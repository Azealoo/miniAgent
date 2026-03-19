"""
Tests for API endpoint logic that does NOT require a live LLM or embeddings.

These tests exercise the route handlers directly instead of going through an
in-process ASGI client, which currently hangs in this environment.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def isolated_api_state(tmp_path):
    """Set up an isolated backend root and patch agent_manager to point at it."""
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)

    (tmp_path / "workspace").mkdir(exist_ok=True)
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    (tmp_path / "artifacts" / "demo" / "2026-03-18" / "run-20260318T190203Z-deadbeef").mkdir(
        parents=True,
        exist_ok=True,
    )
    (
        tmp_path
        / "artifacts"
        / "demo"
        / "2026-03-18"
        / "run-20260318T190203Z-deadbeef"
        / "run.json"
    ).write_text('{"artifact_type": "workflow_run"}\n', encoding="utf-8")
    (tmp_path / "SKILLS_SNAPSHOT.md").write_text("<available_skills/>", encoding="utf-8")
    (tmp_path / "skills").mkdir(exist_ok=True)
    (tmp_path / "skills" / "demo").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "demo" / "SKILL.md").write_text(
        (
            "---\nname: demo\ndescription: Demo skill\ncategory: bio/test\n"
            "stage: analysis\ntags: [demo]\naliases: [demo_alias]\nversion: 1.0\n"
            "requires_tools: [read_file]\nrequires_network: false\nuser_invocable: true\n"
            "---\n# Demo\n## Steps\n1. Do stuff\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "skills" / "bio" / "nested" / "deep_skill").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills" / "bio" / "nested" / "deep_skill" / "SKILL.md").write_text(
        (
            "---\nname: deep_skill\ndescription: Nested skill\ncategory: bio/test\n"
            "stage: qc\nversion: 1.0\nrequires_tools: [read_file]\n"
            "requires_network: false\nuser_invocable: true\n---\n# Nested\n## Steps\n1. Do stuff\n"
        ),
        encoding="utf-8",
    )

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager


class TestHealthEndpoint:
    def test_health_returns_ok(self):
        import app

        resp = app.health()
        assert resp["status"] == "ok"
        assert resp["service"] == "miniOpenClaw"


class TestSessionsEndpoints:
    def test_list_sessions_empty(self, isolated_api_state):
        from api.sessions import list_sessions

        resp = list_sessions()
        assert isinstance(resp, list)

    def test_create_session(self, isolated_api_state):
        from api.sessions import create_session

        data = create_session()
        assert "id" in data
        assert data["title"] == "New Chat"
        assert data["message_count"] == 0

    def test_create_multiple_sessions(self, isolated_api_state):
        from api.sessions import create_session, list_sessions

        ids = [create_session()["id"] for _ in range(3)]
        listed_ids = {s["id"] for s in list_sessions()}
        for sid in ids:
            assert sid in listed_ids

    def test_rename_session(self, isolated_api_state):
        from api.sessions import RenameRequest, create_session, rename_session

        sid = create_session()["id"]
        resp = rename_session(sid, RenameRequest(title="My Test"))
        assert resp["title"] == "My Test"

    def test_delete_session(self, isolated_api_state):
        from api.sessions import create_session, delete_session, list_sessions

        sid = create_session()["id"]
        delete_session(sid)
        listed = {s["id"] for s in list_sessions()}
        assert sid not in listed

    def test_get_history_empty_session(self, isolated_api_state):
        from api.sessions import create_session, get_history

        sid = create_session()["id"]
        assert get_history(sid) == []


class TestFilesEndpoints:
    def test_read_memory_md(self, isolated_api_state):
        from api.files import read_file

        resp = read_file("memory/MEMORY.md")
        assert resp["path"] == "memory/MEMORY.md"
        assert "Memory" in resp["content"]

    def test_read_nonexistent_file_404(self, isolated_api_state):
        from api.files import read_file

        with pytest.raises(HTTPException) as exc_info:
            read_file("memory/no_such.md")
        assert exc_info.value.status_code == 404

    def test_read_artifact_file(self, isolated_api_state):
        from api.files import read_file

        resp = read_file("artifacts/demo/2026-03-18/run-20260318T190203Z-deadbeef/run.json")
        assert "workflow_run" in resp["content"]

    def test_read_path_traversal_blocked(self, isolated_api_state):
        from api.files import read_file

        with pytest.raises(HTTPException) as exc_info:
            read_file("../../../etc/passwd")
        assert exc_info.value.status_code in (403, 400)

    def test_read_disallowed_prefix_blocked(self, isolated_api_state):
        from api.files import read_file

        with pytest.raises(HTTPException) as exc_info:
            read_file("config.py")
        assert exc_info.value.status_code == 403

    def test_save_and_read_memory(self, isolated_api_state):
        from api.files import SaveRequest, read_file, save_file

        resp = save_file(SaveRequest(path="memory/MEMORY.md", content="# Updated\n"))
        assert resp["saved"] is True
        assert "Updated" in read_file("memory/MEMORY.md")["content"]

    def test_save_artifact_file_blocked(self, isolated_api_state):
        from api.files import SaveRequest, save_file

        with pytest.raises(HTTPException) as exc_info:
            save_file(
                SaveRequest(
                    path="artifacts/demo/2026-03-18/run-20260318T190203Z-deadbeef/run.json",
                    content="{}\n",
                )
            )
        assert exc_info.value.status_code == 403

    def test_list_skills(self, isolated_api_state):
        from api.files import list_skills

        resp = list_skills()
        names = {item["name"] for item in resp}
        assert "demo" in names
        assert "deep_skill" in names

    def test_list_skills_includes_metadata(self, isolated_api_state):
        from api.files import list_skills

        demo = next(item for item in list_skills() if item["name"] == "demo")
        assert demo["category"] == "bio/test"
        assert demo["stage"] == "analysis"

    def test_skills_registry_exposes_extended_metadata(self, isolated_api_state):
        from api.skills_registry import list_registry

        demo = next(item for item in list_registry() if item["name"] == "demo")
        assert demo["category"] == "bio/test"
        assert demo["stage"] == "analysis"
        assert demo["tags"] == ["demo"]
        assert demo["aliases"] == ["demo_alias"]
        assert demo["enabled"] is True


class TestConfigEndpoints:
    def test_get_rag_mode_default(self, isolated_api_state, tmp_path):
        from api.config_api import get_rag_mode

        cfg_path = tmp_path / "config.json"
        if cfg_path.exists():
            cfg_path.unlink()

        with patch("config._CONFIG_FILE", cfg_path):
            resp = get_rag_mode()
        assert "rag_mode" in resp

    def test_set_rag_mode(self, isolated_api_state, tmp_path):
        from api.config_api import RagModeRequest, set_rag_mode

        with patch("config._CONFIG_FILE", tmp_path / "config.json"):
            resp = set_rag_mode(RagModeRequest(enabled=True))
        assert resp["rag_mode"] is True
