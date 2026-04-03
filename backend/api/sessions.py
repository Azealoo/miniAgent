"""
Session management endpoints.

GET    /api/sessions
GET    /api/sessions/{id}/files/summary
POST   /api/sessions
PUT    /api/sessions/{id}
DELETE /api/sessions/{id}
GET    /api/sessions/{id}/history    — raw messages with additive typed content blocks
GET    /api/sessions/{id}/continuity — compressed continuity summaries for older history
GET    /api/sessions/{id}/archives/{archive_id} — archived message batches for older history
POST   /api/sessions/{id}/generate-title
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from access_control import require_execution_access, require_inspection_access
from graph.session_manager import _validate_session_id
from runtime.title_generation import generate_chat_title

router = APIRouter()


def _sm():
    from graph.agent import agent_manager

    return agent_manager.session_manager


def _check_session_id(session_id: str) -> None:
    try:
        _validate_session_id(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id")


# ------------------------------------------------------------------ #
# Collection                                                           #
# ------------------------------------------------------------------ #


@router.get("/sessions")
def list_sessions(request: Request = None):
    require_inspection_access(request)
    return _sm().list_sessions()


@router.get("/sessions/{session_id}/files/summary")
def list_session_files_workspace_summary(session_id: str, request: Request = None):
    require_inspection_access(request)
    _check_session_id(session_id)
    from graph.agent import agent_manager
    from graph.files_workspace import list_session_files_workspace_items

    assert agent_manager.base_dir is not None
    return {
        "items": list_session_files_workspace_items(
            base_dir=agent_manager.base_dir,
            session_manager=_sm(),
            session_id=session_id,
        )
    }


@router.post("/sessions", status_code=201)
def create_session(request: Request = None):
    require_execution_access(request)
    session_id = _sm().create_session()
    return _sm().get_session_meta(session_id)


# ------------------------------------------------------------------ #
# Single session                                                       #
# ------------------------------------------------------------------ #


class RenameRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _check_title_length(cls, v: str) -> str:
        if len(v) > 200:
            raise ValueError("title too long (max 200 characters)")
        return v.strip() or "New Chat"


@router.put("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameRequest, request: Request = None):
    require_execution_access(request)
    _check_session_id(session_id)
    _sm().rename_session(session_id, body.title)
    return _sm().get_session_meta(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, request: Request = None):
    require_execution_access(request)
    _check_session_id(session_id)
    from graph.agent import agent_manager

    _sm().delete_session(session_id)
    agent_manager.clear_session_runtime(session_id)


# ------------------------------------------------------------------ #
# History                                                              #
# ------------------------------------------------------------------ #


@router.get("/sessions/{session_id}/history")
def get_history(session_id: str, request: Request = None):
    """Returns raw stored messages, including additive typed content blocks."""
    require_inspection_access(request)
    _check_session_id(session_id)
    return _sm().load_session(session_id)


@router.get("/sessions/{session_id}/continuity")
def get_session_continuity(session_id: str, request: Request = None):
    """Returns compact continuity summaries for compressed older history."""
    require_inspection_access(request)
    _check_session_id(session_id)
    return {"summaries": _sm().get_session_continuity(session_id)}


@router.get("/sessions/{session_id}/archives/{archive_id}")
def get_session_history_archive(
    session_id: str, archive_id: str, request: Request = None
):
    """Returns one archived batch of older messages for on-demand inspection."""
    require_inspection_access(request)
    _check_session_id(session_id)

    try:
        return _sm().load_archived_history(session_id, archive_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid archive_id")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Archive not found")


# ------------------------------------------------------------------ #
# Title generation                                                     #
# ------------------------------------------------------------------ #


@router.post("/sessions/{session_id}/generate-title")
async def generate_title(session_id: str, request: Request = None):
    require_execution_access(request)
    _check_session_id(session_id)
    from graph.agent import agent_manager

    messages = _sm().load_session(session_id)
    if not messages:
        raise HTTPException(400, "Session has no messages")

    first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
    if not first_user:
        raise HTTPException(400, "No user messages found")

    try:
        title = await generate_chat_title(agent_manager, first_user)
    except Exception as exc:
        raise HTTPException(500, str(exc))

    _sm().rename_session(session_id, title)
    return {"session_id": session_id, "title": title}
