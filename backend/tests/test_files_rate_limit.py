"""Rate-limiting coverage for the /api/files* endpoints.

The limiter is token-bucket, process-local, keyed by bearer-token identity
when present (else by client host). These tests assert the three acceptance
items from issue #122:

- configurable rate per bucket,
- HTTP 429 + ``Retry-After`` header once the bucket is drained,
- control case at low volume passes through untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def files_app(tmp_path, monkeypatch):
    """Mount the files router with the rate limiter enabled.

    A tight bucket (3 requests / 60 s for reads, 2 / 60 s for writes) keeps the
    tests fast without having to replay the production defaults. Bucket state
    is cleared before and after each test so no other test's traffic affects
    the assertions here.
    """
    from graph.agent import agent_manager
    from api.files import router as files_router
    from rate_limit import clear_buckets
    import config as cfg

    # Ensure the kill-switch isn't inherited from a sibling test.
    monkeypatch.delenv("BIOAPEX_RATE_LIMIT_DISABLED", raising=False)
    tight_limits = {
        "files_read": {"rate": 3, "period_seconds": 60, "enabled": True},
        "files_write": {"rate": 2, "period_seconds": 60, "enabled": True},
    }
    monkeypatch.setattr(cfg, "get_api_rate_limits", lambda: dict(tight_limits))
    clear_buckets()

    original_base_dir = agent_manager.base_dir
    original_memory_indexer = agent_manager.memory_indexer
    agent_manager.base_dir = tmp_path
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("artifacts", "memory", "workspace", "skills", "knowledge"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

    app = FastAPI()
    app.include_router(files_router, prefix="/api")

    try:
        yield app, tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.memory_indexer = original_memory_indexer
        clear_buckets()


def _loopback_client(app: FastAPI, host: str = "127.0.0.1") -> TestClient:
    return TestClient(app, client=(host, 12345))


def test_read_under_limit_succeeds(files_app):
    """Control case — traffic below the bucket limit passes through unchanged."""
    app, base_dir = files_app
    (base_dir / "artifacts" / "small.bin").write_bytes(b"abc")

    with _loopback_client(app) as client:
        for _ in range(2):
            resp = client.get(
                "/api/files/stream",
                params={"path": "artifacts/small.bin"},
            )
            assert resp.status_code == 200
            assert resp.content == b"abc"


def test_read_over_limit_returns_429_with_retry_after(files_app):
    """Draining the read bucket yields 429 + a Retry-After hint."""
    app, base_dir = files_app
    (base_dir / "artifacts" / "small.bin").write_bytes(b"abc")

    with _loopback_client(app) as client:
        for _ in range(3):
            ok = client.get("/api/files/stream", params={"path": "artifacts/small.bin"})
            assert ok.status_code == 200

        drained = client.get(
            "/api/files/stream", params={"path": "artifacts/small.bin"}
        )

    assert drained.status_code == 429
    assert "Retry-After" in drained.headers
    retry = drained.headers["Retry-After"]
    assert retry.isdigit() and int(retry) >= 1


def test_write_over_limit_returns_429(files_app):
    """Streamed writes use a tighter bucket than reads, with the same 429 shape."""
    app, _ = files_app

    with _loopback_client(app) as client:
        for i in range(2):
            resp = client.put(
                "/api/files/stream",
                params={"path": f"artifacts/upload-{i}.bin"},
                content=b"payload",
            )
            assert resp.status_code == 200, resp.text

        drained = client.put(
            "/api/files/stream",
            params={"path": "artifacts/upload-over.bin"},
            content=b"payload",
        )

    assert drained.status_code == 429
    assert drained.headers.get("Retry-After", "").isdigit()


def test_limits_are_per_client_key(files_app):
    """Distinct client hosts consume independent buckets."""
    app, base_dir = files_app
    (base_dir / "artifacts" / "small.bin").write_bytes(b"abc")

    with _loopback_client(app, host="127.0.0.1") as a:
        for _ in range(3):
            assert a.get(
                "/api/files/stream", params={"path": "artifacts/small.bin"}
            ).status_code == 200
        assert a.get(
            "/api/files/stream", params={"path": "artifacts/small.bin"}
        ).status_code == 429

    # A different client host starts with a full bucket.
    with _loopback_client(app, host="::1") as b:
        assert b.get(
            "/api/files/stream", params={"path": "artifacts/small.bin"}
        ).status_code == 200


def test_rate_limit_disabled_env_var_bypasses_limiter(files_app, monkeypatch):
    """The ``BIOAPEX_RATE_LIMIT_DISABLED=1`` kill-switch skips all buckets."""
    app, base_dir = files_app
    (base_dir / "artifacts" / "small.bin").write_bytes(b"abc")

    monkeypatch.setenv("BIOAPEX_RATE_LIMIT_DISABLED", "1")
    with _loopback_client(app) as client:
        # Well beyond the 3-read bucket; all must succeed.
        for _ in range(8):
            resp = client.get(
                "/api/files/stream", params={"path": "artifacts/small.bin"}
            )
            assert resp.status_code == 200


def test_config_override_sets_rate(files_app, monkeypatch):
    """``config.get_api_rate_limits`` overrides take precedence over defaults."""
    from rate_limit import clear_buckets
    import config as cfg

    app, base_dir = files_app
    (base_dir / "artifacts" / "small.bin").write_bytes(b"abc")

    # Squeeze the read bucket down to 1 request regardless of defaults.
    monkeypatch.setattr(
        cfg,
        "get_api_rate_limits",
        lambda: {"files_read": {"rate": 1, "period_seconds": 60, "enabled": True}},
    )
    clear_buckets()

    with _loopback_client(app) as client:
        assert client.get(
            "/api/files/stream", params={"path": "artifacts/small.bin"}
        ).status_code == 200
        drained = client.get(
            "/api/files/stream", params={"path": "artifacts/small.bin"}
        )
        assert drained.status_code == 429
        assert drained.headers["Retry-After"].isdigit()
