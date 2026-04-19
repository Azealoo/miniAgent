"""Tests for the primary -> fallback model selection wrapper.

Covers:
- ``RoleModelConfig.fallback_model`` is resolved from layered config
  (per-role > llm-wide > _ROLE_DEFAULTS).
- ``build_fallback_chat_model`` returns ``None`` when no fallback is
  configured (no-op contract — caller must re-raise).
- ``is_overload_or_timeout`` recognises 529, anthropic-style overload
  bodies, and timeout-named exception classes.
- ``atry_with_model_fallback`` invokes the fallback once after a 529
  from the primary and writes a ``model_fallback`` audit line.
- An overload-style exception with no fallback configured re-raises
  the original exception (no-op fallback).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class _Overload529(Exception):
    """Stand-in for anthropic.APIStatusError(status_code=529)."""

    def __init__(self, message: str = "overloaded_error: server overloaded"):
        super().__init__(message)
        self.status_code = 529
        self.body = {"error": {"type": "overloaded_error", "message": message}}


class _RecordingChatModel:
    """Minimal chat-model stand-in that records init kwargs."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = dict(kwargs)
        self.model = kwargs.get("model")


def _write_config_with_fallback(tmp_path: Path) -> Path:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "execution_backends": {
                    "llm": {
                        "roles": {
                            "executor": {
                                "provider": "openai",
                                "model": "primary-executor",
                                "fallback_model": "fallback-executor",
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return cfg_file


class TestFallbackConfigResolution:
    def test_role_fallback_model_resolves_from_role_config(self, tmp_path):
        cfg_file = _write_config_with_fallback(tmp_path)
        with patch("config._CONFIG_FILE", cfg_file):
            from runtime.model_factory import get_role_model_config

            role_cfg = get_role_model_config("executor")
            assert role_cfg.model == "primary-executor"
            assert role_cfg.fallback_model == "fallback-executor"

    def test_unset_fallback_model_is_none(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            from runtime.model_factory import get_role_model_config

            role_cfg = get_role_model_config("executor")
            assert role_cfg.fallback_model is None

    def test_build_fallback_chat_model_returns_none_when_unset(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_fallback_chat_model("executor")
            assert client is None

    def test_build_fallback_chat_model_uses_override_when_set(self, tmp_path):
        cfg_file = _write_config_with_fallback(tmp_path)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_fallback_chat_model("executor")
            assert isinstance(client, _RecordingChatModel)
            assert client.kwargs["model"] == "fallback-executor"


class TestOverloadDetection:
    def test_status_code_529_classified_as_overload(self):
        from runtime.model_fallback import is_overload_or_timeout

        assert is_overload_or_timeout(_Overload529()) is True

    def test_anthropic_style_overloaded_body_classified(self):
        from runtime.model_fallback import is_overload_or_timeout

        class _Body(Exception):
            def __init__(self):
                super().__init__("upstream returned overloaded_error")
                self.body = {"error": {"type": "overloaded_error"}}

        assert is_overload_or_timeout(_Body()) is True

    def test_timeout_named_exception_classified(self):
        from runtime.model_fallback import is_overload_or_timeout

        class APITimeoutError(Exception):
            pass

        assert is_overload_or_timeout(APITimeoutError("read timed out")) is True

    def test_unrelated_exception_not_classified(self):
        from runtime.model_fallback import is_overload_or_timeout

        assert is_overload_or_timeout(ValueError("bad input")) is False


class TestAtryWithModelFallback:
    def test_primary_529_routes_through_fallback_and_audits(self, tmp_path):
        cfg_file = _write_config_with_fallback(tmp_path)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory
            import runtime.model_fallback as model_fallback

            primary = MagicMock(name="primary")
            fallback = MagicMock(name="fallback")

            async def _primary_call(_msg):
                raise _Overload529()

            async def _fallback_call(_msg):
                return "ok"

            primary.ainvoke = _primary_call
            fallback.ainvoke = _fallback_call

            with patch.object(model_factory, "build_chat_model", return_value=primary), \
                 patch.object(model_fallback, "build_chat_model", return_value=primary), \
                 patch.object(
                     model_fallback,
                     "build_fallback_chat_model",
                     return_value=fallback,
                 ):
                result = asyncio.run(
                    model_fallback.atry_with_model_fallback(
                        "executor",
                        lambda model: model.ainvoke("hi"),
                        base_dir=tmp_path,
                        session_id="sess-fallback-test",
                    )
                )

            assert result == "ok"

            from audit.store import query_audit_events

            events = query_audit_events(
                tmp_path,
                event_type="model_fallback",
                session_id="sess-fallback-test",
            )
            assert len(events) == 1
            event = events[0]
            assert event.outcome == "fallback"
            assert event.details["role"] == "executor"
            assert event.details["primary_model"] == "primary-executor"
            assert event.details["fallback_model"] == "fallback-executor"
            assert event.details["exception_class"] == "_Overload529"

    def test_no_fallback_configured_reraises_original(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory
            import runtime.model_fallback as model_fallback

            primary = MagicMock(name="primary")

            async def _primary_call(_msg):
                raise _Overload529("primary down")

            primary.ainvoke = _primary_call

            with patch.object(model_factory, "build_chat_model", return_value=primary), \
                 patch.object(model_fallback, "build_chat_model", return_value=primary), \
                 patch.object(
                     model_fallback,
                     "build_fallback_chat_model",
                     return_value=None,
                 ):
                with pytest.raises(_Overload529):
                    asyncio.run(
                        model_fallback.atry_with_model_fallback(
                            "executor",
                            lambda model: model.ainvoke("hi"),
                            base_dir=tmp_path,
                            session_id="sess-no-fallback",
                        )
                    )

    def test_non_overload_exception_propagates_without_fallback(self, tmp_path):
        cfg_file = _write_config_with_fallback(tmp_path)
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory
            import runtime.model_fallback as model_fallback

            primary = MagicMock(name="primary")
            fallback = MagicMock(name="fallback")

            async def _primary_call(_msg):
                raise ValueError("bad request")

            primary.ainvoke = _primary_call

            with patch.object(model_factory, "build_chat_model", return_value=primary), \
                 patch.object(model_fallback, "build_chat_model", return_value=primary), \
                 patch.object(
                     model_fallback,
                     "build_fallback_chat_model",
                     return_value=fallback,
                 ):
                with pytest.raises(ValueError):
                    asyncio.run(
                        model_fallback.atry_with_model_fallback(
                            "executor",
                            lambda model: model.ainvoke("hi"),
                            base_dir=tmp_path,
                        )
                    )
            fallback.ainvoke.assert_not_called()
