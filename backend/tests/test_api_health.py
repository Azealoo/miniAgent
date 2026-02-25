"""
Tests for API endpoints that do NOT require a live LLM or embeddings.
Uses FastAPI's TestClient but mocks the lifespan startup so no real
LLM/embedding calls are made.
"""
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client(tmp_path):
    """
    Spin up the FastAPI app with a mocked lifespan and a real but isolated
    SessionManager and AgentManager (no LLM, no embeddings).
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from graph.session_manager import SessionManager

    @asynccontextmanager
    async def mock_lifespan(app):
        yield

    # Import app *after* patching to avoid real startup
    with patch("app.lifespan", mock_lifespan):
        import app as app_module
        test_app = FastAPI(title="test")

        # Register routers manually
        from api.sessions import router as sessions_router
        from api.files import router as files_router
        from api.config_api import router as config_router

        test_app.include_router(sessions_router, prefix="/api")
        test_app.include_router(files_router, prefix="/api")
        test_app.include_router(config_router, prefix="/api")

        @test_app.get("/")
        def health():
            return {"status": "ok", "service": "miniOpenClaw"}

        # Wire up a real SessionManager to agent_manager
        from graph.agent import agent_manager
        agent_manager.session_manager = SessionManager(base_dir=tmp_path)
        agent_manager.base_dir = tmp_path

        # Create workspace dirs expected by files.py
        (tmp_path / "workspace").mkdir(exist_ok=True)
        (tmp_path / "memory").mkdir(exist_ok=True)
        (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
        (tmp_path / "SKILLS_SNAPSHOT.md").write_text("<available_skills/>", encoding="utf-8")
        (tmp_path / "skills").mkdir(exist_ok=True)

        yield TestClient(test_app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "miniOpenClaw"


class TestSessionsEndpoints:
    def test_list_sessions_empty(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_session(self, client):
        resp = client.post("/api/sessions")
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] == "New Chat"
        assert data["message_count"] == 0

    def test_create_multiple_sessions(self, client):
        ids = [client.post("/api/sessions").json()["id"] for _ in range(3)]
        resp = client.get("/api/sessions")
        listed_ids = {s["id"] for s in resp.json()}
        for sid in ids:
            assert sid in listed_ids

    def test_rename_session(self, client):
        sid = client.post("/api/sessions").json()["id"]
        resp = client.put(f"/api/sessions/{sid}", json={"title": "My Test"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "My Test"

    def test_delete_session(self, client):
        sid = client.post("/api/sessions").json()["id"]
        resp = client.delete(f"/api/sessions/{sid}")
        assert resp.status_code == 204
        listed = {s["id"] for s in client.get("/api/sessions").json()}
        assert sid not in listed

    def test_get_history_empty_session(self, client):
        sid = client.post("/api/sessions").json()["id"]
        resp = client.get(f"/api/sessions/{sid}/history")
        assert resp.status_code == 200
        assert resp.json() == []


class TestFilesEndpoints:
    def test_read_memory_md(self, client):
        resp = client.get("/api/files", params={"path": "memory/MEMORY.md"})
        assert resp.status_code == 200
        assert resp.json()["path"] == "memory/MEMORY.md"
        assert "Memory" in resp.json()["content"]

    def test_read_nonexistent_file_404(self, client):
        resp = client.get("/api/files", params={"path": "memory/no_such.md"})
        assert resp.status_code == 404

    def test_read_path_traversal_blocked(self, client):
        resp = client.get("/api/files", params={"path": "../../../etc/passwd"})
        assert resp.status_code in (403, 400)

    def test_read_disallowed_prefix_blocked(self, client):
        resp = client.get("/api/files", params={"path": "config.py"})
        assert resp.status_code == 403

    def test_save_and_read_memory(self, client):
        resp = client.post("/api/files", json={"path": "memory/MEMORY.md", "content": "# Updated\n"})
        assert resp.status_code == 200
        assert resp.json()["saved"] is True
        # Read back
        read = client.get("/api/files", params={"path": "memory/MEMORY.md"})
        assert "Updated" in read.json()["content"]

    def test_list_skills(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestConfigEndpoints:
    def test_get_rag_mode_default(self, client, tmp_path):
        # Remove any existing config.json to test default
        cfg = tmp_path / "config.json"
        if cfg.exists():
            cfg.unlink()
        with patch("config._CONFIG_FILE", tmp_path / "config.json"):
            resp = client.get("/api/config/rag-mode")
        assert resp.status_code == 200
        assert "rag_mode" in resp.json()

    def test_set_rag_mode(self, client, tmp_path):
        with patch("config._CONFIG_FILE", tmp_path / "config.json"):
            resp = client.put("/api/config/rag-mode", json={"enabled": True})
            assert resp.status_code == 200
            assert resp.json()["rag_mode"] is True
