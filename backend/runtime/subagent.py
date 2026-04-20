"""First-class SubAgent abstraction for BioAPEX helper agents.

A ``SubAgent`` wraps the existing :func:`run_scoped_agent` helper with an
explicit contract (``name``, ``system_prompt``, ``tools_allowed``,
``max_steps``, ``token_budget``) and persists every run as a JSON artifact
under ``artifacts/subagent/<YYYY-MM-DD>/<run_id>/subagent_run.json`` using
the canonical artifact registry layout.

Plan and verification helper tools re-implement their execution path on top
of this contract so future helpers stay artifact-backed and reviewable.

The outer event flow consumed by :class:`QueryEngine` is unchanged: the
tools still return ``structured_payload`` dicts with the same shape that
drives ``plan_created`` / ``plan_updated`` / ``verification_result`` SSE
events — this module only adds the persisted transcript.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from artifacts.naming import (
    build_run_directory,
    compute_content_hash,
    generate_run_id,
    is_valid_run_id,
    resolve_artifact_path,
)
from config import get_agent_runtime_limit
from tools.contracts import normalize_tool_output

from .helper_agent_runner import _coerce_chunk_text  # noqa: F401 (re-export for tests)

SubAgentStatus = Literal[
    "ok",
    "recursion_cap_exceeded",
    "token_budget_exceeded",
    "error",
]

SUBAGENT_WORKFLOW_SLUG = "subagent"
SUBAGENT_ARTIFACT_TYPE = "subagent_run"
SUBAGENT_ARTIFACT_FILENAME = "subagent_run.json"
SUBAGENT_SCHEMA_VERSION = "1.0.0"


class _TokenBudgetExceeded(Exception):
    """Internal signal raised from the event loop when the token budget trips.

    Funneling the budget exit through the same ``except`` boundary as
    recursion and generic errors keeps every terminal condition classified
    in one place instead of splitting between an inline ``break`` and the
    exception handler.
    """


def _tool_name(tool: Any) -> str:
    name = getattr(tool, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(tool).__name__


def _count_tokens(value: Any) -> int:
    """Lazy import so tests that stub the tokenizer still work."""
    from api.tokens import _count_optional_text

    return _count_optional_text(value)


def _isoformat_z(value: datetime) -> str:
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    aware_utc = aware.astimezone(timezone.utc).replace(microsecond=0)
    return aware_utc.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SubAgentContract:
    """Immutable description of a scoped helper sub-agent.

    ``tools_allowed`` is the final tool list handed to the LLM — callers
    filter with :func:`filter_tools_by_exposure` before constructing the
    contract so policy/exposure metadata stays authoritative.

    ``stable_prefix`` is an optional session-scoped leading prompt fragment
    (workspace files, skill snapshot, tool-result contract, harness guidance)
    captured by :class:`graph.session_manager.SessionManager` on the first
    turn of the parent session. When set, ``run_subagent`` prepends it verbatim
    to ``system_prompt`` so the provider's prefix cache matches the parent
    agent's leading bytes and ~95% of the sub-agent's input is served from
    cache. Adding a skill or editing workspace files mid-session silently
    invalidates the prefix and degrades the cache hit rate; see
    :meth:`SessionManager.freeze_session_prefix` for the drift warning hook.
    """

    name: str
    system_prompt: str
    tools_allowed: tuple[Any, ...]
    max_steps: int
    token_budget: int
    stable_prefix: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("SubAgentContract.name must be a non-empty string.")
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("SubAgentContract.system_prompt must be non-empty.")
        if self.max_steps < 1:
            raise ValueError("SubAgentContract.max_steps must be >= 1.")
        if self.token_budget < 0:
            raise ValueError(
                "SubAgentContract.token_budget must be >= 0 (0 disables the cap)."
            )

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(_tool_name(tool) for tool in self.tools_allowed)

    def composed_system_prompt(self) -> str:
        """Return the final system prompt handed to :func:`create_agent`.

        The stable prefix comes first so its bytes align with the parent
        agent's prefix and participate in the provider's prefix cache.
        """
        if self.stable_prefix and self.stable_prefix.strip():
            return f"{self.stable_prefix}\n\n{self.system_prompt}"
        return self.system_prompt


@dataclass(frozen=True)
class SubAgentArtifact:
    """Result of a :class:`SubAgentContract` run, backed by an on-disk file."""

    run_id: str
    name: str
    status: SubAgentStatus
    response_text: str
    tool_trace: tuple[dict[str, Any], ...]
    verdict: str | None
    tokens_used: int
    steps_used: int
    relative_path: str
    absolute_path: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    cache_stats: dict[str, Any] | None = None


def _extract_llm_usage_event(event: dict[str, Any]) -> dict[str, int] | None:
    """Map a LangChain ``on_chat_model_end`` event into prompt-cache counters.

    LangChain normalizes provider-side cache accounting into
    ``AIMessage.usage_metadata`` — ``input_token_details.cache_read`` and
    ``cache_creation`` are populated for DeepSeek, OpenAI and Anthropic once
    the SDK maps them. Runs without usage metadata (some streamed responses)
    are skipped: the collector only needs samples, not an invariant.
    """
    output = event.get("data", {}).get("output")
    usage = getattr(output, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    input_tokens = int(usage.get("input_tokens") or 0)
    details = usage.get("input_token_details") or {}
    if not isinstance(details, dict):
        details = {}
    cache_read = int(details.get("cache_read") or 0)
    cache_creation = int(details.get("cache_creation") or 0)
    if input_tokens <= 0 and cache_read <= 0 and cache_creation <= 0:
        return None
    return {
        "input_tokens": input_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_creation,
    }


def _observe_llm_usage(usage: dict[str, int], *, subagent_name: str) -> None:
    """Forward per-call usage samples to the process-wide metrics collector.

    Import is deferred so this module stays usable in unit tests that stub
    the Prometheus surface.
    """
    try:
        from runtime.metrics_collector import METRICS
    except Exception:  # pragma: no cover — defensive
        return
    METRICS.observe_llm_usage(
        input_tokens=usage["input_tokens"],
        cache_read_tokens=usage["cache_read_tokens"],
        cache_creation_tokens=usage["cache_creation_tokens"],
    )


def _normalize_tool_input(raw_input: Any) -> str:
    if isinstance(raw_input, dict) and len(raw_input) == 1:
        return str(next(iter(raw_input.values())))
    return str(raw_input)


def _build_artifact_payload(
    *,
    contract: SubAgentContract,
    run_id: str,
    created_at: datetime,
    user_prompt: str,
    response_text: str,
    tool_trace: Iterable[dict[str, Any]],
    status: SubAgentStatus,
    tokens_used: int,
    steps_used: int,
    verdict: str | None,
    error: str | None,
    extra_metadata: dict[str, Any] | None,
    cache_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_list = [dict(item) for item in tool_trace]
    payload: dict[str, Any] = {
        "schema_version": SUBAGENT_SCHEMA_VERSION,
        "artifact_type": SUBAGENT_ARTIFACT_TYPE,
        "run_id": run_id,
        "created_at": _isoformat_z(created_at),
        "source_workflow": SUBAGENT_WORKFLOW_SLUG,
        "source_tool": contract.name,
        "subagent": {
            "name": contract.name,
            "max_steps": contract.max_steps,
            "token_budget": contract.token_budget,
            "tools_allowed": list(contract.tool_names),
            "stable_prefix_bytes": len(contract.stable_prefix.encode("utf-8"))
            if contract.stable_prefix
            else 0,
        },
        "inputs": {
            "system_prompt": contract.system_prompt,
            "user_prompt": user_prompt,
        },
        "outputs": {
            "response_text": response_text,
            "tool_trace": trace_list,
        },
        "status": status,
        "tokens_used": tokens_used,
        "steps_used": steps_used,
        "verdict": verdict,
        "error": error,
    }
    if cache_stats is not None:
        payload["cache_stats"] = cache_stats
    if extra_metadata:
        payload["metadata"] = dict(extra_metadata)
    return payload


def _write_artifact(
    *,
    base_dir: Path,
    run_id: str,
    created_at: datetime,
    payload: dict[str, Any],
) -> tuple[str, Path]:
    relative_run_dir = build_run_directory(
        SUBAGENT_WORKFLOW_SLUG,
        created_at=created_at,
        run_id=run_id,
    )
    run_dir = resolve_artifact_path(base_dir, relative_run_dir, must_not_exist=False)
    run_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = run_dir / SUBAGENT_ARTIFACT_FILENAME
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    artifact_path.write_text(rendered, encoding="utf-8")

    # Hash manifest makes the artifact registry-complete without a full
    # workflow run record — we intentionally skip generating a run.json so
    # subagent runs are not conflated with authored workflow executions.
    hash_manifest = {
        "schema_version": SUBAGENT_SCHEMA_VERSION,
        "artifact_type": "content_hash_manifest",
        "run_id": run_id,
        "created_at": _isoformat_z(created_at),
        "source_workflow": SUBAGENT_WORKFLOW_SLUG,
        "source_tool": payload.get("source_tool") or SUBAGENT_WORKFLOW_SLUG,
        "hashes": {
            SUBAGENT_ARTIFACT_FILENAME: {
                "algorithm": "sha256",
                "digest": compute_content_hash(rendered),
            }
        },
    }
    (run_dir / "content_hashes.json").write_text(
        json.dumps(hash_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    relative = artifact_path.resolve().relative_to(Path(base_dir).resolve()).as_posix()
    return relative, artifact_path


async def run_subagent(
    contract: SubAgentContract,
    *,
    llm: Any,
    user_prompt: str,
    base_dir: str | Path,
    run_id: str | None = None,
    created_at: datetime | None = None,
    verdict: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> SubAgentArtifact:
    """Execute ``contract`` and persist the run transcript as an artifact.

    ``max_steps`` is enforced through the LangGraph ``recursion_limit``
    configuration; a :class:`langgraph.errors.GraphRecursionError` (or any
    other runtime exception) produces a status of ``recursion_cap_exceeded``
    or ``error`` respectively.

    ``token_budget`` is enforced via a per-run counter mirroring
    :meth:`QueryEngine._budget_exceeded`: when tokens consumed across
    streamed chunks, tool inputs, and tool outputs exceed the budget we stop
    consuming events and persist the partial transcript.
    """
    if run_id is not None and not is_valid_run_id(run_id):
        raise ValueError(f"Invalid run_id format: {run_id!r}")

    if created_at is None:
        if run_id is not None:
            # Derive timestamp from the supplied run_id so the canonical
            # path ``artifacts/subagent/<YYYY-MM-DD>/<run_id>/`` stays
            # internally consistent.
            stamp = run_id[len("run-") : len("run-") + 16]
            created_at = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            created_at = datetime.now(timezone.utc)
    created_at = created_at.astimezone(timezone.utc).replace(microsecond=0)

    if run_id is None:
        run_id = generate_run_id(now=created_at)

    composed_prompt = contract.composed_system_prompt()
    agent = create_agent(llm, list(contract.tools_allowed), system_prompt=composed_prompt)
    recursion_limit = max(25, contract.max_steps)
    response_chunks: list[str] = []
    tool_trace: list[dict[str, Any]] = []
    pending: dict[Any, int] = {}
    tokens_used = _count_tokens(composed_prompt) + _count_tokens(user_prompt)
    steps_used = 0
    status: SubAgentStatus = "ok"
    error: str | None = None
    budget = max(0, contract.token_budget)
    cache_stats = {
        "llm_calls": 0,
        "input_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "uncached_tokens": 0,
        "cache_hit_rate": 0.0,
    }

    def _over_budget() -> bool:
        return budget > 0 and tokens_used > budget

    try:
        async for event in agent.astream_events(
            {"messages": [HumanMessage(content=user_prompt)]},
            version="v2",
            config={"recursion_limit": recursion_limit},
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                text = _coerce_chunk_text(getattr(chunk, "content", ""))
                if text:
                    response_chunks.append(text)
                    tokens_used += _count_tokens(text)
            elif kind == "on_chat_model_end":
                usage_event = _extract_llm_usage_event(event)
                if usage_event is not None:
                    cache_stats["llm_calls"] += 1
                    cache_stats["input_tokens"] += usage_event["input_tokens"]
                    cache_stats["cache_read_tokens"] += usage_event["cache_read_tokens"]
                    cache_stats["cache_creation_tokens"] += usage_event[
                        "cache_creation_tokens"
                    ]
                    _observe_llm_usage(usage_event, subagent_name=contract.name)
            elif kind == "on_tool_start":
                run_event_id = event.get("run_id")
                raw_input = event.get("data", {}).get("input", {})
                tool_input = _normalize_tool_input(raw_input)
                pending[run_event_id] = len(tool_trace)
                tool_trace.append(
                    {
                        "tool": event.get("name"),
                        "input": tool_input,
                        "run_id": run_event_id,
                    }
                )
                steps_used += 1
                tokens_used += _count_tokens(tool_input)
            elif kind == "on_tool_end":
                run_event_id = event.get("run_id")
                raw_output = event.get("data", {}).get("output", "")
                result = normalize_tool_output(event.get("name", ""), raw_output)
                index = pending.pop(run_event_id, None)
                payload_entry = {
                    "tool": event.get("name"),
                    "run_id": run_event_id,
                    "output": result.summary,
                    "result": result.model_dump(mode="json"),
                }
                if index is None:
                    tool_trace.append(payload_entry)
                else:
                    tool_trace[index] = {**tool_trace[index], **payload_entry}
                tokens_used += _count_tokens(result.summary)

            if _over_budget():
                raise _TokenBudgetExceeded()
    except _TokenBudgetExceeded:
        status = "token_budget_exceeded"
    except Exception as exc:  # noqa: BLE001 — classify at the boundary
        if _is_recursion_error(exc):
            status = "recursion_cap_exceeded"
        else:
            status = "error"
        error = str(exc) or exc.__class__.__name__

    # Finalize the cache hit rate for the artifact so per-run inspection is
    # possible alongside the process-wide Prometheus gauge.
    total_input = (
        cache_stats["cache_read_tokens"]
        + cache_stats["cache_creation_tokens"]
        + max(
            0,
            cache_stats["input_tokens"]
            - cache_stats["cache_read_tokens"]
            - cache_stats["cache_creation_tokens"],
        )
    )
    cache_stats["uncached_tokens"] = max(
        0,
        cache_stats["input_tokens"]
        - cache_stats["cache_read_tokens"]
        - cache_stats["cache_creation_tokens"],
    )
    cache_stats["cache_hit_rate"] = (
        cache_stats["cache_read_tokens"] / total_input
    ) if total_input > 0 else 0.0

    response_text = "".join(response_chunks).strip()
    artifact_payload = _build_artifact_payload(
        contract=contract,
        run_id=run_id,
        created_at=created_at,
        user_prompt=user_prompt,
        response_text=response_text,
        tool_trace=tool_trace,
        status=status,
        tokens_used=tokens_used,
        steps_used=steps_used,
        verdict=verdict,
        error=error,
        extra_metadata=extra_metadata,
        cache_stats=cache_stats if cache_stats["llm_calls"] > 0 else None,
    )

    relative_path, absolute_path = _write_artifact(
        base_dir=Path(base_dir),
        run_id=run_id,
        created_at=created_at,
        payload=artifact_payload,
    )

    return SubAgentArtifact(
        run_id=run_id,
        name=contract.name,
        status=status,
        response_text=response_text,
        tool_trace=tuple(tool_trace),
        verdict=verdict,
        tokens_used=tokens_used,
        steps_used=steps_used,
        relative_path=relative_path,
        absolute_path=str(absolute_path),
        payload=artifact_payload,
        error=error,
        cache_stats=dict(cache_stats) if cache_stats["llm_calls"] > 0 else None,
    )


def _is_recursion_error(exc: BaseException) -> bool:
    """Detect LangGraph recursion-cap exits without a hard dependency."""
    try:
        from langgraph.errors import GraphRecursionError  # type: ignore
    except Exception:  # pragma: no cover — fallback path
        GraphRecursionError = ()  # type: ignore[assignment]

    if GraphRecursionError and isinstance(exc, GraphRecursionError):
        return True
    message = str(exc).lower()
    return "recursion" in message and ("limit" in message or "cap" in message)


def default_max_steps() -> int:
    return get_agent_runtime_limit("helper_agent_recursion_limit", 1000)


def default_token_budget() -> int:
    from config import get_max_tokens_per_turn

    return get_max_tokens_per_turn()


def resolve_session_stable_prefix() -> str:
    """Return the parent session's frozen stable prefix, or ``""``.

    Sub-agent tools call this from inside a ``tool_policy_context`` so the
    frozen prefix captured on the parent turn is reused verbatim. When the
    session or session manager is unavailable (tests, one-off CLI runs) this
    returns an empty string and the sub-agent falls back to its own system
    prompt — correct behaviour, at the cost of no prompt-cache hits.
    """
    try:
        from graph.agent import agent_manager
        from tools.policy import get_tool_policy_context
    except Exception:  # pragma: no cover — defensive import path
        return ""

    policy_context = get_tool_policy_context()
    if policy_context is None or not policy_context.session_id:
        return ""
    session_manager = getattr(agent_manager, "session_manager", None)
    if session_manager is None:
        return ""
    frozen = session_manager.get_frozen_session_prefix(policy_context.session_id)
    if frozen is None:
        return ""
    return frozen.stable_prefix


__all__ = [
    "SUBAGENT_ARTIFACT_FILENAME",
    "SUBAGENT_ARTIFACT_TYPE",
    "SUBAGENT_SCHEMA_VERSION",
    "SUBAGENT_WORKFLOW_SLUG",
    "SubAgentArtifact",
    "SubAgentContract",
    "SubAgentStatus",
    "default_max_steps",
    "default_token_budget",
    "resolve_session_stable_prefix",
    "run_subagent",
]
