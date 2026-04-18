"""Tests for GET /api/config/effective resolved role→model table.

Each test patches ``config._CONFIG_FILE`` to an isolated tmp config file and
optionally patches ``os.environ`` to exercise a single override source at a
time:

- per-role env var (``BIOAPEX_<ROLE>_*``)
- provider-generic env var (``DEEPSEEK_*`` / ``OPENAI_*``)
- ``execution_backends.llm.roles.<role>`` entries in ``config.json``
- fallback to ``runtime.model_factory._ROLE_DEFAULTS`` when no overrides exist
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


_PER_ROLE_ENV_VARS = (
    "BIOAPEX_EXECUTOR_PROVIDER",
    "BIOAPEX_EXECUTOR_MODEL",
    "BIOAPEX_EXECUTOR_BASE_URL",
    "BIOAPEX_EXECUTOR_API_KEY",
    "BIOAPEX_EXECUTOR_TEMPERATURE",
    "BIOAPEX_EXECUTOR_STREAMING",
    "BIOAPEX_PLANNER_PROVIDER",
    "BIOAPEX_PLANNER_MODEL",
    "BIOAPEX_PLANNER_BASE_URL",
    "BIOAPEX_PLANNER_API_KEY",
    "BIOAPEX_PLANNER_TEMPERATURE",
    "BIOAPEX_PLANNER_STREAMING",
    "BIOAPEX_VERIFIER_PROVIDER",
    "BIOAPEX_VERIFIER_MODEL",
    "BIOAPEX_VERIFIER_BASE_URL",
    "BIOAPEX_VERIFIER_API_KEY",
    "BIOAPEX_VERIFIER_TEMPERATURE",
    "BIOAPEX_VERIFIER_STREAMING",
    "BIOAPEX_TITLE_PROVIDER",
    "BIOAPEX_TITLE_MODEL",
    "BIOAPEX_TITLE_BASE_URL",
    "BIOAPEX_TITLE_API_KEY",
    "BIOAPEX_TITLE_TEMPERATURE",
    "BIOAPEX_TITLE_STREAMING",
)
_PROVIDER_ENV_VARS = (
    "DEEPSEEK_MODEL",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _clean_model_env(monkeypatch):
    """Ensure no ambient role / provider env vars leak into these tests."""
    for name in _PER_ROLE_ENV_VARS + _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


def _call_endpoint(cfg_file: Path) -> dict:
    with patch("config._CONFIG_FILE", cfg_file):
        from api.config import get_effective_config

        return get_effective_config(request=None)


class TestResolvedRoleModels:
    def test_endpoint_reports_all_four_roles(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}", encoding="utf-8")

        response = _call_endpoint(cfg_file)

        assert set(response["resolved_role_models"].keys()) == {
            "executor",
            "planner",
            "verifier",
            "title",
        }

    def test_endpoint_never_surfaces_api_key(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("BIOAPEX_EXECUTOR_API_KEY", "should-not-appear")
        monkeypatch.setenv("OPENAI_API_KEY", "also-should-not-appear")

        response = _call_endpoint(cfg_file)

        for role, entry in response["resolved_role_models"].items():
            assert "api_key" not in entry, role
            assert set(entry.keys()) == {
                "provider",
                "model",
                "base_url",
                "temperature",
                "streaming",
                "seed",
            }
            for value in entry.values():
                if isinstance(value, str):
                    assert "should-not-appear" not in value
                    assert "also-should-not-appear" not in value

    def test_fallback_to_role_defaults_when_no_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("{}", encoding="utf-8")

        response = _call_endpoint(cfg_file)
        resolved = response["resolved_role_models"]

        assert resolved["executor"]["provider"] == "deepseek"
        assert resolved["executor"]["model"] == "deepseek-chat"
        assert resolved["executor"]["base_url"] == "https://api.deepseek.com"
        assert resolved["executor"]["temperature"] == 0.3
        assert resolved["executor"]["streaming"] is True

        assert resolved["title"]["provider"] == "openai"
        assert resolved["title"]["model"] == "gpt-5-mini"
        assert resolved["title"]["base_url"] == "https://api.openai.com/v1"
        assert resolved["title"]["streaming"] is False

    def test_config_json_roles_entry_is_honored(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "execution_backends": {
                        "llm": {
                            "roles": {
                                "executor": {
                                    "provider": "openai",
                                    "model": "gpt-from-config",
                                    "base_url": "https://config.example/v1",
                                    "temperature": 0.9,
                                    "streaming": False,
                                }
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        resolved = _call_endpoint(cfg_file)["resolved_role_models"]

        assert resolved["executor"]["provider"] == "openai"
        assert resolved["executor"]["model"] == "gpt-from-config"
        assert resolved["executor"]["base_url"] == "https://config.example/v1"
        assert resolved["executor"]["temperature"] == 0.9
        assert resolved["executor"]["streaming"] is False

    def test_provider_generic_env_var_beats_config_and_defaults_for_model(
        self, tmp_path, monkeypatch
    ):
        # model_factory's precedence for ``model`` is:
        # per-role env > provider-generic env > config.json role entry >
        # config.json llm.model > defaults. This test pins the middle rung.
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "execution_backends": {
                        "llm": {
                            "roles": {
                                "executor": {
                                    "provider": "deepseek",
                                    "model": "deepseek-from-config",
                                }
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-from-env")

        resolved = _call_endpoint(cfg_file)["resolved_role_models"]

        assert resolved["executor"]["provider"] == "deepseek"
        assert resolved["executor"]["model"] == "deepseek-from-env"

    def test_per_role_env_var_beats_provider_env_and_config(
        self, tmp_path, monkeypatch
    ):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "execution_backends": {
                        "llm": {
                            "roles": {
                                "planner": {
                                    "provider": "openai",
                                    "model": "gpt-from-config",
                                    "base_url": "https://config.example/v1",
                                    "temperature": 0.2,
                                    "streaming": True,
                                }
                            }
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        # Provider-generic env vars would also match, but the role-specific
        # vars must win over everything else.
        monkeypatch.setenv("OPENAI_MODEL", "gpt-from-provider-env")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://provider-env.example/v1")
        monkeypatch.setenv("BIOAPEX_PLANNER_PROVIDER", "openai")
        monkeypatch.setenv("BIOAPEX_PLANNER_MODEL", "gpt-from-role-env")
        monkeypatch.setenv(
            "BIOAPEX_PLANNER_BASE_URL", "https://role-env.example/v1"
        )
        monkeypatch.setenv("BIOAPEX_PLANNER_TEMPERATURE", "0.75")
        monkeypatch.setenv("BIOAPEX_PLANNER_STREAMING", "false")

        resolved = _call_endpoint(cfg_file)["resolved_role_models"]

        assert resolved["planner"]["provider"] == "openai"
        assert resolved["planner"]["model"] == "gpt-from-role-env"
        assert resolved["planner"]["base_url"] == "https://role-env.example/v1"
        assert resolved["planner"]["temperature"] == 0.75
        assert resolved["planner"]["streaming"] is False
