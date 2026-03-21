"""
Tests for config.py — RAG mode persistence via config.json.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfig:
    """Each test patches the config file path to an isolated tmp file."""

    def test_default_rag_mode_is_false(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is False

    def test_set_rag_mode_true(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
            assert config.get_rag_mode() is True

    def test_set_rag_mode_false(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
            config.set_rag_mode(False)
            assert config.get_rag_mode() is False

    def test_config_file_written_on_set(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
            assert cfg_file.exists()
            data = json.loads(cfg_file.read_text())
            assert data["rag_mode"] is True

    def test_persists_across_loads(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            config.set_rag_mode(True)
        # Re-read fresh
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_rag_mode() is True

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
                            "connectors_runtime_actions_enabled": False,
                            "allow_loopback_without_auth": False,
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
        assert policy.api.connectors_runtime_actions_enabled is False
        assert policy.api.allow_loopback_without_auth is False
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
        assert policy.api.connectors_runtime_actions_enabled is False
        assert policy.api.allow_loopback_without_auth is False
        assert policy.api.cors_allowed_origins == []
