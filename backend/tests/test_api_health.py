"""
Tests for API endpoint logic that does NOT require a live LLM or embeddings.

These tests exercise the route handlers directly instead of going through an
in-process ASGI client, which currently hangs in this environment.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).parent.parent))


def _request(
    path: str,
    *,
    method: str = "GET",
    host: str = "127.0.0.1",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
            "client": (host, 12345),
        }
    )


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
    (tmp_path / "artifacts" / "reference_schemas").mkdir(parents=True, exist_ok=True)
    (
        tmp_path
        / "artifacts"
        / "reference_schemas"
        / "biocompute_bioapex_extension.v1.schema.json"
    ).write_text(
        (
            '{"$schema": "https://json-schema.org/draft/2020-12/schema", '
            '"$id": "http://localhost:8002/api/files/raw?path=artifacts/reference_schemas/'
            'biocompute_bioapex_extension.v1.schema.json"}\n'
        ),
        encoding="utf-8",
    )
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

    def test_app_cors_defaults_to_local_origins(self):
        import app

        cors = next(middleware for middleware in app.app.user_middleware if middleware.cls.__name__ == "CORSMiddleware")
        assert cors.kwargs["allow_origins"] == [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]


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

    def test_session_reads_block_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.sessions import create_session, get_history, list_sessions

        sid = create_session()["id"]

        with pytest.raises(HTTPException) as exc_info:
            list_sessions(_request("/api/sessions", host="10.0.0.8"))
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            get_history(
                sid,
                _request(f"/api/sessions/{sid}/history", host="10.0.0.8"),
            )
        assert exc_info.value.status_code == 403

    def test_session_reads_allow_non_local_clients_with_inspection_token(self, isolated_api_state):
        from api.sessions import create_session, get_history, list_sessions

        sid = create_session()["id"]
        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "inspection_bearer_token_env_var": "BIOAPEX_INSPECTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer inspection-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_INSPECTION_TOKEN": "inspection-token"},
            clear=False,
        ):
            sessions = list_sessions(_request("/api/sessions", host="10.0.0.8", headers=headers))
            history = get_history(
                sid,
                _request(f"/api/sessions/{sid}/history", host="10.0.0.8", headers=headers),
            )

        assert any(item["id"] == sid for item in sessions)
        assert history == []

    def test_session_mutations_block_non_local_clients_without_execution_token(self, isolated_api_state):
        from api.sessions import RenameRequest, create_session, delete_session, rename_session

        with pytest.raises(HTTPException) as exc_info:
            create_session(_request("/api/sessions", method="POST", host="10.0.0.8"))
        assert exc_info.value.status_code == 403

        sid = create_session()["id"]
        with pytest.raises(HTTPException) as exc_info:
            rename_session(
                sid,
                RenameRequest(title="Blocked"),
                _request(f"/api/sessions/{sid}", method="PUT", host="10.0.0.8"),
            )
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            delete_session(
                sid,
                _request(f"/api/sessions/{sid}", method="DELETE", host="10.0.0.8"),
            )
        assert exc_info.value.status_code == 403

    def test_session_create_allows_non_local_clients_with_execution_token(self, isolated_api_state):
        from api.sessions import create_session

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer execution-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
            clear=False,
        ):
            data = create_session(
                _request("/api/sessions", method="POST", host="10.0.0.8", headers=headers)
            )

        assert "id" in data
        assert data["title"] == "New Chat"

    @pytest.mark.asyncio
    async def test_generate_title_blocks_non_local_clients_without_execution_token(self, isolated_api_state):
        from api.sessions import create_session, generate_title
        from graph.agent import agent_manager

        sid = create_session()["id"]
        agent_manager.session_manager.save_message(sid, "user", "Name this chat")

        with pytest.raises(HTTPException) as exc_info:
            await generate_title(
                sid,
                _request(f"/api/sessions/{sid}/generate-title", method="POST", host="10.0.0.8"),
            )

        assert exc_info.value.status_code == 403


class TestCompressionEndpoint:
    @pytest.mark.asyncio
    async def test_compress_returns_structured_summary(self, isolated_api_state):
        from api.compress import compress
        from api.sessions import create_session
        from graph.agent import agent_manager
        from graph.session_summary import MAX_SUMMARY_CHARS, STRUCTURED_SUMMARY_HEADER

        sid = create_session()["id"]
        for i in range(6):
            agent_manager.session_manager.save_message(
                sid,
                "user" if i % 2 == 0 else "assistant",
                f"msg-{i}",
            )

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)

        async def fake_ainvoke(_msgs):
            mock_resp = MagicMock()
            mock_resp.content = (
                "Legacy free-text summary with PMID:12345 and /tmp/run-1/result.txt "
                + ("extra detail " * 400)
            )
            return mock_resp

        mock_llm.ainvoke = fake_ainvoke
        mock_llm.bind.return_value.ainvoke = fake_ainvoke
        original_llm = agent_manager.llm
        agent_manager.llm = mock_llm

        try:
            resp = await compress(sid)
        finally:
            agent_manager.llm = original_llm

        assert resp["archived_count"] == 4
        assert resp["remaining_count"] == 2
        assert STRUCTURED_SUMMARY_HEADER in resp["summary"]
        assert "Results register:" in resp["summary"]
        assert "Legacy free-text summary with PMID:12345" in resp["summary"]
        assert len(resp["summary"]) <= MAX_SUMMARY_CHARS

    @pytest.mark.asyncio
    async def test_compress_blocks_non_local_clients_without_execution_token(self, isolated_api_state):
        from api.compress import compress
        from api.sessions import create_session
        from graph.agent import agent_manager

        sid = create_session()["id"]
        for i in range(6):
            agent_manager.session_manager.save_message(
                sid,
                "user" if i % 2 == 0 else "assistant",
                f"msg-{i}",
            )

        with pytest.raises(HTTPException) as exc_info:
            await compress(
                sid,
                _request(f"/api/sessions/{sid}/compress", method="POST", host="10.0.0.8"),
            )

        assert exc_info.value.status_code == 403


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

    def test_read_artifact_file_raw(self, isolated_api_state):
        from api.files import read_raw_file

        resp = read_raw_file("artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json")
        assert resp.media_type == "application/json"
        assert b'"$schema"' in resp.body

    def test_read_artifact_reference_schema_raw_rewrites_schema_id_to_public_url(
        self,
        isolated_api_state,
        monkeypatch,
    ):
        from api.files import read_raw_file

        monkeypatch.setenv("BIOAPEX_PUBLIC_BASE_URL", "https://bioapex.example.org/base/")

        resp = read_raw_file("artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json")
        payload = json.loads(resp.body.decode("utf-8"))

        assert payload["$id"] == (
            "https://bioapex.example.org/base/api/files/raw"
            "?path=artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json"
        )

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

    def test_read_secret_like_file_blocked(self, isolated_api_state):
        from api.files import read_file

        (isolated_api_state / "memory" / ".env").write_text("SECRET=1\n", encoding="utf-8")

        with pytest.raises(HTTPException) as exc_info:
            read_file("memory/.env")
        assert exc_info.value.status_code == 403

    def test_read_blocks_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.files import read_file, read_raw_file

        with pytest.raises(HTTPException) as exc_info:
            read_file("memory/MEMORY.md", _request("/api/files", host="10.0.0.8"))
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            read_raw_file(
                "artifacts/reference_schemas/biocompute_bioapex_extension.v1.schema.json",
                _request("/api/files/raw", host="10.0.0.8"),
            )
        assert exc_info.value.status_code == 403

    def test_read_allows_non_local_clients_with_inspection_token(self, isolated_api_state):
        from api.files import read_file

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "inspection_bearer_token_env_var": "BIOAPEX_INSPECTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer inspection-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_INSPECTION_TOKEN": "inspection-token"},
            clear=False,
        ):
            resp = read_file("memory/MEMORY.md", _request("/api/files", host="10.0.0.8", headers=headers))

        assert "Memory" in resp["content"]

    def test_read_routes_do_not_fall_back_to_execution_token(self, isolated_api_state):
        from api.files import read_file

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer execution-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
            clear=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                read_file("memory/MEMORY.md", _request("/api/files", host="10.0.0.8", headers=headers))

        assert exc_info.value.status_code == 403

    def test_save_and_read_memory(self, isolated_api_state):
        from api.files import SaveRequest, read_file, save_file

        resp = save_file(SaveRequest(path="memory/MEMORY.md", content="# Updated\n"))
        assert resp["saved"] is True
        assert "Updated" in read_file("memory/MEMORY.md")["content"]

    def test_save_secret_like_file_blocked(self, isolated_api_state):
        from api.files import SaveRequest, save_file

        with pytest.raises(HTTPException) as exc_info:
            save_file(SaveRequest(path="memory/.env", content="SECRET=1\n"))
        assert exc_info.value.status_code == 403

    def test_save_blocked_when_file_editor_policy_disabled(self, isolated_api_state):
        from api.files import SaveRequest, save_file

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps({"production_hardening": {"api": {"files_write_enabled": False}}}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", config_path), pytest.raises(HTTPException) as exc_info:
            save_file(SaveRequest(path="memory/MEMORY.md", content="# Updated\n"))
        assert exc_info.value.status_code == 403

    def test_save_blocks_non_local_clients_without_bearer_token(self, isolated_api_state):
        from api.files import SaveRequest, save_file

        with pytest.raises(HTTPException) as exc_info:
            save_file(
                SaveRequest(path="memory/MEMORY.md", content="# Updated\n"),
                _request("/api/files", method="POST", host="10.0.0.8"),
            )
        assert exc_info.value.status_code == 403

    def test_save_allows_non_local_clients_with_execution_bearer_token(self, isolated_api_state):
        from api.files import SaveRequest, read_file, save_file

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer execution-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
            clear=False,
        ):
            resp = save_file(
                SaveRequest(path="memory/MEMORY.md", content="# Updated\n"),
                _request("/api/files", method="POST", host="10.0.0.8", headers=headers),
            )

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

    def test_list_skills_blocks_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.files import list_skills

        with pytest.raises(HTTPException) as exc_info:
            list_skills(_request("/api/skills", host="10.0.0.8"))

        assert exc_info.value.status_code == 403

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

    def test_skills_registry_list_blocks_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.skills_registry import list_registry

        with pytest.raises(HTTPException) as exc_info:
            list_registry(_request("/api/skills/registry", host="10.0.0.8"))

        assert exc_info.value.status_code == 403

    def test_skills_registry_update_blocks_non_local_clients_without_admin_token(self, isolated_api_state):
        from api.skills_registry import SkillEntryUpdate, update_skill_entry

        with pytest.raises(HTTPException) as exc_info:
            update_skill_entry(
                "demo",
                SkillEntryUpdate(enabled=False),
                _request("/api/skills/registry/demo", method="PUT", host="10.0.0.8"),
            )

        assert exc_info.value.status_code == 403

    def test_skills_registry_update_allows_non_local_clients_with_admin_token(self, isolated_api_state):
        from api.skills_registry import SkillEntryUpdate, list_registry, update_skill_entry

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "admin_bearer_token_env_var": "BIOAPEX_ADMIN_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer admin-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_ADMIN_TOKEN": "admin-token"},
            clear=False,
        ):
            response = update_skill_entry(
                "demo",
                SkillEntryUpdate(enabled=False),
                _request("/api/skills/registry/demo", method="PUT", host="10.0.0.8", headers=headers),
            )
            demo = next(item for item in list_registry() if item["name"] == "demo")

        assert response["enabled"] is False
        assert demo["enabled"] is False


class TestConfigEndpoints:
    def test_get_rag_mode_default(self, isolated_api_state, tmp_path):
        from api.config_api import get_rag_mode

        cfg_path = tmp_path / "config.json"
        if cfg_path.exists():
            cfg_path.unlink()

        with patch("config._CONFIG_FILE", cfg_path):
            resp = get_rag_mode(_request("/api/config/rag-mode"))
        assert "rag_mode" in resp

    def test_set_rag_mode(self, isolated_api_state, tmp_path):
        from api.config_api import RagModeRequest, set_rag_mode

        with patch("config._CONFIG_FILE", tmp_path / "config.json"):
            resp = set_rag_mode(RagModeRequest(enabled=True), _request("/api/config/rag-mode", method="PUT"))
        assert resp["rag_mode"] is True

    def test_get_production_hardening_returns_effective_policy(self, isolated_api_state):
        from api.config_api import get_production_hardening

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "tools": {"terminal_enabled": False},
                        "api": {"connectors_runtime_actions_enabled": False},
                    }
                }
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", config_path):
            resp = get_production_hardening(_request("/api/config/production-hardening"))

        assert resp["tools"]["terminal_enabled"] is False
        assert resp["api"]["connectors_runtime_actions_enabled"] is False

    def test_config_routes_block_non_local_clients(self, isolated_api_state, tmp_path):
        from api.config_api import RagModeRequest, get_production_hardening, get_rag_mode, set_rag_mode

        with patch("config._CONFIG_FILE", tmp_path / "config.json"):
            with pytest.raises(HTTPException) as exc_info:
                get_rag_mode(_request("/api/config/rag-mode", host="10.0.0.8"))
            assert exc_info.value.status_code == 403

            with pytest.raises(HTTPException) as exc_info:
                get_production_hardening(_request("/api/config/production-hardening", host="10.0.0.8"))
            assert exc_info.value.status_code == 403

            with pytest.raises(HTTPException) as exc_info:
                set_rag_mode(
                    RagModeRequest(enabled=True),
                    _request("/api/config/rag-mode", method="PUT", host="10.0.0.8"),
                )
            assert exc_info.value.status_code == 403

    def test_config_routes_allow_non_local_clients_with_admin_token(self, isolated_api_state):
        from api.config_api import RagModeRequest, get_production_hardening, get_rag_mode, set_rag_mode

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "admin_bearer_token_env_var": "BIOAPEX_ADMIN_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer admin-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_ADMIN_TOKEN": "admin-token"},
            clear=False,
        ):
            assert get_rag_mode(_request("/api/config/rag-mode", host="10.0.0.8", headers=headers))["rag_mode"] is False
            assert "tools" in get_production_hardening(
                _request("/api/config/production-hardening", host="10.0.0.8", headers=headers)
            )
            resp = set_rag_mode(
                RagModeRequest(enabled=True),
                _request("/api/config/rag-mode", method="PUT", host="10.0.0.8", headers=headers),
            )

        assert resp["rag_mode"] is True

    def test_config_routes_do_not_fall_back_to_execution_token(self, isolated_api_state):
        from api.config_api import get_production_hardening

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "execution_bearer_token_env_var": "BIOAPEX_EXECUTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer execution-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_EXECUTION_TOKEN": "execution-token"},
            clear=False,
        ):
            with pytest.raises(HTTPException) as exc_info:
                get_production_hardening(
                    _request("/api/config/production-hardening", host="10.0.0.8", headers=headers)
                )

        assert exc_info.value.status_code == 403


class TestArtifactRegistryEndpoints:
    def test_list_registry_blocks_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.artifact_registry import list_artifact_registry

        with pytest.raises(HTTPException) as exc_info:
            list_artifact_registry(request=_request("/api/artifacts/registry", host="10.0.0.8"))

        assert exc_info.value.status_code == 403

    def test_list_registry_allows_non_local_clients_with_inspection_token(self, isolated_api_state):
        from api.artifact_registry import list_artifact_registry
        from artifacts.registry import rebuild_artifact_registry

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "inspection_bearer_token_env_var": "BIOAPEX_INSPECTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer inspection-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_INSPECTION_TOKEN": "inspection-token"},
            clear=False,
        ):
            rebuild_artifact_registry(isolated_api_state)
            snapshot = list_artifact_registry(request=_request("/api/artifacts/registry", host="10.0.0.8", headers=headers))

        assert "records" in snapshot

    def test_rebuild_registry_blocks_non_local_clients_without_admin_token(self, isolated_api_state):
        from api.artifact_registry import rebuild_registry

        with pytest.raises(HTTPException) as exc_info:
            rebuild_registry(_request("/api/artifacts/registry/rebuild", method="POST", host="10.0.0.8"))

        assert exc_info.value.status_code == 403

    def test_rebuild_registry_allows_non_local_clients_with_admin_token(self, isolated_api_state):
        from api.artifact_registry import rebuild_registry

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "admin_bearer_token_env_var": "BIOAPEX_ADMIN_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer admin-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_ADMIN_TOKEN": "admin-token"},
            clear=False,
        ):
            snapshot = rebuild_registry(
                _request("/api/artifacts/registry/rebuild", method="POST", host="10.0.0.8", headers=headers)
            )

        assert snapshot["record_count"] >= 1


class TestAuditEndpoints:
    def test_audit_route_blocks_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.audit import list_audit_events

        with pytest.raises(HTTPException) as exc_info:
            list_audit_events(request=_request("/api/audit/events", host="10.0.0.8"))

        assert exc_info.value.status_code == 403

    def test_audit_route_allows_non_local_clients_with_inspection_token(self, isolated_api_state):
        from api.audit import list_audit_events

        config_path = isolated_api_state / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "production_hardening": {
                        "api": {
                            "allow_loopback_without_auth": False,
                            "inspection_bearer_token_env_var": "BIOAPEX_INSPECTION_TOKEN",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        headers = [(b"authorization", b"Bearer inspection-token")]

        with patch("config._CONFIG_FILE", config_path), patch.dict(
            os.environ,
            {"BIOAPEX_INSPECTION_TOKEN": "inspection-token"},
            clear=False,
        ):
            response = list_audit_events(request=_request("/api/audit/events", host="10.0.0.8", headers=headers))

        assert "events" in response


class TestTokenEndpoints:
    def test_session_tokens_includes_usage_breakdown(self, isolated_api_state):
        from api.tokens import _count, session_tokens
        from graph.agent import agent_manager

        session_id = agent_manager.session_manager.create_session()
        agent_manager.session_manager.save_message(session_id, "user", "Plan a CRISPR screen")
        agent_manager.session_manager.save_message(
            session_id,
            "assistant",
            "I found the latest workflow artifacts.",
            tool_calls=[
                {
                    "tool": "read_file",
                    "input": "artifacts/rnaseq-qc/run.json",
                    "output": "{\"status\":\"completed\"}",
                }
            ],
        )

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_MODEL": "deepseek-chat",
                "MODEL_CONTEXT_WINDOW_TOKENS": "4096",
            },
            clear=False,
        ):
            result = session_tokens(session_id)

        expected_user_tokens = _count("Plan a CRISPR screen")
        expected_assistant_tokens = _count("I found the latest workflow artifacts.")
        expected_tool_tokens = (
            _count("artifacts/rnaseq-qc/run.json") + _count("{\"status\":\"completed\"}")
        )

        assert result["session_id"] == session_id
        assert result["system_tokens"] > 0
        assert result["message_tokens"] == expected_user_tokens + expected_assistant_tokens
        assert result["total_tokens"] == result["system_tokens"] + result["message_tokens"]
        assert result["input_tokens"] == result["system_tokens"] + expected_user_tokens
        assert result["output_tokens"] == expected_assistant_tokens
        assert result["tool_tokens"] == expected_tool_tokens
        assert result["tracked_total_tokens"] == (
            result["input_tokens"] + result["output_tokens"] + result["tool_tokens"]
        )
        assert result["context_window_tokens"] == 4096
        assert result["context_window_remaining_tokens"] == 4096 - result["total_tokens"]
        assert result["model_name"] == "deepseek-chat"

    def test_session_tokens_include_compressed_context_in_prompt_budget(
        self, isolated_api_state
    ):
        from api.tokens import _count, session_tokens
        from graph.agent import agent_manager

        session_id = agent_manager.session_manager.create_session()
        agent_manager.session_manager.save_message(session_id, "user", "First question")
        agent_manager.session_manager.save_message(session_id, "assistant", "First answer")
        agent_manager.session_manager.save_message(session_id, "user", "Second question")
        agent_manager.session_manager.save_message(session_id, "assistant", "Second answer")

        compressed_summary = "Earlier work summary"
        agent_manager.session_manager.compress_history(session_id, compressed_summary, 2)

        summary_wrapper = (
            "[Summary of earlier conversation — treat as background context]\n"
            f"{compressed_summary}"
        )
        expected_summary_tokens = _count(summary_wrapper)
        expected_user_tokens = _count("Second question")
        expected_assistant_tokens = _count("Second answer")

        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_MODEL": "deepseek-chat",
                "MODEL_CONTEXT_WINDOW_TOKENS": "4096",
            },
            clear=False,
        ):
            result = session_tokens(session_id)

        assert result["message_tokens"] == (
            expected_summary_tokens + expected_user_tokens + expected_assistant_tokens
        )
        assert result["input_tokens"] == (
            result["system_tokens"] + expected_summary_tokens + expected_user_tokens
        )
        assert result["output_tokens"] == expected_assistant_tokens
        assert result["tool_tokens"] == 0
        assert result["total_tokens"] == result["system_tokens"] + result["message_tokens"]
        assert result["context_window_remaining_tokens"] == 4096 - result["total_tokens"]

    def test_files_tokens_counts_allowed_file(self, isolated_api_state):
        from api.tokens import FilesTokenRequest, files_tokens

        result = files_tokens(FilesTokenRequest(paths=["memory/MEMORY.md"]))

        assert result[0]["path"] == "memory/MEMORY.md"
        assert result[0]["tokens"] > 0

    def test_files_tokens_blocks_secret_like_files(self, isolated_api_state):
        from api.tokens import FilesTokenRequest, files_tokens

        (isolated_api_state / "memory" / ".env").write_text("SECRET=1\n", encoding="utf-8")

        result = files_tokens(FilesTokenRequest(paths=["memory/.env"]))

        assert result == [{"path": "memory/.env", "tokens": 0}]

    def test_files_tokens_block_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.tokens import FilesTokenRequest, files_tokens

        with pytest.raises(HTTPException) as exc_info:
            files_tokens(
                FilesTokenRequest(paths=["memory/MEMORY.md"]),
                _request("/api/tokens/files", method="POST", host="10.0.0.8"),
            )

        assert exc_info.value.status_code == 403


class TestObservabilityEndpoints:
    def test_observability_routes_return_metrics_traces_and_overview(self, isolated_api_state):
        from api.observability import (
            get_observability_dashboard_definitions,
            get_observability_overview,
            list_observability_metrics,
            list_observability_traces,
        )
        from observability import append_metric_record, append_trace_record, chat_span_id

        now = datetime.now(timezone.utc)
        append_metric_record(
            isolated_api_state,
            metric_name="chat_latency_seconds",
            metric_kind="duration",
            value=0.42,
            unit="seconds",
            request_id="request-api-1",
            session_id="session-api-1",
            trace_id="request-api-1",
            span_id=chat_span_id("request-api-1"),
            attributes={"latency_scope": "user_visible"},
            recorded_at=now,
        )
        append_trace_record(
            isolated_api_state,
            trace_id="request-api-1",
            span_id=chat_span_id("request-api-1"),
            span_name="chat_turn",
            started_at=now,
            ended_at=now,
            status="ok",
            request_id="request-api-1",
            session_id="session-api-1",
        )

        metrics = list_observability_metrics(request_id="request-api-1", limit=20)
        traces = list_observability_traces(request_id="request-api-1", limit=20)
        overview = get_observability_overview(request_id="request-api-1", days=1, limit=100)
        dashboards = get_observability_dashboard_definitions()

        assert len(metrics["metrics"]) == 1
        assert metrics["metrics"][0]["metric_name"] == "chat_latency_seconds"
        assert len(traces["traces"]) == 1
        assert traces["traces"][0]["span_name"] == "chat_turn"
        assert overview["chat_responsiveness"]["user_visible_latency_seconds"]["count"] == 1
        assert dashboards["dashboards"]

    def test_observability_routes_block_non_local_clients_without_inspection_token(self, isolated_api_state):
        from api.observability import get_observability_dashboard_definitions, list_observability_metrics

        with pytest.raises(HTTPException) as exc_info:
            list_observability_metrics(request=_request("/api/observability/metrics", host="10.0.0.8"))
        assert exc_info.value.status_code == 403

        with pytest.raises(HTTPException) as exc_info:
            get_observability_dashboard_definitions(_request("/api/observability/dashboard-definitions", host="10.0.0.8"))
        assert exc_info.value.status_code == 403
