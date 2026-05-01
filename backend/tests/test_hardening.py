"""Tests for the posture-driven ProductionHardeningPolicy.

Each posture (``dev | trusted-lab | hosted-strict``) expands into a known
set of derived flags — these tests pin that derivation so an accidental
change to a posture default fails loudly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from hardening import (  # noqa: E402
    DEFAULT_POSTURE,
    VALID_POSTURES,
    ProductionHardeningPolicy,
    posture_defaults,
)


def _write_posture_config(tmp_path: Path, body: dict) -> Path:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(body), encoding="utf-8")
    return cfg_file


class TestPostureDerivation:
    """Exact derived-flag assertions for each posture."""

    def test_dev_posture_expands_to_permissive_defaults(self):
        policy = ProductionHardeningPolicy.from_posture("dev")

        assert policy.posture == "dev"
        assert policy.tools.terminal_enabled is True
        assert policy.tools.python_repl_enabled is True
        assert policy.tools.slurm_enabled is True
        assert policy.tools.slurm_legacy_commands_enabled is True
        assert policy.tools.write_file_enabled is True

        assert policy.api.files_write_enabled is True
        assert policy.api.allow_loopback_without_auth is True
        assert policy.api.trust_forwarded_loopback_headers is False
        assert policy.api.inspection_bearer_token_env_var is None
        assert policy.api.execution_bearer_token_env_var is None
        assert policy.api.admin_bearer_token_env_var is None
        assert policy.api.cors_allowed_origins == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]

        assert policy.host_binding == "127.0.0.1"
        assert policy.approval_threshold == "none"
        assert policy.file_write_whitelist == [
            "workspace/",
            "memory/",
            "skills/",
            "knowledge/",
        ]

    def test_trusted_lab_posture_restricts_repl_and_loopback_bypass(self):
        policy = ProductionHardeningPolicy.from_posture("trusted-lab")

        assert policy.posture == "trusted-lab"
        # REPL and legacy slurm are the highest-risk surfaces in a shared lab.
        assert policy.tools.terminal_enabled is True
        assert policy.tools.python_repl_enabled is False
        assert policy.tools.slurm_enabled is True
        assert policy.tools.slurm_legacy_commands_enabled is False
        assert policy.tools.write_file_enabled is True

        # Shared deployments require bearer auth — no silent loopback bypass.
        assert policy.api.files_write_enabled is True
        assert policy.api.allow_loopback_without_auth is False
        assert policy.api.trust_forwarded_loopback_headers is False
        assert policy.api.inspection_bearer_token_env_var is None
        assert policy.api.execution_bearer_token_env_var is None
        assert policy.api.admin_bearer_token_env_var is None
        assert policy.api.cors_allowed_origins == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]

        assert policy.host_binding == "0.0.0.0"
        assert policy.approval_threshold == "destructive_only"
        assert policy.file_write_whitelist == [
            "workspace/",
            "memory/",
            "skills/",
            "knowledge/",
        ]

    def test_hosted_strict_posture_matches_fail_closed_baseline(self):
        policy = ProductionHardeningPolicy.from_posture("hosted-strict")

        assert policy.posture == "hosted-strict"
        assert policy.tools.terminal_enabled is False
        assert policy.tools.python_repl_enabled is False
        assert policy.tools.slurm_enabled is False
        assert policy.tools.slurm_legacy_commands_enabled is False
        assert policy.tools.write_file_enabled is False

        assert policy.api.files_write_enabled is False
        assert policy.api.allow_loopback_without_auth is False
        assert policy.api.trust_forwarded_loopback_headers is False
        assert policy.api.cors_allowed_origins == []

        assert policy.host_binding == "127.0.0.1"
        assert policy.approval_threshold == "all_risky"
        assert policy.file_write_whitelist == []

    def test_fail_closed_is_hosted_strict(self):
        assert ProductionHardeningPolicy.fail_closed().posture == "hosted-strict"

    def test_default_posture_matches_dev_dict(self):
        # posture_defaults() is the source the effective endpoint advertises.
        dev_dict = posture_defaults("dev")
        assert dev_dict["posture"] == "dev"
        assert dev_dict["host_binding"] == "127.0.0.1"
        assert dev_dict["approval_threshold"] == "none"
        assert DEFAULT_POSTURE == "dev"

    def test_valid_postures_are_exactly_three(self):
        assert set(VALID_POSTURES) == {"dev", "trusted-lab", "hosted-strict"}

    def test_unknown_posture_raises_value_error(self):
        with pytest.raises(ValueError):
            ProductionHardeningPolicy.from_posture("nope")  # type: ignore[arg-type]


class TestPostureOverrideLayering:
    """Escape-hatch overrides still layer on top of posture defaults."""

    def test_override_flips_single_tool_without_affecting_siblings(self):
        policy = ProductionHardeningPolicy.from_posture(
            "dev",
            overrides={"tools": {"terminal_enabled": False}},
        )
        assert policy.posture == "dev"
        assert policy.tools.terminal_enabled is False
        # Sibling tool flags retain the posture default, not a pydantic default.
        assert policy.tools.python_repl_enabled is True
        assert policy.tools.slurm_legacy_commands_enabled is True
        # Non-tool posture fields are unaffected by tool overrides.
        assert policy.api.allow_loopback_without_auth is True
        assert policy.host_binding == "127.0.0.1"

    def test_override_cannot_change_posture_label(self):
        policy = ProductionHardeningPolicy.from_posture(
            "hosted-strict",
            overrides={"posture": "dev"},
        )
        # Overrides layer derived values, but the active posture is whatever
        # the caller (or config) explicitly selected on the outer call.
        assert policy.posture == "hosted-strict"

    def test_override_can_widen_hosted_strict_cors(self):
        policy = ProductionHardeningPolicy.from_posture(
            "hosted-strict",
            overrides={"api": {"cors_allowed_origins": ["https://example.org"]}},
        )
        assert policy.posture == "hosted-strict"
        assert policy.api.cors_allowed_origins == ["https://example.org"]
        # Other hosted-strict API flags remain closed.
        assert policy.api.files_write_enabled is False
        assert policy.api.allow_loopback_without_auth is False


class TestConfigIntegration:
    """Posture is read out of backend/config.json via get_production_hardening_policy."""

    def test_missing_posture_defaults_to_dev(self, tmp_path):
        cfg_file = _write_posture_config(tmp_path, {})
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()
        assert policy.posture == "dev"
        assert policy.tools.terminal_enabled is True
        assert policy.api.allow_loopback_without_auth is True

    def test_trusted_lab_posture_from_config(self, tmp_path):
        cfg_file = _write_posture_config(
            tmp_path,
            {"production_hardening": {"posture": "trusted-lab"}},
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()
        assert policy.posture == "trusted-lab"
        assert policy.tools.python_repl_enabled is False
        assert policy.tools.slurm_legacy_commands_enabled is False
        assert policy.api.allow_loopback_without_auth is False
        assert policy.host_binding == "0.0.0.0"

    def test_hosted_strict_posture_from_config(self, tmp_path):
        cfg_file = _write_posture_config(
            tmp_path,
            {"production_hardening": {"posture": "hosted-strict"}},
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()
        assert policy.posture == "hosted-strict"
        assert policy.tools.write_file_enabled is False
        assert policy.api.cors_allowed_origins == []
        assert policy.file_write_whitelist == []

    def test_unknown_posture_in_config_raises_at_startup(self, tmp_path):
        """An unknown posture in config.json now fails validation at load
        time (issue #124) so operators notice the typo immediately, instead
        of silently falling back to hosted-strict at first getter call."""
        import pydantic

        cfg_file = _write_posture_config(
            tmp_path,
            {"production_hardening": {"posture": "paranoid"}},
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            with pytest.raises(pydantic.ValidationError) as exc_info:
                config.get_production_hardening_policy()

        assert "posture" in str(exc_info.value)

    def test_explicit_override_layers_on_top_of_posture(self, tmp_path):
        cfg_file = _write_posture_config(
            tmp_path,
            {
                "production_hardening": {
                    "posture": "trusted-lab",
                    "tools": {"python_repl_enabled": True},
                    "api": {
                        "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                    },
                }
            },
        )
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()
        assert policy.posture == "trusted-lab"
        # Override wins against the posture default.
        assert policy.tools.python_repl_enabled is True
        # Posture defaults still apply where not overridden.
        assert policy.tools.slurm_legacy_commands_enabled is False
        assert policy.api.allow_loopback_without_auth is False
        assert policy.api.execution_bearer_token_env_var == "BIOAPEX_EXECUTION_TOKEN"
