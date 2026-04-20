"""Content-type and nosniff hardening for whitelisted file reads.

Tool-output overflow files are written as ``.txt`` under
``storage/tool-outputs/`` (see ``tools.policy_wrappers._persist_tool_output_overflow``)
and are readable through the files API. A browser that fetches one must not
be able to MIME-sniff embedded ``<script>`` and render it as HTML, so the
``/files/raw``, ``/files/stream``, and ``HEAD /files/stream`` handlers must:

- declare an explicit ``text/plain; charset=utf-8`` content type for ``.txt``, and
- set ``X-Content-Type-Options: nosniff`` on the response.
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
    from graph.agent import agent_manager
    from api.files import router as files_router
    from rate_limit import clear_buckets

    monkeypatch.setenv("BIOAPEX_RATE_LIMIT_DISABLED", "1")
    clear_buckets()

    original_base_dir = agent_manager.base_dir
    original_memory_indexer = agent_manager.memory_indexer
    agent_manager.base_dir = tmp_path
    agent_manager.memory_indexer = MagicMock()

    for relpath in (
        "artifacts",
        "memory",
        "workspace",
        "skills",
        "knowledge",
        "storage/tool-outputs",
    ):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

    app = FastAPI()
    app.include_router(files_router, prefix="/api")

    try:
        yield app, tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.memory_indexer = original_memory_indexer
        clear_buckets()


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 12345))


def _write_overflow(base_dir: Path) -> str:
    rel = "storage/tool-outputs/session-123/turn-abc-tool-deadbeef.txt"
    target = base_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("<script>alert(1)</script> plain overflow body\n", encoding="utf-8")
    return rel


def test_raw_overflow_txt_has_explicit_charset_and_nosniff(files_app):
    app, base_dir = files_app
    rel = _write_overflow(base_dir)

    with _client(app) as client:
        resp = client.get("/api/files/raw", params={"path": rel})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_stream_overflow_txt_has_explicit_charset_and_nosniff(files_app):
    app, base_dir = files_app
    rel = _write_overflow(base_dir)

    with _client(app) as client:
        resp = client.get("/api/files/stream", params={"path": rel})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_stream_head_overflow_txt_has_explicit_charset_and_nosniff(files_app):
    app, base_dir = files_app
    rel = _write_overflow(base_dir)

    with _client(app) as client:
        resp = client.head("/api/files/stream", params={"path": rel})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/plain; charset=utf-8"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_raw_non_txt_still_gets_nosniff(files_app):
    """nosniff is defense-in-depth for every raw response, not only ``.txt``."""
    app, base_dir = files_app
    (base_dir / "artifacts" / "data.json").write_text('{"k": 1}', encoding="utf-8")

    with _client(app) as client:
        resp = client.get("/api/files/raw", params={"path": "artifacts/data.json"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.headers["x-content-type-options"] == "nosniff"
