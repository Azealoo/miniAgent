"""Tests for the default/escalation output-token cap in runtime.model_factory.

Covers:
- ``build_chat_model`` forwards the default cap (8000) to the provider.
- ``invoke_with_escalation`` keeps the first response when the model stops
  for reasons other than the cap.
- ``invoke_with_escalation`` escalates once to the higher cap on
  ``finish_reason='length'`` (OpenAI/DeepSeek) and records an audit line.
- Escalation is also triggered by Anthropic-style ``stop_reason='max_tokens'``
  so the helper is provider-agnostic.
- When the escalated call also hits the cap, the audit line outcome is
  ``still_capped`` but the retry response is still returned.
- When the escalated call raises, the original response is returned and the
  audit line outcome is ``retry_failed``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class _RecordingChatModel:
    """Stand-in for ChatOpenAI / ChatDeepSeek that captures init kwargs."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = dict(kwargs)


def _write_cap_config(tmp_path: Path, *, default: int, escalated: int) -> Path:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "llm_output_token_cap": {
                    "default": default,
                    "escalated": escalated,
                }
            }
        ),
        encoding="utf-8",
    )
    return cfg_file


class TestDefaultCapForwarded:
    def test_build_chat_model_forwards_default_cap(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_chat_model("executor")

        assert isinstance(client, _RecordingChatModel)
        assert client.kwargs["max_tokens"] == 8000

    def test_build_chat_model_forwards_override(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_chat_model(
                    "executor",
                    max_tokens_override=65536,
                )

        assert client.kwargs["max_tokens"] == 65536

    def test_build_chat_model_omits_cap_when_disabled(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=0, escalated=0)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_chat_model("executor")

        assert "max_tokens" not in client.kwargs


class TestInvokeWithEscalation:
    @pytest.mark.asyncio
    async def test_no_escalation_when_cap_not_hit(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            ok_response = SimpleNamespace(
                content="short answer",
                response_metadata={"finish_reason": "stop"},
            )
            primary_model = SimpleNamespace(ainvoke=AsyncMock(return_value=ok_response))

            with patch.object(model_factory, "build_chat_model") as build_mock:
                result = await model_factory.invoke_with_escalation(
                    "title",
                    [SimpleNamespace(content="hi")],
                    model=primary_model,
                    base_dir=tmp_path,
                )

            assert result is ok_response
            primary_model.ainvoke.assert_awaited_once()
            build_mock.assert_not_called()

        # No audit event should have been written.
        audit_dir = tmp_path / "storage" / "audit"
        assert not audit_dir.exists() or not any(audit_dir.iterdir())

    @pytest.mark.asyncio
    async def test_escalates_once_on_length_finish_reason(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory
            from audit.store import query_audit_events

            capped_response = SimpleNamespace(
                content="partial...",
                response_metadata={"finish_reason": "length"},
            )
            retry_response = SimpleNamespace(
                content="full answer",
                response_metadata={"finish_reason": "stop"},
            )
            primary_model = SimpleNamespace(
                ainvoke=AsyncMock(return_value=capped_response)
            )
            escalated_model = SimpleNamespace(
                ainvoke=AsyncMock(return_value=retry_response)
            )

            with patch.object(
                model_factory, "build_chat_model", return_value=escalated_model
            ) as build_mock:
                result = await model_factory.invoke_with_escalation(
                    "executor",
                    [SimpleNamespace(content="please write a very long essay")],
                    model=primary_model,
                    base_dir=tmp_path,
                    session_id="sess-1",
                    run_id="run-1",
                )

            assert result is retry_response
            assert primary_model.ainvoke.await_count == 1
            assert escalated_model.ainvoke.await_count == 1
            # The escalation rebuild must use the higher cap.
            _, kwargs = build_mock.call_args
            assert kwargs.get("max_tokens_override") == 65536

            events = query_audit_events(tmp_path, event_type="llm_escalation")

        assert len(events) == 1
        event = events[0]
        assert event.outcome == "retried"
        assert event.session_id == "sess-1"
        assert event.run_id == "run-1"
        assert event.details["default_max_tokens"] == 8000
        assert event.details["escalated_max_tokens"] == 65536
        assert event.details["role"] == "executor"
        assert event.details["stop_reason"] == "length"

    @pytest.mark.asyncio
    async def test_escalates_on_anthropic_style_stop_reason(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            capped_response = SimpleNamespace(
                content="partial",
                response_metadata={"stop_reason": "max_tokens"},
            )
            retry_response = SimpleNamespace(
                content="full",
                response_metadata={"stop_reason": "end_turn"},
            )
            primary_model = SimpleNamespace(
                ainvoke=AsyncMock(return_value=capped_response)
            )
            escalated_model = SimpleNamespace(
                ainvoke=AsyncMock(return_value=retry_response)
            )

            with patch.object(
                model_factory, "build_chat_model", return_value=escalated_model
            ):
                result = await model_factory.invoke_with_escalation(
                    "planner",
                    [SimpleNamespace(content="plan please")],
                    model=primary_model,
                    base_dir=tmp_path,
                )

        assert result is retry_response
        assert escalated_model.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_still_capped_retry_records_outcome_and_returns_retry(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory
            from audit.store import query_audit_events

            capped_first = SimpleNamespace(
                content="truncated",
                response_metadata={"finish_reason": "length"},
            )
            capped_retry = SimpleNamespace(
                content="still truncated",
                response_metadata={"finish_reason": "length"},
            )
            primary_model = SimpleNamespace(ainvoke=AsyncMock(return_value=capped_first))
            escalated_model = SimpleNamespace(
                ainvoke=AsyncMock(return_value=capped_retry)
            )

            with patch.object(
                model_factory, "build_chat_model", return_value=escalated_model
            ):
                result = await model_factory.invoke_with_escalation(
                    "verifier",
                    [SimpleNamespace(content="verify")],
                    model=primary_model,
                    base_dir=tmp_path,
                )

            events = query_audit_events(tmp_path, event_type="llm_escalation")

        assert result is capped_retry
        assert len(events) == 1
        assert events[0].outcome == "still_capped"

    @pytest.mark.asyncio
    async def test_retry_exception_falls_back_to_original(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=8000, escalated=65536)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory
            from audit.store import query_audit_events

            capped_first = SimpleNamespace(
                content="truncated",
                response_metadata={"finish_reason": "length"},
            )
            primary_model = SimpleNamespace(ainvoke=AsyncMock(return_value=capped_first))
            escalated_model = SimpleNamespace(
                ainvoke=AsyncMock(side_effect=RuntimeError("rate limited"))
            )

            with patch.object(
                model_factory, "build_chat_model", return_value=escalated_model
            ):
                result = await model_factory.invoke_with_escalation(
                    "executor",
                    [SimpleNamespace(content="do work")],
                    model=primary_model,
                    base_dir=tmp_path,
                )

            events = query_audit_events(tmp_path, event_type="llm_escalation")

        assert result is capped_first
        assert len(events) == 1
        assert events[0].outcome == "retry_failed"
        assert events[0].details["error"] == "rate limited"

    @pytest.mark.asyncio
    async def test_skips_escalation_when_cap_disabled(self, tmp_path):
        cfg_file = _write_cap_config(tmp_path, default=0, escalated=0)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            capped_response = SimpleNamespace(
                content="partial",
                response_metadata={"finish_reason": "length"},
            )
            primary_model = SimpleNamespace(
                ainvoke=AsyncMock(return_value=capped_response)
            )

            with patch.object(model_factory, "build_chat_model") as build_mock:
                result = await model_factory.invoke_with_escalation(
                    "title",
                    [SimpleNamespace(content="x")],
                    model=primary_model,
                    base_dir=tmp_path,
                )

            assert result is capped_response
            build_mock.assert_not_called()
