"""In-process Prometheus metrics collector for BioAPEX runtime.

The collector is intentionally framework-free: the project prefers minimal
dependencies (see CLAUDE.md), so metric state lives in plain dicts guarded
by a lock and the Prometheus text exposition format is hand-formatted.

Feed the collector with runtime events via :meth:`MetricsCollector.observe_event`
on the chat turn hot-path (``runtime/query_engine.py``). Miss signals that do
not correspond to emitted events (e.g. empty retrievals) can be recorded with
explicit ``observe_*`` helpers. ``render_exposition`` produces the bytes the
``/api/metrics`` route returns.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Iterable


# Keep buckets aligned with Prometheus' default histogram buckets so Grafana
# templates "just work" without extra configuration.
_DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: dict[str, str] | None) -> str:
    if not labels:
        return ""
    parts = [
        f'{key}="{_escape_label_value(str(val))}"'
        for key, val in sorted(labels.items())
    ]
    return "{" + ",".join(parts) + "}"


def _format_float(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


class MetricsCollector:
    """Thread-safe in-process counter/histogram/gauge registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[tuple[tuple[str, str], ...], float]] = {}
        self._gauges: dict[str, dict[tuple[tuple[str, str], ...], float]] = {}
        self._histograms: dict[
            str,
            dict[tuple[tuple[str, str], ...], dict[str, Any]],
        ] = {}
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}
        self._tool_start_times: dict[str, tuple[str, float]] = {}

        self._register_defaults()

    # ------------------------------------------------------------------ #
    # Metric registration                                                  #
    # ------------------------------------------------------------------ #

    def _register(self, name: str, mtype: str, help_text: str) -> None:
        self._help[name] = help_text
        self._types[name] = mtype
        if mtype == "counter":
            self._counters.setdefault(name, {})
        elif mtype == "gauge":
            self._gauges.setdefault(name, {})
        elif mtype == "histogram":
            self._histograms.setdefault(name, {})

    def _register_defaults(self) -> None:
        self._register(
            "bioapex_turns_total",
            "counter",
            "Total chat turns completed (one per done event).",
        )
        self._register(
            "bioapex_turns_by_status_total",
            "counter",
            "Total chat turns completed, labeled by turn_status.",
        )
        self._register(
            "bioapex_tokens_input_total",
            "counter",
            "Total input tokens observed on the turn hot-path.",
        )
        self._register(
            "bioapex_tokens_output_total",
            "counter",
            "Total output tokens observed on the turn hot-path.",
        )
        self._register(
            "bioapex_tool_invocations_total",
            "counter",
            "Total tool invocations started, labeled by tool name.",
        )
        self._register(
            "bioapex_tool_errors_total",
            "counter",
            "Total tool invocations that ended in an error outcome.",
        )
        self._register(
            "bioapex_tool_duration_seconds",
            "histogram",
            "Tool invocation wall-clock duration in seconds.",
        )
        self._register(
            "bioapex_compaction_events_total",
            "counter",
            "Total turn-boundary history compaction events emitted.",
        )
        self._register(
            "bioapex_new_response_segments_total",
            "counter",
            "Total new_response segment markers emitted during streaming.",
        )
        self._register(
            "bioapex_verification_results_total",
            "counter",
            "Total verification_result events, labeled by verdict.",
        )
        self._register(
            "bioapex_runtime_errors_total",
            "counter",
            "Total runtime error events emitted from the chat turn loop.",
        )
        self._register(
            "bioapex_retrieval_queries_total",
            "counter",
            "Total memory retrieval lookups attempted (hits plus misses).",
        )
        self._register(
            "bioapex_retrieval_cache_hits_total",
            "counter",
            "Retrieval lookups that returned at least one result.",
        )
        self._register(
            "bioapex_retrieval_cache_misses_total",
            "counter",
            "Retrieval lookups that returned no results or raised.",
        )
        self._register(
            "bioapex_retrieval_cache_hit_ratio",
            "gauge",
            "Rolling ratio of retrieval hits over total retrieval queries.",
        )
        self._register(
            "bioapex_retrieval_errors_total",
            "counter",
            "Retrieval lookups that raised, labeled by exception class name.",
        )
        self._register(
            "bioapex_prompt_cache_read_tokens_total",
            "counter",
            "Input tokens served from the provider-side prompt cache.",
        )
        self._register(
            "bioapex_prompt_cache_creation_tokens_total",
            "counter",
            "Input tokens written to the provider-side prompt cache.",
        )
        self._register(
            "bioapex_prompt_cache_uncached_tokens_total",
            "counter",
            "Input tokens that were neither cache-read nor cache-write.",
        )
        self._register(
            "bioapex_prompt_cache_hit_rate",
            "gauge",
            "Rolling ratio cache_read_tokens / total_input_tokens across LLM calls.",
        )
        self._register(
            "bioapex_approval_store_load_errors_total",
            "counter",
            "Turns where the on-disk approval store failed to load and destructive tools were forced closed.",
        )

    # ------------------------------------------------------------------ #
    # Mutation helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _label_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        if not labels:
            return ()
        return tuple(sorted((k, str(v)) for k, v in labels.items()))

    def _inc_counter(
        self,
        name: str,
        *,
        amount: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = self._label_key(labels)
        with self._lock:
            family = self._counters.setdefault(name, {})
            family[key] = family.get(key, 0.0) + amount

    def _set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = self._label_key(labels)
        with self._lock:
            family = self._gauges.setdefault(name, {})
            family[key] = float(value)

    def _observe_histogram(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = self._label_key(labels)
        with self._lock:
            family = self._histograms.setdefault(name, {})
            entry = family.get(key)
            if entry is None:
                entry = {
                    "buckets": {bound: 0 for bound in _DEFAULT_BUCKETS},
                    "inf": 0,
                    "sum": 0.0,
                    "count": 0,
                }
                family[key] = entry
            for bound in _DEFAULT_BUCKETS:
                if value <= bound:
                    entry["buckets"][bound] += 1
            entry["inf"] += 1
            entry["sum"] += float(value)
            entry["count"] += 1

    # ------------------------------------------------------------------ #
    # Public recording API                                                 #
    # ------------------------------------------------------------------ #

    def record_input_tokens(self, n: int) -> None:
        if n > 0:
            self._inc_counter("bioapex_tokens_input_total", amount=float(n))

    def record_output_tokens(self, n: int) -> None:
        if n > 0:
            self._inc_counter("bioapex_tokens_output_total", amount=float(n))

    def observe_retrieval(self, *, hit: bool) -> None:
        self._inc_counter("bioapex_retrieval_queries_total")
        if hit:
            self._inc_counter("bioapex_retrieval_cache_hits_total")
        else:
            self._inc_counter("bioapex_retrieval_cache_misses_total")
        self._recompute_hit_ratio()

    def observe_approval_store_load_error(self) -> None:
        """Record a turn where the on-disk approval store could not be loaded."""
        self._inc_counter("bioapex_approval_store_load_errors_total")

    def observe_retrieval_error(self, *, error_type: str) -> None:
        """Record a retrieval attempt that raised.

        Does not touch ``bioapex_retrieval_queries_total`` or the hit/miss
        counters — callers keep invoking ``observe_retrieval(hit=False)`` on
        the error path so the miss ratio stays comparable across releases.
        """
        label = error_type if error_type else "Exception"
        self._inc_counter(
            "bioapex_retrieval_errors_total",
            labels={"error_type": label},
        )

    def _recompute_hit_ratio(self) -> None:
        with self._lock:
            hits = self._counters.get("bioapex_retrieval_cache_hits_total", {}).get((), 0.0)
            misses = self._counters.get("bioapex_retrieval_cache_misses_total", {}).get((), 0.0)
            total = hits + misses
            ratio = (hits / total) if total > 0 else 0.0
            self._gauges.setdefault("bioapex_retrieval_cache_hit_ratio", {})[()] = ratio

    def observe_llm_usage(
        self,
        *,
        input_tokens: int,
        cache_read_tokens: int,
        cache_creation_tokens: int,
    ) -> None:
        """Record a per-call LLM usage sample and refresh the cache hit rate.

        Token counts come from LangChain's normalized ``usage_metadata`` on
        ``AIMessage`` responses (``input_tokens`` plus ``input_token_details``
        with ``cache_read`` and ``cache_creation`` keys). DeepSeek, OpenAI and
        Anthropic all surface the same shape once LangChain has mapped it, so
        the metric is provider-agnostic.
        """
        cache_read = max(0, int(cache_read_tokens))
        cache_creation = max(0, int(cache_creation_tokens))
        total_input = max(cache_read + cache_creation, int(input_tokens))
        uncached = max(0, total_input - cache_read - cache_creation)

        if cache_read:
            self._inc_counter(
                "bioapex_prompt_cache_read_tokens_total",
                amount=float(cache_read),
            )
        if cache_creation:
            self._inc_counter(
                "bioapex_prompt_cache_creation_tokens_total",
                amount=float(cache_creation),
            )
        if uncached:
            self._inc_counter(
                "bioapex_prompt_cache_uncached_tokens_total",
                amount=float(uncached),
            )
        self._recompute_prompt_cache_hit_rate()

    def _recompute_prompt_cache_hit_rate(self) -> None:
        with self._lock:
            read = self._counters.get(
                "bioapex_prompt_cache_read_tokens_total", {}
            ).get((), 0.0)
            creation = self._counters.get(
                "bioapex_prompt_cache_creation_tokens_total", {}
            ).get((), 0.0)
            uncached = self._counters.get(
                "bioapex_prompt_cache_uncached_tokens_total", {}
            ).get((), 0.0)
            total = read + creation + uncached
            rate = (read / total) if total > 0 else 0.0
            self._gauges.setdefault("bioapex_prompt_cache_hit_rate", {})[()] = rate

    def observe_event(self, event: dict[str, Any]) -> None:
        """Update metrics from a runtime event payload.

        Accepts the internal event dict shape used by ``QueryEngine``. Unknown
        event types are ignored so new runtime events do not break metrics.
        """
        event_type = event.get("type")
        if event_type == "token":
            content = event.get("content")
            if isinstance(content, str) and content:
                self.record_output_tokens(_token_estimate(content))
            return

        if event_type == "tool_start":
            run_id = str(event.get("run_id") or event.get("tool") or "")
            tool = str(event.get("tool") or "unknown")
            self._inc_counter(
                "bioapex_tool_invocations_total",
                labels={"tool": tool},
            )
            tool_input = event.get("input")
            if tool_input is not None:
                self.record_input_tokens(_token_estimate(tool_input))
            if run_id:
                with self._lock:
                    self._tool_start_times[run_id] = (tool, time.monotonic())
            return

        if event_type == "tool_end":
            run_id = str(event.get("run_id") or event.get("tool") or "")
            tool = str(event.get("tool") or "unknown")
            output = event.get("output")
            if output is not None:
                self.record_output_tokens(_token_estimate(output))

            started_at: float | None = None
            started_tool: str | None = None
            if run_id:
                with self._lock:
                    entry = self._tool_start_times.pop(run_id, None)
                if entry is not None:
                    started_tool, started_at = entry

            if started_at is not None:
                duration = max(0.0, time.monotonic() - started_at)
                self._observe_histogram(
                    "bioapex_tool_duration_seconds",
                    duration,
                    labels={"tool": started_tool or tool},
                )

            result = event.get("result")
            outcome: str | None = None
            status: str | None = None
            if isinstance(result, dict):
                outcome_val = result.get("outcome")
                status_val = result.get("status")
                if isinstance(outcome_val, str):
                    outcome = outcome_val
                if isinstance(status_val, str):
                    status = status_val
            is_error = status == "error" or (outcome is not None and outcome not in {"success", "ok", "needs_approval"})
            if is_error:
                self._inc_counter(
                    "bioapex_tool_errors_total",
                    labels={"tool": tool},
                )
            return

        if event_type == "new_response":
            self._inc_counter("bioapex_new_response_segments_total")
            return

        if event_type == "compaction_event":
            self._inc_counter("bioapex_compaction_events_total")
            return

        if event_type == "verification_result":
            verdict = event.get("verdict")
            verdict_label = verdict if isinstance(verdict, str) and verdict else "unknown"
            self._inc_counter(
                "bioapex_verification_results_total",
                labels={"verdict": verdict_label},
            )
            return

        if event_type == "error":
            self._inc_counter("bioapex_runtime_errors_total")
            return

        if event_type == "retrieval":
            results = event.get("results")
            hit = isinstance(results, list) and len(results) > 0
            self.observe_retrieval(hit=hit)
            return

        if event_type == "retrieval_error":
            error_type = event.get("error_type")
            self.observe_retrieval_error(
                error_type=str(error_type) if isinstance(error_type, str) else "Exception",
            )
            return

        if event_type == "llm_usage":
            self.observe_llm_usage(
                input_tokens=int(event.get("input_tokens") or 0),
                cache_read_tokens=int(event.get("cache_read_tokens") or 0),
                cache_creation_tokens=int(event.get("cache_creation_tokens") or 0),
            )
            return

        if event_type == "done":
            self._inc_counter("bioapex_turns_total")
            status = event.get("turn_status") or event.get("status")
            status_label = status if isinstance(status, str) and status else "ok"
            self._inc_counter(
                "bioapex_turns_by_status_total",
                labels={"status": status_label},
            )
            return

    # ------------------------------------------------------------------ #
    # Exposition                                                           #
    # ------------------------------------------------------------------ #

    def render_exposition(self) -> str:
        """Render the Prometheus text exposition format."""
        with self._lock:
            lines: list[str] = []
            ordered_names: list[str] = sorted(self._types.keys())
            for name in ordered_names:
                mtype = self._types[name]
                help_text = self._help.get(name, "")
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {mtype}")
                if mtype == "counter":
                    family = self._counters.get(name, {})
                    if not family:
                        lines.append(f"{name} 0")
                    else:
                        for label_key in sorted(family.keys()):
                            value = family[label_key]
                            labels = dict(label_key)
                            lines.append(f"{name}{_format_labels(labels)} {_format_float(value)}")
                elif mtype == "gauge":
                    family = self._gauges.get(name, {})
                    if not family:
                        lines.append(f"{name} 0")
                    else:
                        for label_key in sorted(family.keys()):
                            value = family[label_key]
                            labels = dict(label_key)
                            lines.append(f"{name}{_format_labels(labels)} {_format_float(value)}")
                elif mtype == "histogram":
                    family = self._histograms.get(name, {})
                    if not family:
                        for bound in _DEFAULT_BUCKETS:
                            lines.append(f'{name}_bucket{{le="{_format_float(bound)}"}} 0')
                        lines.append(f'{name}_bucket{{le="+Inf"}} 0')
                        lines.append(f"{name}_sum 0")
                        lines.append(f"{name}_count 0")
                    else:
                        for label_key in sorted(family.keys()):
                            entry = family[label_key]
                            labels = dict(label_key)
                            cumulative = 0
                            for bound in _DEFAULT_BUCKETS:
                                cumulative = entry["buckets"][bound]
                                bucket_labels = dict(labels)
                                bucket_labels["le"] = _format_float(bound)
                                lines.append(
                                    f"{name}_bucket{_format_labels(bucket_labels)} {cumulative}"
                                )
                            inf_labels = dict(labels)
                            inf_labels["le"] = "+Inf"
                            lines.append(
                                f"{name}_bucket{_format_labels(inf_labels)} {entry['inf']}"
                            )
                            lines.append(
                                f"{name}_sum{_format_labels(labels)} {_format_float(entry['sum'])}"
                            )
                            lines.append(
                                f"{name}_count{_format_labels(labels)} {entry['count']}"
                            )
            return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------ #
    # Test / maintenance                                                   #
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Clear accumulated metric state. Intended for tests."""
        with self._lock:
            for family in self._counters.values():
                family.clear()
            for family in self._gauges.values():
                family.clear()
            for family in self._histograms.values():
                family.clear()
            self._tool_start_times.clear()

    def documented_metric_names(self) -> Iterable[str]:
        return tuple(sorted(self._types.keys()))


def _token_estimate(value: Any) -> int:
    """Delegate to the shared token accounting helper, with a safe fallback.

    Importing ``api.tokens`` pulls FastAPI which is unavailable during some
    unit tests; fall back to a deterministic byte-based estimate.
    """
    try:
        from api.tokens import _count_optional_text

        return _count_optional_text(value)
    except Exception:
        if value is None:
            return 0
        text = value if isinstance(value, str) else str(value)
        if not text:
            return 0
        return max(1, len(text.encode("utf-8")) // 4)


METRICS = MetricsCollector()
"""Module-level singleton used by the chat hot-path and the /api/metrics route."""
