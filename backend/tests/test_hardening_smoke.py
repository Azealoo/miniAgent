"""Posture smoke tests that exercise the live FastAPI stack.

These tests pin the end-to-end wiring between the production-hardening
posture and the running backend. For each posture they:

1. Build a real ``FastAPI`` ASGI app with the access-control router wired
   in (the same ``access_control`` module the production ``app.py`` uses).
2. Assert the destructive tool flags match the posture on the live policy
   returned by ``config.get_production_hardening_policy()``.
3. Hit the protected ``/access/probe`` route from loopback via
   ``TestClient`` and confirm that ``dev`` accepts the unauthenticated
   request while ``trusted-lab`` and ``hosted-strict`` reject it (because
   their posture flips ``api.allow_loopback_without_auth`` to ``false``).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


def _write_posture_config(tmp_path: Path, posture: str) -> Path:
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"production_hardening": {"posture": posture}}),
        encoding="utf-8",
    )
    return cfg_file


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with only the access-control surface.

    Importing the full ``app.py`` would trigger LlamaIndex/embedding setup
    and memory-index rebuilds; for a posture smoke test we only need the
    live ``access_control`` integration, so we mount the same router the
    production app uses on a throwaway FastAPI instance.
    """
    from api.access import router as access_router

    fast = FastAPI()
    fast.include_router(access_router, prefix="/api")
    return fast


def _loopback_client(app: FastAPI) -> TestClient:
    # Starlette's TestClient defaults to a non-loopback client host
    # ("testclient"); pin it so requests look like real 127.0.0.1 traffic
    # and the loopback-bypass rule is actually exercised.
    return TestClient(app, client=("127.0.0.1", 12345))


@pytest.mark.parametrize(
    "posture,expected_tools",
    [
        (
            "dev",
            {
                "terminal_enabled": True,
                "python_repl_enabled": True,
                "slurm_enabled": True,
                "slurm_legacy_commands_enabled": True,
                "write_file_enabled": True,
            },
        ),
        (
            "trusted-lab",
            {
                "terminal_enabled": True,
                "python_repl_enabled": False,
                "slurm_enabled": True,
                "slurm_legacy_commands_enabled": False,
                "write_file_enabled": True,
            },
        ),
        (
            "hosted-strict",
            {
                "terminal_enabled": False,
                "python_repl_enabled": False,
                "slurm_enabled": False,
                "slurm_legacy_commands_enabled": False,
                "write_file_enabled": False,
            },
        ),
    ],
)
def test_posture_destructive_tool_flags_match_live_policy(
    tmp_path, posture, expected_tools
):
    cfg_file = _write_posture_config(tmp_path, posture)
    with patch("config._CONFIG_FILE", cfg_file):
        import config

        policy = config.get_production_hardening_policy()

    assert policy.posture == posture
    for flag, expected in expected_tools.items():
        assert getattr(policy.tools, flag) is expected, (
            f"{posture}: tools.{flag} should be {expected}"
        )


def test_posture_host_binding_drives_dev_and_hosted_to_loopback(tmp_path):
    for posture, expected_host in (
        ("dev", "127.0.0.1"),
        ("trusted-lab", "0.0.0.0"),
        ("hosted-strict", "127.0.0.1"),
    ):
        cfg_file = _write_posture_config(tmp_path, posture)
        with patch("config._CONFIG_FILE", cfg_file):
            import config

            policy = config.get_production_hardening_policy()

        assert policy.host_binding == expected_host, (
            f"{posture}: host_binding should be {expected_host}"
        )


def test_dev_posture_accepts_unauthenticated_loopback_request(tmp_path):
    cfg_file = _write_posture_config(tmp_path, "dev")
    with patch("config._CONFIG_FILE", cfg_file):
        app = _build_app()
        client = _loopback_client(app)
        response = client.get("/api/access/probe", params={"scope": "execution"})

    assert response.status_code == 200
    assert response.json() == {
        "scope": "execution",
        "authorization_mode": "loopback",
    }


def test_hosted_strict_posture_rejects_unauthenticated_loopback_request(tmp_path):
    cfg_file = _write_posture_config(tmp_path, "hosted-strict")
    with patch("config._CONFIG_FILE", cfg_file):
        app = _build_app()
        client = _loopback_client(app)
        response = client.get("/api/access/probe", params={"scope": "execution"})

    # hosted-strict flips allow_loopback_without_auth off and configures no
    # bearer token by default, so loopback traffic gets a 403 "local access
    # or a configured bearer token" error.
    assert response.status_code == 403


def test_trusted_lab_posture_rejects_unauthenticated_loopback_request(tmp_path):
    cfg_file = _write_posture_config(tmp_path, "trusted-lab")
    with patch("config._CONFIG_FILE", cfg_file):
        app = _build_app()
        client = _loopback_client(app)
        response = client.get("/api/access/probe", params={"scope": "execution"})

    assert response.status_code == 403


@pytest.mark.parametrize(
    "actual,required,expected",
    [
        ("inspection", "inspection", True),
        ("execution", "inspection", True),
        ("admin", "inspection", True),
        ("inspection", "execution", False),
        ("execution", "execution", True),
        ("admin", "execution", True),
        ("inspection", "admin", False),
        ("execution", "admin", False),
        ("admin", "admin", True),
        (None, "execution", False),
        ("garbage", "execution", False),
    ],
)
def test_scope_satisfies_orders_inspection_below_execution_below_admin(
    actual, required, expected
):
    from access_control import scope_satisfies

    assert scope_satisfies(actual, required) is expected
