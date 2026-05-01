"""
Tests for config.py runtime layering and hardening policy helpers.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _reset_runtime_config_cache():
    """Clear the module-level runtime-config cache between tests.

    The cache is keyed by per-layer stat signatures, so tmp_path isolation
    already prevents cross-contamination — but resetting keeps cache-hit
    counting tests self-contained regardless of execution order.
    """
    import config as _config

    _config._CACHED_LOADED_RUNTIME = None
    _config._CACHED_LOADED_RUNTIME_SIGNATURE = None
    yield
    _config._CACHED_LOADED_RUNTIME = None
    _config._CACHED_LOADED_RUNTIME_SIGNATURE = None


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

    def test_malformed_production_hardening_policy_raises_at_startup(self, tmp_path):
        """Typos like ``terminal_enabledd`` fail loudly at load time under
        the pydantic-validated config (issue #124), instead of silently
        collapsing to fail-closed at first getter call."""
        import pydantic

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

            with pytest.raises(pydantic.ValidationError) as exc_info:
                config.snapshot_runtime_config()

        assert "terminal_enabledd" in str(exc_info.value)

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

    def test_invalid_agent_runtime_limit_raises_at_startup(self, tmp_path):
        """A string where an int is expected must fail loudly at load time
        (issue #124) so operators see the problem immediately instead of
        discovering it later through the getter fallback."""
        import pydantic

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

            with pytest.raises(pydantic.ValidationError):
                config.snapshot_runtime_config()

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

    def test_env_layer_overlays_project_when_bioapex_env_is_set(self, tmp_path):
        project_cfg = tmp_path / "config.json"
        env_cfg = tmp_path / "config.staging.json"
        project_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": False,
                    "tool_policy": {"enabled": True},
                }
            ),
            encoding="utf-8",
        )
        env_cfg.write_text(
            json.dumps(
                {
                    "rag_mode": True,
                    "tool_policy": {"enabled": False},
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ, {"BIOAPEX_ENV": "staging"}, clear=False
        ):
            from runtime_config import load_runtime_config

            loaded = load_runtime_config(
                default_config={"rag_mode": False, "tool_policy": {"enabled": True}},
                project_config_path=project_cfg,
            )

        assert loaded.data["rag_mode"] is True
        assert loaded.data["tool_policy"]["enabled"] is False

        provenance = loaded.field_provenance
        assert provenance["rag_mode"].source_layer == "env"
        assert provenance["rag_mode"].path == str(env_cfg)
        assert provenance["tool_policy.enabled"].source_layer == "env"

        layer_names = [layer.name for layer in loaded.layers]
        assert layer_names == ["defaults", "user", "project", "env", "local"]

    def test_env_layer_missing_file_is_noop(self, tmp_path):
        project_cfg = tmp_path / "config.json"
        project_cfg.write_text(
            json.dumps({"rag_mode": True}), encoding="utf-8"
        )

        # config.prod.json does not exist on disk.
        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ, {"BIOAPEX_ENV": "prod"}, clear=False
        ):
            from runtime_config import load_runtime_config

            loaded = load_runtime_config(
                default_config={"rag_mode": False},
                project_config_path=project_cfg,
            )

        # Project wins; env layer is present but un-applied.
        assert loaded.data["rag_mode"] is True
        assert loaded.field_provenance["rag_mode"].source_layer == "project"

        env_layer = next(layer for layer in loaded.layers if layer.name == "env")
        assert env_layer.exists is False
        assert env_layer.applied is False
        assert env_layer.path == str(tmp_path / "config.prod.json")

    def test_env_layer_skipped_when_bioapex_env_unset(self, tmp_path):
        project_cfg = tmp_path / "config.json"
        project_cfg.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")

        # Explicitly clear BIOAPEX_ENV (and treat blank the same as unset).
        env_patch = {"BIOAPEX_ENV": ""}
        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ, env_patch, clear=False
        ):
            from runtime_config import load_runtime_config

            loaded = load_runtime_config(
                default_config={"rag_mode": False},
                project_config_path=project_cfg,
            )

        layer_names = [layer.name for layer in loaded.layers]
        assert "env" not in layer_names
        assert layer_names == ["defaults", "user", "project", "local"]

    def test_env_layer_is_overridden_by_local_and_env_vars(self, tmp_path):
        project_cfg = tmp_path / "config.json"
        env_cfg = tmp_path / "config.staging.json"
        local_cfg = tmp_path / "config.local.json"

        project_cfg.write_text(
            json.dumps({"prompt_context": {"memory_stale_days": 10}}),
            encoding="utf-8",
        )
        env_cfg.write_text(
            json.dumps({"prompt_context": {"memory_stale_days": 20}}),
            encoding="utf-8",
        )
        local_cfg.write_text(
            json.dumps({"prompt_context": {"memory_stale_days": 30}}),
            encoding="utf-8",
        )

        # local beats env (file layer precedence).
        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ,
            {
                "BIOAPEX_ENV": "staging",
                "BIOAPEX_LOCAL_CONFIG": str(local_cfg),
            },
            clear=False,
        ):
            import config

            assert config.get_memory_stale_days() == 30

        # Process env var beats every file layer, including env-profile.
        with patch("config._CONFIG_FILE", project_cfg), patch.dict(
            os.environ,
            {
                "BIOAPEX_ENV": "staging",
                "BIOAPEX_LOCAL_CONFIG": str(local_cfg),
                "BIOAPEX_PROMPT_MEMORY_STALE_DAYS": "99",
            },
            clear=False,
        ):
            import config

            assert config.get_memory_stale_days() == 99


class TestRuntimeConfigCache:
    def test_repeated_accessor_calls_reuse_parsed_config(self, tmp_path):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            real_load = config.load_runtime_config
            call_count = 0

            def counting_load(**kwargs):
                nonlocal call_count
                call_count += 1
                return real_load(**kwargs)

            with patch("config.load_runtime_config", side_effect=counting_load):
                # Mix of direct and accessor calls — all should share one parse.
                assert config._load_loaded_runtime() is config._load_loaded_runtime()
                assert config.get_rag_mode() is True
                config.get_prompt_budget()
                config.get_tool_policy_settings()

            assert call_count == 1

    def test_file_edit_invalidates_cache_when_reload_allowed(
        self, tmp_path, monkeypatch
    ):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        monkeypatch.setenv("BIOAPEX_ALLOW_CONFIG_RELOAD", "1")

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            assert config.get_rag_mode() is False

            cfg_file.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
            # Bump the mtime explicitly so the test does not depend on the
            # filesystem's clock resolution between the two writes.
            st = cfg_file.stat()
            os.utime(cfg_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

            assert config.get_rag_mode() is True

    def test_env_profile_change_invalidates_cache(self, tmp_path, monkeypatch):
        project_cfg = tmp_path / "config.json"
        staging_cfg = tmp_path / "config.staging.json"
        prod_cfg = tmp_path / "config.prod.json"
        project_cfg.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        staging_cfg.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
        prod_cfg.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        monkeypatch.setenv("BIOAPEX_ALLOW_CONFIG_RELOAD", "1")

        with patch("config._CONFIG_FILE", project_cfg):
            import config

            monkeypatch.delenv("BIOAPEX_ENV", raising=False)
            assert config.get_rag_mode() is False

            monkeypatch.setenv("BIOAPEX_ENV", "staging")
            assert config.get_rag_mode() is True

            monkeypatch.setenv("BIOAPEX_ENV", "prod")
            assert config.get_rag_mode() is False

    def test_env_profile_file_edit_invalidates_cache(self, tmp_path, monkeypatch):
        project_cfg = tmp_path / "config.json"
        staging_cfg = tmp_path / "config.staging.json"
        project_cfg.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        staging_cfg.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        monkeypatch.setenv("BIOAPEX_ALLOW_CONFIG_RELOAD", "1")
        monkeypatch.setenv("BIOAPEX_ENV", "staging")

        with patch("config._CONFIG_FILE", project_cfg):
            import config

            assert config.get_rag_mode() is False

            staging_cfg.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
            st = staging_cfg.stat()
            os.utime(staging_cfg, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

            assert config.get_rag_mode() is True

    def test_snapshot_reflects_current_file_state(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": False}), encoding="utf-8")
        monkeypatch.setenv("BIOAPEX_ALLOW_CONFIG_RELOAD", "1")

        with patch("config._CONFIG_FILE", cfg_file):
            import config

            first = config.snapshot_runtime_config()
            assert first.config.data["rag_mode"] is False

            cfg_file.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
            st = cfg_file.stat()
            os.utime(cfg_file, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))

            second = config.snapshot_runtime_config()
            assert second.config.data["rag_mode"] is True
            # First snapshot still holds its point-in-time view.
            assert first.config.data["rag_mode"] is False


class TestToolWallclockOverride:
    """``get_tool_wallclock_override_s`` must distinguish an explicit
    operator disable (``0``/negative) from an unparseable typo (``"30s"``,
    ``true``, ...). A typo must return ``None`` so the manifest sandbox
    default and ``tool_wallclock.default_seconds`` still apply."""

    def _write(self, tmp_path, overrides):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            json.dumps({"tool_wallclock": {"overrides": overrides}}),
            encoding="utf-8",
        )
        return cfg_file

    def test_numeric_override_returned(self, tmp_path):
        cfg_file = self._write(tmp_path, {"foo": 12.5})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_tool_wallclock_override_s("foo") == 12.5

    def test_numeric_string_override_parsed(self, tmp_path):
        cfg_file = self._write(tmp_path, {"foo": "5"})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_tool_wallclock_override_s("foo") == 5.0

    def test_zero_override_disables_cap(self, tmp_path):
        cfg_file = self._write(tmp_path, {"foo": 0})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            # 0.0 == explicit disable, distinct from None (no override).
            assert config.get_tool_wallclock_override_s("foo") == 0.0

    def test_negative_override_disables_cap(self, tmp_path):
        cfg_file = self._write(tmp_path, {"foo": -1})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_tool_wallclock_override_s("foo") == 0.0

    def test_non_numeric_string_falls_back_to_none(self, tmp_path):
        # A typo like "30s" must NOT silently disable the cap.
        cfg_file = self._write(tmp_path, {"foo": "30s"})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_tool_wallclock_override_s("foo") is None

    def test_bool_override_falls_back_to_none(self, tmp_path):
        cfg_file = self._write(tmp_path, {"foo": True})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_tool_wallclock_override_s("foo") is None

    def test_missing_tool_returns_none(self, tmp_path):
        cfg_file = self._write(tmp_path, {"other": 5})
        with patch("config._CONFIG_FILE", cfg_file):
            import config
            assert config.get_tool_wallclock_override_s("foo") is None
