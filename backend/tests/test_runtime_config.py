"""Tests for the pydantic-validated runtime config (issue #124).

Covers three shapes:

* A config with every top-level section populated validates cleanly.
* Missing optional sections fall through to the defaults.
* Malformed fields (bad types, unknown posture, invalid rag_mode, negative
  ints, typos in sub-blocks) raise ``pydantic.ValidationError`` at startup
  instead of slipping through and crashing later at tool dispatch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pydantic
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime_config_types import RuntimeConfigModel, validate_runtime_config


class TestValidateDirectly:
    """Exercise ``RuntimeConfigModel`` against fully-merged dicts."""

    def test_empty_dict_validates_with_defaults(self):
        model = RuntimeConfigModel.model_validate({})
        assert model.rag_mode == "off"
        assert model.max_tokens_per_turn == 200_000
        assert model.prompt_context.memory_stale_days == 30
        assert model.agent_runtime.executor_recursion_limit == 1000
        assert model.production_hardening.posture == "dev"
        assert model.api_rate_limits == {}

    def test_full_valid_config_all_sections(self):
        payload = {
            "rag_mode": "keyword",
            "deterministic_seed": 42,
            "max_tokens_per_turn": 100_000,
            "production_hardening": {
                "posture": "trusted-lab",
                "tools": {"terminal_enabled": True},
                "api": {"files_write_enabled": False},
                "host_binding": "0.0.0.0",
                "approval_threshold": "destructive_only",
                "file_write_whitelist": ["workspace/"],
            },
            "prompt_context": {
                "include_git_context": True,
                "memory_stale_days": 14,
                "llm_probe_min_files": 5,
                "llm_probe_max_chars": 4_000,
            },
            "prompt_budget": {
                "component_max_chars": 10_000,
                "project_instruction_file_max_chars": 1_000,
                "project_instruction_total_max_chars": 4_000,
                "git_context_max_chars": 1_000,
                "retrieved_memory_block_max_chars": 800,
                "retrieved_memory_item_max_chars": 140,
                "scoped_memory_block_max_chars": 2_000,
                "memory_index_max_chars": 1_024,
                "total_max_chars": 50_000,
            },
            "agent_runtime": {
                "executor_recursion_limit": 500,
                "helper_agent_recursion_limit": 500,
            },
            "verification": {"retry_on_repair_required": False},
            "llm_output_token_cap": {"default": 4_000, "escalated": 16_000},
            "tool_policy": {
                "enabled": True,
                "allow_without_context": False,
                "warn_on_missing_artifact_refs": False,
            },
            "permissions": {
                "enabled": True,
                "rules": [
                    {"description": "block rm -rf", "effect": "deny"},
                    {"description": "allow reads in workspace", "effect": "allow"},
                ],
                "cache_max_entries_per_session": 128,
            },
            "access_defaults": {"allow_loopback_without_auth": False},
            "execution_backends": {
                "llm": {
                    "provider": "deepseek",
                    "roles": {
                        "executor": {
                            "provider": "deepseek",
                            "model": "deepseek-chat",
                            "temperature": 0.3,
                            "streaming": True,
                            "fallback_model": None,
                        },
                        "planner": {
                            "provider": "openai",
                            "model": "gpt-5.4-mini",
                            "temperature": 0.2,
                            "streaming": True,
                            "fallback_model": None,
                        },
                        "verifier": {
                            "provider": "openai",
                            "model": "gpt-5.4-mini",
                            "temperature": 0.2,
                            "streaming": True,
                            "fallback_model": None,
                        },
                        "title": {
                            "provider": "openai",
                            "model": "gpt-5-mini",
                            "temperature": 0.2,
                            "streaming": False,
                            "fallback_model": None,
                        },
                    },
                }
            },
            "skills": {
                "extra_dirs": ["./custom-skills"],
                "entries": {"foo": {"enabled": False}},
            },
            "read_file_extra_roots": ["/tmp/scratch"],
            "memory_indexer": {"max_sections_per_file": 32},
            "retention": {
                "dry_run": True,
                "enabled_on_startup": False,
                "paths": {"sessions/archive": {"keep_days": 90}},
            },
            "api_rate_limits": {
                "files_read": {"rate": 30, "period_seconds": 60, "enabled": True},
                "files_write": {"rate": 10, "period_seconds": 60, "enabled": True},
            },
        }

        validate_runtime_config(payload)  # must not raise

    def test_rag_mode_bool_true_normalizes_to_keyword(self):
        model = RuntimeConfigModel.model_validate({"rag_mode": True})
        assert model.rag_mode == "keyword"

    def test_rag_mode_bool_false_normalizes_to_off(self):
        model = RuntimeConfigModel.model_validate({"rag_mode": False})
        assert model.rag_mode == "off"

    def test_rag_mode_unknown_string_falls_back_to_off(self):
        # Mirrors the historical lenient behavior of ``_normalize_rag_mode``
        # for string input — non-bool/non-string inputs still raise.
        model = RuntimeConfigModel.model_validate({"rag_mode": "banana"})
        assert model.rag_mode == "off"

    def test_rag_mode_non_bool_non_str_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate({"rag_mode": 42})

    def test_unknown_hardening_posture_raises(self):
        with pytest.raises(pydantic.ValidationError) as exc_info:
            RuntimeConfigModel.model_validate(
                {"production_hardening": {"posture": "mega-strict"}}
            )
        assert "posture" in str(exc_info.value)

    def test_negative_memory_stale_days_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {"prompt_context": {"memory_stale_days": -1}}
            )

    def test_negative_prompt_budget_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {"prompt_budget": {"component_max_chars": -5}}
            )

    def test_negative_agent_runtime_limit_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {"agent_runtime": {"executor_recursion_limit": -10}}
            )

    def test_bad_type_for_tool_policy_enabled_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {"tool_policy": {"enabled": "maybe"}}
            )

    def test_unknown_top_level_key_raises(self):
        with pytest.raises(pydantic.ValidationError) as exc_info:
            RuntimeConfigModel.model_validate({"this_is_not_a_section": 1})
        assert "this_is_not_a_section" in str(exc_info.value)

    def test_unknown_permission_effect_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {
                    "permissions": {
                        "enabled": True,
                        "rules": [{"description": "bad", "effect": "maybe"}],
                    }
                }
            )

    def test_unknown_model_role_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {
                    "execution_backends": {
                        "llm": {"roles": {"ghost_role": {"model": "x"}}}
                    }
                }
            )

    def test_memory_indexer_bad_type_raises(self):
        with pytest.raises(pydantic.ValidationError):
            RuntimeConfigModel.model_validate(
                {"memory_indexer": {"max_sections_per_file": "sixty-four"}}
            )


class TestLoadIntegration:
    """Validation must fire through ``_load_loaded_runtime`` /
    ``snapshot_runtime_config`` so the error surfaces at startup, not at
    first tool dispatch."""

    def test_snapshot_raises_on_bad_posture(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"production_hardening": {"posture": "nope"}}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            with pytest.raises(pydantic.ValidationError):
                config.snapshot_runtime_config()

    def test_snapshot_raises_on_negative_max_tokens(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"max_tokens_per_turn": -1}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            with pytest.raises(pydantic.ValidationError):
                config.snapshot_runtime_config()

    def test_snapshot_valid_config_succeeds(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "rag_mode": "llm_probe",
                    "memory_indexer": {"max_sections_per_file": 16},
                    "retention": {
                        "dry_run": False,
                        "enabled_on_startup": True,
                        "paths": {},
                    },
                    "api_rate_limits": {
                        "files_read": {
                            "rate": 5,
                            "period_seconds": 30,
                            "enabled": False,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            snap = config.snapshot_runtime_config()

        assert snap.config.data["rag_mode"] == "llm_probe"
        assert snap.config.data["memory_indexer"]["max_sections_per_file"] == 16

    def test_snapshot_missing_optional_sections_uses_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        # Empty config — all optional sections absent.
        cfg_file.write_text("{}", encoding="utf-8")

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            snap = config.snapshot_runtime_config()

        assert snap.config.data["rag_mode"] is False  # legacy bool default
        assert snap.config.data["max_tokens_per_turn"] == 200_000
        assert (
            snap.config.data["prompt_context"]["memory_stale_days"] == 30
        )

    def test_snapshot_rejects_unknown_top_level_key(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"bogus_section": {"anything": 1}}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            with pytest.raises(pydantic.ValidationError) as exc_info:
                config.snapshot_runtime_config()

        assert "bogus_section" in str(exc_info.value)
