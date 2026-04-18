"""
Minimal backend surface checks for the chat-engine-only backend.

These tests intentionally cover only the routes and modules we still expose:
chat bootstrap, access probing, session management, and workspace file access.
"""
from __future__ import annotations

import builtins
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
import pytest
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
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)

    (tmp_path / "workspace").mkdir(exist_ok=True)
    (tmp_path / "memory").mkdir(exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager


def test_health_returns_ok():
    import app

    resp = app.health()
    assert resp["status"] == "ok"
    assert resp["service"] == "BioAPEX"


def test_app_import_keeps_chat_engine_surface_lightweight():
    sys.modules.pop("app", None)
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        banned = {
            "api.artifact_registry",
            "api.audit",
            "api.compress",
            "api.config_api",
            "api.connectors",
            "api.observability",
            "api.skills_registry",
            "api.studies",
            "compliance",
            "compliance.audit",
            "observability",
            "observability.store",
        }
        if name in banned:
            raise AssertionError(f"{name} should not be imported by the chat-engine app")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=guarded_import):
        app_module = importlib.import_module("app")

    assert app_module.health()["status"] == "ok"


def test_runtime_tool_catalog_excludes_legacy_workflow_tools():
    from tools import get_all_tools

    tool_names = {tool.name for tool in get_all_tools(Path(__file__).parent.parent)}

    assert "claim_graph" not in tool_names
    assert "slurm_tool" not in tool_names


def test_access_probe_reports_loopback_grant_mode(isolated_api_state):
    from api.access import probe_route_access

    response = probe_route_access("inspection", _request("/api/access/probe?scope=inspection"))

    assert response == {
        "scope": "inspection",
        "authorization_mode": "loopback",
    }


def test_access_probe_blocks_non_local_clients_without_token(isolated_api_state):
    from api.access import probe_route_access

    with pytest.raises(HTTPException) as exc_info:
        probe_route_access(
            "execution",
            _request("/api/access/probe?scope=execution", host="10.0.0.8"),
        )

    assert exc_info.value.status_code == 403


def test_sessions_create_and_list_round_trip(isolated_api_state):
    from api.sessions import create_session, list_sessions

    created = create_session()
    listed_ids = {session["id"] for session in list_sessions()}

    assert created["id"] in listed_ids
    assert created["title"] == "New Chat"


@pytest.mark.asyncio
async def test_generate_title_renames_session_from_first_user_message(isolated_api_state):
    from api.sessions import generate_title
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    agent_manager.session_manager.save_message(session_id, "user", "Plan a CRISPR screen")

    original_title_llm = agent_manager.title_llm
    try:
        agent_manager.title_llm = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=SimpleNamespace(content="CRISPR Screen Plan")
            )
        )
        result = await generate_title(session_id)
    finally:
        agent_manager.title_llm = original_title_llm

    assert result == {
        "session_id": session_id,
        "title": "CRISPR Screen Plan",
    }
    assert (
        agent_manager.session_manager.get_session_meta(session_id)["title"]
        == "CRISPR Screen Plan"
    )


@pytest.mark.asyncio
async def test_generate_title_normalizes_blank_model_output(isolated_api_state):
    from api.sessions import generate_title
    from graph.agent import agent_manager

    session_id = agent_manager.session_manager.create_session()
    agent_manager.session_manager.save_message(session_id, "user", "Plan a CRISPR screen")

    original_title_llm = agent_manager.title_llm
    try:
        agent_manager.title_llm = SimpleNamespace(
            ainvoke=AsyncMock(return_value=SimpleNamespace(content="   "))
        )
        result = await generate_title(session_id)
    finally:
        agent_manager.title_llm = original_title_llm

    assert result == {
        "session_id": session_id,
        "title": "New Chat",
    }
    assert agent_manager.session_manager.get_session_meta(session_id)["title"] == "New Chat"


def test_files_read_file_blocks_missing_path(isolated_api_state):
    from api.files import read_file

    with pytest.raises(HTTPException) as exc_info:
        read_file("../../outside.txt")

    assert exc_info.value.status_code == 403


def test_session_tokens_includes_usage_breakdown(isolated_api_state):
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
    assert result["tokenizer_backend"] == "tiktoken_cl100k_base"
    assert result["tokenizer_accuracy"] == "model_aligned"


def test_session_tokens_fall_back_when_exact_tokenizer_is_unavailable(isolated_api_state):
    import api.tokens as tokens_api
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

    tokens_api._get_tokenizer_runtime.cache_clear()
    try:
        with patch("api.tokens.importlib.import_module", side_effect=RuntimeError("offline")):
            result = tokens_api.session_tokens(session_id)
            expected_user_tokens = tokens_api._count("Plan a CRISPR screen")
            expected_assistant_tokens = tokens_api._count(
                "I found the latest workflow artifacts."
            )
            expected_tool_tokens = (
                tokens_api._count("artifacts/rnaseq-qc/run.json")
                + tokens_api._count("{\"status\":\"completed\"}")
            )
    finally:
        tokens_api._get_tokenizer_runtime.cache_clear()

    assert result["message_tokens"] == expected_user_tokens + expected_assistant_tokens
    assert result["input_tokens"] == result["system_tokens"] + expected_user_tokens
    assert result["output_tokens"] == expected_assistant_tokens
    assert result["tool_tokens"] == expected_tool_tokens
    assert result["tracked_total_tokens"] == (
        result["input_tokens"] + result["output_tokens"] + result["tool_tokens"]
    )
    assert result["tokenizer_backend"] == "deterministic_fallback"
    assert result["tokenizer_accuracy"] == "approximate"


def test_files_tokens_counts_allowed_file(isolated_api_state):
    from api.tokens import FilesTokenRequest, files_tokens

    result = files_tokens(FilesTokenRequest(paths=["memory/MEMORY.md"]))

    assert result[0]["path"] == "memory/MEMORY.md"
    assert result[0]["tokens"] > 0


def test_skills_list_uses_runtime_registry_instead_of_snapshot(isolated_api_state):
    from api.files import list_skills

    skill_dir = isolated_api_state / "skills" / "demo_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        (
            "---\n"
            "name: demo_skill\n"
            "description: demo\n"
            "category: bio/literature\n"
            "requires_tools: [read_file]\n"
            "requires_network: false\n"
            "user_invocable: true\n"
            "species: any\n"
            "modality: literature\n"
            "stage: analysis\n"
            "stability: experimental\n"
            "safety_level: low\n"
            "---\n"
            "# Body\n"
        ),
        encoding="utf-8",
    )
    (isolated_api_state / "SKILLS_SNAPSHOT.md").write_text(
        "<available_skills><skill><name>stale_skill</name></skill></available_skills>",
        encoding="utf-8",
    )

    skills = list_skills(_request("/api/skills"))

    assert [skill["name"] for skill in skills] == ["demo_skill"]


def test_skills_registry_keeps_full_runtime_state_while_skills_list_stays_active_only(
    isolated_api_state,
):
    from api.files import list_skills, list_skills_registry

    def _write_skill(name: str, *, include_hints: bool = False) -> None:
        skill_dir = isolated_api_state / "skills" / name
        skill_dir.mkdir(parents=True)
        hint_block = ""
        if include_hints:
            hint_block = "paths:\n  - backend/runtime/**\n  - memory/project/**\neffort: medium\n"
        (skill_dir / "SKILL.md").write_text(
            (
                f"---\nname: {name}\ndescription: demo\ncategory: bio/literature\n"
                f"{hint_block}"
                "requires_tools: [read_file]\n"
                "requires_network: false\n"
                "user_invocable: true\n"
                "species: any\n"
                "modality: literature\n"
                "stage: analysis\n"
                "stability: experimental\n"
                "safety_level: low\n"
                "---\n# Body\n"
            ),
            encoding="utf-8",
        )

    _write_skill("active_skill", include_hints=True)
    _write_skill("disabled_skill")
    cfg_file = isolated_api_state / "backend-config.json"
    cfg_file.write_text(
        json.dumps({"skills": {"entries": {"disabled_skill": {"enabled": False}}}}),
        encoding="utf-8",
    )

    with patch("config._CONFIG_FILE", cfg_file):
        active_skills = list_skills(_request("/api/skills"))
        registry = list_skills_registry(_request("/api/skills/registry"))

    assert active_skills == [
        {
            "name": "active_skill",
            "path": "skills/active_skill/SKILL.md",
            "category": "bio/literature",
            "stage": "analysis",
        }
    ]

    active_entry = next(entry for entry in registry if entry["name"] == "active_skill")
    disabled_entry = next(entry for entry in registry if entry["name"] == "disabled_skill")

    assert active_entry["selected"] is True
    assert active_entry["selection_reason"] == "selected"
    assert active_entry["location"] == "skills/active_skill/SKILL.md"
    assert active_entry["paths"] == ["backend/runtime/**", "memory/project/**"]
    assert active_entry["effort"] == "medium"
    assert disabled_entry["enabled"] is False
    assert disabled_entry["selected"] is False
    assert disabled_entry["selection_reason"] == "disabled_by_config"


# --------------------------------------------------------------------- #
# POST /api/sessions/{id}/end + GET /api/debug/failed-distillations    #
# --------------------------------------------------------------------- #


def test_post_session_end_returns_202_and_triggers_distillation(isolated_api_state):
    from api.sessions import end_session
    from graph.agent import agent_manager
    from runtime.memory_distillation import clear_failed_distillations

    clear_failed_distillations()
    session_id = agent_manager.session_manager.create_session()
    agent_manager.session_manager.save_message(
        session_id, "user", "Kick off the QC pass.", request_id="req-end-1"
    )

    response = end_session(session_id, _request(f"/api/sessions/{session_id}/end", method="POST"))

    assert response.status_code == 202
    # Session still exists (end does not delete it).
    assert (isolated_api_state / "sessions" / f"{session_id}.json").exists()
    # Distillation ran synchronously because the test has no running loop.
    distillation_path = (
        isolated_api_state / "memory" / "agent" / f"session-{session_id}.md"
    )
    assert distillation_path.exists()
    content = distillation_path.read_text(encoding="utf-8")
    assert "type: session_distillation" in content
    assert "## Turn req-end-1" in content


def test_post_session_end_returns_404_for_unknown_session(isolated_api_state):
    from api.sessions import end_session

    unknown_id = "00000000-0000-4000-8000-000000000099"
    with pytest.raises(HTTPException) as exc_info:
        end_session(unknown_id, _request(f"/api/sessions/{unknown_id}/end", method="POST"))
    assert exc_info.value.status_code == 404


def test_debug_failed_distillations_exposes_recorded_failures(isolated_api_state):
    from api.debug import list_failed_distillations
    from runtime.memory_distillation import (
        clear_failed_distillations,
        record_failed_distillation,
    )

    clear_failed_distillations()
    result = list_failed_distillations(_request("/api/debug/failed-distillations"))
    assert result == {"session_ids": [], "count": 0}

    record_failed_distillation("00000000-0000-4000-8000-000000000042")
    record_failed_distillation("00000000-0000-4000-8000-000000000017")

    result = list_failed_distillations(_request("/api/debug/failed-distillations"))
    assert result["count"] == 2
    assert result["session_ids"] == [
        "00000000-0000-4000-8000-000000000017",
        "00000000-0000-4000-8000-000000000042",
    ]
    clear_failed_distillations()
