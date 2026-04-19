"""
Tests for config.py runtime layering and hardening policy helpers.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfig:
    """Each test patches the config file path to an isolated tmp file."""

    def test_default_rag_mode_is_false(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is False
            assert config.get_rag_mode_name() == "off"

    def test_rag_mode_string_keyword(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": "keyword"}), encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode_name() == "keyword"
            assert config.get_rag_mode() is True

    def test_rag_mode_string_llm_probe(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": "llm_probe"}), encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode_name() == "llm_probe"
            assert config.get_rag_mode() is True

    def test_rag_mode_bool_true_maps_to_keyword(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode_name() == "keyword"

    def test_rag_mode_unknown_string_falls_back_to_off(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": "banana"}), encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode_name() == "off"
            assert config.get_rag_mode() is False

    def test_llm_probe_min_files_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_llm_probe_min_files() == 10

    def test_llm_probe_min_files_override(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"prompt_context": {"llm_probe_min_files": 3}}),
            encoding="utf-8",
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_llm_probe_min_files() == 3

    def test_project_config_can_enable_rag_mode(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is True

    def test_project_config_can_disable_rag_mode(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is False

    def test_corrupt_config_falls_back_to_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text("not valid json!!!}", encoding="utf-8")
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is False

    def test_production_hardening_policy_defaults_to_enabled(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()

        assert policy.tools.terminal_enabled is True
        assert policy.tools.python_repl_enabled is True
        assert policy.tools.slurm_enabled is True
        assert policy.api.files_write_enabled is True
        assert policy.api.allow_loopback_without_auth is True
        assert policy.api.trust_forwarded_loopback_headers is False
        assert policy.api.inspection_bearer_token_env_var is None
        assert policy.api.cors_allowed_origins == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]

    def test_production_hardening_policy_reads_configured_overrides(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "tools": {
                            "terminal_enabled": False,
                            "python_repl_enabled": False,
                            "slurm_legacy_commands_enabled": False,
                        },
                        "api": {
                            "files_write_enabled": False,
                            "allow_loopback_without_auth": False,
                            "trust_forwarded_loopback_headers": True,
                            "inspection_bearer_token_env_var": "BIOAPEX_INSPECTION_TOKEN",
                            "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                            "admin_bearer_token_env_var": "BIOAPEX_ADMIN_TOKEN",
                            "cors_allowed_origins": ["https://bioapex.example.org"],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()

        assert policy.tools.terminal_enabled is False
        assert policy.tools.python_repl_enabled is False
        assert policy.tools.slurm_legacy_commands_enabled is False
        assert policy.api.files_write_enabled is False
        assert policy.api.allow_loopback_without_auth is False
        assert policy.api.trust_forwarded_loopback_headers is True
        assert policy.api.inspection_bearer_token_env_var == "BIOAPEX_INSPECTION_TOKEN"
        assert policy.api.execution_bearer_token_env_var == "BIOAPEX_EXECUTION_TOKEN"
        assert policy.api.admin_bearer_token_env_var == "BIOAPEX_ADMIN_TOKEN"
        assert policy.api.cors_allowed_origins == ["https://bioapex.example.org"]

    def test_malformed_production_hardening_policy_fails_closed(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "tools": {
                            "terminal_enabled": False,
                            "terminal_enabledd": True,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()

        assert policy.tools.terminal_enabled is False
        assert policy.tools.python_repl_enabled is False
        assert policy.tools.slurm_enabled is False
        assert policy.api.files_write_enabled is False
        assert policy.api.allow_loopback_without_auth is False
        assert policy.api.cors_allowed_origins == []

    def test_runtime_config_layers_apply_user_project_local_precedence(self, tmp_path):
        user_cfg = tmp_path / "user-config.json"
        project_cfg = tmp_path / "config.json"
        local_cfg = tmp_path / "config.local.json"
        user_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": False,
                    "prompt_context": {"include_git_context": True},
                    "tool_policy": {"warn_on_missing_artifact_refs": False},
                }
            ),
            encoding="utf-8",
        )
        project_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": True,
                    "tool_policy": {"enabled": False},
                    "production_hardening": {
                        "api": {"allow_loopback_without_auth": False}
                    },
                }
            ),
            encoding="utf-8",
        )
        local_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": False,
                    "tool_policy": {"enabled": True},
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ,
            {
                "BIOAPEX_USER_CONFIG": str(user_cfg),
                "BIOAPEX_LOCAL_CONFIG": str(local_cfg),
            },
            clear=False,
        ):
            import config

            assert config.get_rag_mode() is False
            assert config.get_prompt_context_settings()["include_git_context"] is True
            assert config.get_tool_policy_settings()["enabled"] is True
            assert (
                config.get_tool_policy_settings()["warn_on_missing_artifact_refs"] is False
            )
            assert config.get_production_hardening_policy().api.allow_loopback_without_auth is False

    def test_runtime_config_exposes_new_default_sections(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            agent_runtime = config.get_agent_runtime_settings()
            prompt_context = config.get_prompt_context_settings()
            tool_policy = config.get_tool_policy_settings()
            access_defaults = config.get_access_defaults()
            execution_backends = config.get_execution_backend_settings()

        assert agent_runtime["executor_recursion_limit"] == 1000
        assert agent_runtime["helper_agent_recursion_limit"] == 1000
        assert prompt_context["include_git_context"] is False
        assert tool_policy["enabled"] is True
        assert access_defaults["allow_loopback_without_auth"] is True
        assert execution_backends["llm"]["provider"] == "deepseek"
        assert execution_backends["llm"]["roles"]["executor"]["provider"] == "deepseek"
        assert execution_backends["llm"]["roles"]["planner"]["provider"] == "openai"
        assert execution_backends["llm"]["roles"]["verifier"]["provider"] == "openai"

    def test_project_config_can_override_agent_runtime_limits(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "agent_runtime": {
                        "executor_recursion_limit": 320,
                        "helper_agent_recursion_limit": 180,
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            agent_runtime = config.get_agent_runtime_settings()

        assert agent_runtime["executor_recursion_limit"] == 320
        assert agent_runtime["helper_agent_recursion_limit"] == 180

    def test_invalid_agent_runtime_limit_falls_back_to_default(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps(
                {
                    "agent_runtime": {
                        "executor_recursion_limit": "many",
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            assert config.get_agent_runtime_limit("executor_recursion_limit", 1000) == 1000
            assert config.get_agent_runtime_limit("helper_agent_recursion_limit", 1000) == 1000

    def test_effective_config_endpoint_reports_per_field_provenance(self, tmp_path):
        user_cfg = tmp_path / "user-config.json"
        project_cfg = tmp_path / "config.json"
        local_cfg = tmp_path / "config.local.json"

        user_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": True,
                    "prompt_context": {"include_git_context": True},
                    "tool_policy": {"warn_on_missing_artifact_refs": False},
                }
            ),
            encoding="utf-8",
        )
        project_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": False,
                    "tool_policy": {"enabled": False},
                }
            ),
            encoding="utf-8",
        )
        local_cfg.write_text(
            json.dumps(
                {
                    "tool_policy": {"enabled": True},
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ,
            {
                "BIOAPEX_USER_CONFIG": str(user_cfg),
                "BIOAPEX_LOCAL_CONFIG": str(local_cfg),
            },
            clear=False,
        ):
            from api.config import get_effective_config

            response = get_effective_config(request=None)

        assert "field_provenance" in response
        provenance = response["field_provenance"]

        # Local overrides project override → tool_policy.enabled came from local.
        enabled_entry = provenance["tool_policy.enabled"]
        assert enabled_entry["value"] is True
        assert enabled_entry["source_layer"] == "local"
        assert enabled_entry["path"] == str(local_cfg)

        # Project overrides user → rag_mode came from project.
        rag_entry = provenance["rag_mode"]
        assert rag_entry["value"] is False
        assert rag_entry["source_layer"] == "project"
        assert rag_entry["path"] == str(project_cfg)

        # Only user set this flag → source is user.
        git_entry = provenance["prompt_context.include_git_context"]
        assert git_entry["value"] is True
        assert git_entry["source_layer"] == "user"
        assert git_entry["path"] == str(user_cfg)

        # Only user set this flag → source is user.
        warn_entry = provenance["tool_policy.warn_on_missing_artifact_refs"]
        assert warn_entry["value"] is False
        assert warn_entry["source_layer"] == "user"

        # Untouched defaults should still report provenance from defaults.
        memory_stale = provenance["prompt_context.memory_stale_days"]
        assert memory_stale["source_layer"] == "defaults"
        assert memory_stale["path"] is None

        # Backwards-compatible layer summary remains alongside field_provenance.
        layer_names = [layer["name"] for layer in response["config_layers"]]
        assert layer_names == ["defaults", "user", "project", "local"]
