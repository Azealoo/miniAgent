"""
Tests for the deterministic_seed config field.

Covers:
- Default config exposes deterministic_seed as None.
- Project config can set deterministic_seed and get_deterministic_seed() reads it.
- build_chat_model forwards seed=<value> and temperature=0 to both providers
  when deterministic_seed is set, and omits seed when it is not.
- SessionManager stamps `deterministic: {seed: <value>}` on session records.
- Two model instances built with the same seed + same input produce an
  identical first tool call, while instances built without a seed do not
  share that guarantee.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class _RecordingChatModel:
    """Stand-in for ChatOpenAI / ChatDeepSeek that captures init kwargs.

    ``invoke`` returns a first tool call whose payload is deterministic in
    (seed, input) — that is exactly what the real API contract promises when
    temperature=0 and a seed is supplied.
    """

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = dict(kwargs)
        self.seed = kwargs.get("seed")
        self.temperature = kwargs.get("temperature")

    def invoke(self, messages: object) -> dict[str, object]:
        seed_part = self.seed if self.seed is not None else "no-seed"
        tool_input = f"inspect|seed={seed_part}|msg={messages!r}"
        return {
            "tool_calls": [
                {"name": "read_file", "args": {"path": tool_input}},
            ],
        }


class TestDeterministicSeedConfig:
    def test_default_is_none(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            assert config.get_deterministic_seed() is None

    def test_project_config_sets_seed(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": 42}), encoding="utf-8"
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            assert config.get_deterministic_seed() == 42

    def test_invalid_seed_raises_at_startup(self, tmp_path):
        """A non-integer ``deterministic_seed`` now fails validation at load
        time (issue #124) so the typo surfaces at startup, not on the first
        LLM call."""
        import pydantic

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": "not-a-number"}),
            encoding="utf-8",
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            with pytest.raises(pydantic.ValidationError):
                config.get_deterministic_seed()


class TestDeterministicSeedModelFactory:
    def test_build_chat_model_forwards_seed_and_forces_temperature_zero_for_deepseek(
        self, tmp_path
    ):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": 123}), encoding="utf-8"
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_chat_model("executor")

        assert isinstance(client, _RecordingChatModel)
        assert client.kwargs["seed"] == 123
        assert client.kwargs["temperature"] == 0.0

    def test_build_chat_model_forwards_seed_and_forces_temperature_zero_for_openai(
        self, tmp_path
    ):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": 7}), encoding="utf-8"
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_chat_model("planner")

        assert isinstance(client, _RecordingChatModel)
        assert client.kwargs["seed"] == 7
        assert client.kwargs["temperature"] == 0.0

    def test_build_chat_model_omits_seed_when_unset(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                client = model_factory.build_chat_model("executor")

        assert "seed" not in client.kwargs
        # With no deterministic override, temperature should follow the role default.
        assert client.kwargs["temperature"] != 0.0

    def test_get_role_model_config_reports_seed_and_zero_temperature(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": 99}), encoding="utf-8"
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            settings = model_factory.get_role_model_config("executor")

        assert settings.seed == 99
        assert settings.temperature == 0.0


class TestDeterministicSeedSessionRecord:
    def test_session_record_is_stamped_when_seed_is_set(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": 2024}), encoding="utf-8"
        )
        with patch("config._CONFIG_FILE", cfg_file):
            from graph.session_manager import SessionManager

            sm = SessionManager(base_dir=tmp_path)
            session_id = sm.create_session()
            sm.save_message(session_id, "user", "hello")

            raw = json.loads(
                (tmp_path / "sessions" / f"{session_id}.json").read_text(
                    encoding="utf-8"
                )
            )

        assert raw.get("deterministic") == {"seed": 2024}

    def test_session_record_omits_deterministic_when_unset(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            from graph.session_manager import SessionManager

            sm = SessionManager(base_dir=tmp_path)
            session_id = sm.create_session()
            sm.save_message(session_id, "user", "hello")

            raw = json.loads(
                (tmp_path / "sessions" / f"{session_id}.json").read_text(
                    encoding="utf-8"
                )
            )

        assert "deterministic" not in raw


class TestDeterministicSeedFirstToolCall:
    def test_two_runs_with_same_seed_produce_identical_first_tool_call(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"deterministic_seed": 1337}), encoding="utf-8"
        )
        user_input = [{"role": "user", "content": "what files exist?"}]

        with patch("config._CONFIG_FILE", cfg_file):
            import runtime.model_factory as model_factory

            with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
                 patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
                run_a = model_factory.build_chat_model("executor").invoke(user_input)
                run_b = model_factory.build_chat_model("executor").invoke(user_input)

        first_call_a = run_a["tool_calls"][0]
        first_call_b = run_b["tool_calls"][0]
        assert first_call_a == first_call_b

    def test_runs_without_seed_are_not_pinned_to_a_seeded_payload(self, tmp_path):
        cfg_file_seeded = tmp_path / "seeded.json"
        cfg_file_seeded.write_text(
            json.dumps({"deterministic_seed": 1337}), encoding="utf-8"
        )
        cfg_file_unseeded = tmp_path / "unseeded.json"
        user_input = [{"role": "user", "content": "what files exist?"}]

        import runtime.model_factory as model_factory

        with patch.object(model_factory, "ChatDeepSeek", _RecordingChatModel), \
             patch.object(model_factory, "ChatOpenAI", _RecordingChatModel):
            with patch("config._CONFIG_FILE", cfg_file_seeded):
                seeded = model_factory.build_chat_model("executor").invoke(user_input)
            with patch("config._CONFIG_FILE", cfg_file_unseeded):
                unseeded = model_factory.build_chat_model("executor").invoke(user_input)

        assert seeded["tool_calls"][0] != unseeded["tool_calls"][0]
