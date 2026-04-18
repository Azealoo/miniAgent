"""Unit tests for the runtime metrics collector and /api/metrics endpoint.

Drive one event of each runtime event type through the collector and assert
the Prometheus exposition text carries the expected metric name and value.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime.metrics_collector import MetricsCollector, METRICS


@pytest.fixture
def collector() -> MetricsCollector:
    """Fresh collector per test to avoid cross-test state leakage."""
    return MetricsCollector()


# ---------------------------------------------------------------------- #
# Per-event-type smoke tests                                               #
# ---------------------------------------------------------------------- #


def test_token_event_records_output_tokens(collector: MetricsCollector) -> None:
    collector.observe_event({"type": "token", "content": "hello world"})
    text = collector.render_exposition()
    assert "# TYPE bioapex_tokens_output_total counter" in text
    # The fallback tokenizer returns at least 1 token for any non-empty string.
    line = next(
        line for line in text.splitlines() if line.startswith("bioapex_tokens_output_total ")
    )
    _, _, value = line.partition(" ")
    assert int(value) >= 1


def test_tool_start_and_tool_end_events_record_invocation_and_duration(
    collector: MetricsCollector,
) -> None:
    collector.observe_event(
        {
            "type": "tool_start",
            "tool": "read_file",
            "run_id": "run-1",
            "input": "memory/MEMORY.md",
        }
    )
    collector.observe_event(
        {
            "type": "tool_end",
            "tool": "read_file",
            "run_id": "run-1",
            "output": "# Memory\n",
            "result": {"status": "success", "outcome": "success"},
        }
    )
    text = collector.render_exposition()
    assert 'bioapex_tool_invocations_total{tool="read_file"} 1' in text
    assert 'bioapex_tool_duration_seconds_count{tool="read_file"} 1' in text
    assert 'bioapex_tool_duration_seconds_bucket{le="+Inf",tool="read_file"} 1' in text


def test_tool_end_with_error_outcome_records_tool_error(
    collector: MetricsCollector,
) -> None:
    collector.observe_event(
        {
            "type": "tool_start",
            "tool": "terminal",
            "run_id": "run-err",
            "input": "bad command",
        }
    )
    collector.observe_event(
        {
            "type": "tool_end",
            "tool": "terminal",
            "run_id": "run-err",
            "output": "",
            "result": {"status": "error", "outcome": "error"},
        }
    )
    text = collector.render_exposition()
    assert 'bioapex_tool_errors_total{tool="terminal"} 1' in text


def test_new_response_event_records_segment_counter(
    collector: MetricsCollector,
) -> None:
    collector.observe_event({"type": "new_response"})
    text = collector.render_exposition()
    assert "bioapex_new_response_segments_total 1" in text


def test_compaction_event_records_counter(collector: MetricsCollector) -> None:
    collector.observe_event(
        {
            "type": "compaction_event",
            "from_turn": 0,
            "to_turn": 4,
            "summary": "compacted",
            "saved_tokens": 1200,
        }
    )
    text = collector.render_exposition()
    assert "bioapex_compaction_events_total 1" in text


def test_verification_result_event_records_by_verdict(
    collector: MetricsCollector,
) -> None:
    collector.observe_event(
        {
            "type": "verification_result",
            "summary": "ok",
            "verdict": "pass",
            "verification": {"verdict": "pass"},
        }
    )
    text = collector.render_exposition()
    assert 'bioapex_verification_results_total{verdict="pass"} 1' in text


def test_error_event_records_runtime_error(collector: MetricsCollector) -> None:
    collector.observe_event({"type": "error", "error": "boom"})
    text = collector.render_exposition()
    assert "bioapex_runtime_errors_total 1" in text


def test_retrieval_event_with_results_records_cache_hit(
    collector: MetricsCollector,
) -> None:
    collector.observe_event(
        {
            "type": "retrieval",
            "query": "brca1",
            "results": [{"text": "x", "source": "a", "score": 0.1}],
        }
    )
    text = collector.render_exposition()
    assert "bioapex_retrieval_queries_total 1" in text
    assert "bioapex_retrieval_cache_hits_total 1" in text
    assert "bioapex_retrieval_cache_misses_total 0" in text
    assert "bioapex_retrieval_cache_hit_ratio 1" in text


def test_retrieval_miss_updates_hit_ratio(collector: MetricsCollector) -> None:
    collector.observe_retrieval(hit=True)
    collector.observe_retrieval(hit=False)
    text = collector.render_exposition()
    assert "bioapex_retrieval_queries_total 2" in text
    assert "bioapex_retrieval_cache_hits_total 1" in text
    assert "bioapex_retrieval_cache_misses_total 1" in text
    assert any(
        line.startswith("bioapex_retrieval_cache_hit_ratio ")
        and line.endswith(" 0.5")
        for line in text.splitlines()
    )


def test_done_event_records_turn_and_status(collector: MetricsCollector) -> None:
    collector.observe_event({"type": "done", "turn_status": "ok"})
    text = collector.render_exposition()
    assert "bioapex_turns_total 1" in text
    assert 'bioapex_turns_by_status_total{status="ok"} 1' in text


def test_record_input_tokens_updates_counter(collector: MetricsCollector) -> None:
    collector.record_input_tokens(42)
    text = collector.render_exposition()
    assert "bioapex_tokens_input_total 42" in text


# ---------------------------------------------------------------------- #
# Exposition shape                                                         #
# ---------------------------------------------------------------------- #


def test_exposition_documents_at_least_ten_core_metrics(
    collector: MetricsCollector,
) -> None:
    text = collector.render_exposition()
    help_lines = [line for line in text.splitlines() if line.startswith("# HELP ")]
    type_lines = [line for line in text.splitlines() if line.startswith("# TYPE ")]
    assert len(help_lines) == len(type_lines)
    assert len(help_lines) >= 10


def test_exposition_lists_every_core_metric_name(
    collector: MetricsCollector,
) -> None:
    text = collector.render_exposition()
    expected_names = {
        "bioapex_turns_total",
        "bioapex_turns_by_status_total",
        "bioapex_tokens_input_total",
        "bioapex_tokens_output_total",
        "bioapex_tool_invocations_total",
        "bioapex_tool_errors_total",
        "bioapex_tool_duration_seconds",
        "bioapex_compaction_events_total",
        "bioapex_new_response_segments_total",
        "bioapex_verification_results_total",
        "bioapex_runtime_errors_total",
        "bioapex_retrieval_queries_total",
        "bioapex_retrieval_cache_hits_total",
        "bioapex_retrieval_cache_misses_total",
        "bioapex_retrieval_cache_hit_ratio",
    }
    for name in expected_names:
        assert f"# TYPE {name} " in text, f"missing TYPE header for {name}"


# ---------------------------------------------------------------------- #
# HTTP endpoint                                                            #
# ---------------------------------------------------------------------- #


def test_metrics_endpoint_returns_prometheus_text() -> None:
    from api.metrics import PROMETHEUS_CONTENT_TYPE, router

    METRICS.reset()
    METRICS.observe_event({"type": "done", "turn_status": "ok"})

    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(PROMETHEUS_CONTENT_TYPE.split(";")[0])
    body = response.text
    assert "# HELP bioapex_turns_total" in body
    assert "bioapex_turns_total 1" in body

    METRICS.reset()
