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
POST   /api/sessions/{id}/end        — fire post-session distillation idempotently
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from access_control import require_execution_access, require_inspection_access
from graph.session_manager import SessionCorruptError, _validate_session_id
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


def _session_corrupt_response(exc: SessionCorruptError) -> HTTPException:
    """Translate a SessionCorruptError into a structured 422 response.

    Frontend matches on ``detail.error == 'session_corrupt'`` to surface a
    user-visible "session corrupt" notice instead of a generic failure.
    """
    return HTTPException(
        status_code=422,
        detail={
            "error": "session_corrupt",
            "session_id": exc.session_id,
            "quarantine_path": exc.quarantine_path,
            "message": (
                "The saved session file was corrupt and has been quarantined."
            ),
        },
    )


def _normalize_session_title(title: str) -> str:
    if len(title) > 200:
        raise ValueError("title too long (max 200 characters)")
    return title.strip() or "New Chat"


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
    # The route requires execution access, so the session is bound to the
    # ``execution`` tier. Recording it on the session JSON lets ``/api/chat``
    # cross-check session scope against per-turn requirements (issue #240).
    session_id = _sm().create_session(access_scope="execution")
    return _sm().get_session_meta(session_id)


# ------------------------------------------------------------------ #
# Single session                                                       #
# ------------------------------------------------------------------ #


class RenameRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def _check_title_length(cls, v: str) -> str:
        return _normalize_session_title(v)


@router.put("/sessions/{session_id}")
def rename_session(session_id: str, body: RenameRequest, request: Request = None):
    require_execution_access(request)
    _check_session_id(session_id)
    try:
        _sm().rename_session(session_id, body.title, raise_on_corrupt=True)
        return _sm().get_session_meta(session_id)
    except SessionCorruptError as exc:
        raise _session_corrupt_response(exc) from exc


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
    try:
        return _sm().load_session(session_id, raise_on_corrupt=True)
    except SessionCorruptError as exc:
        raise _session_corrupt_response(exc) from exc


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

    try:
        messages = _sm().load_session(session_id, raise_on_corrupt=True)
    except SessionCorruptError as exc:
        raise _session_corrupt_response(exc) from exc
    if not messages:
        raise HTTPException(400, "Session has no messages")

    first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
    if not first_user:
        raise HTTPException(400, "No user messages found")

    try:
        title = _normalize_session_title(
            await generate_chat_title(agent_manager, first_user)
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))

    try:
        _sm().rename_session(session_id, title, raise_on_corrupt=True)
    except SessionCorruptError as exc:
        raise _session_corrupt_response(exc) from exc
    return {"session_id": session_id, "title": title}


# ------------------------------------------------------------------ #
# Post-session distillation trigger                                    #
# ------------------------------------------------------------------ #


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, request: Request = None):
    """Idempotently fire the post-session distillation pipeline.

    Returns 202 when the distillation task is scheduled; returns 404 if the
    session id is unknown. The session file itself is left intact — callers
    that also want to delete the session should follow up with DELETE.
    """
    require_execution_access(request)
    _check_session_id(session_id)

    sm = _sm()
    if not sm._path(session_id).exists():
        raise HTTPException(status_code=404, detail="Session not found")

    from runtime.memory_distillation import fire_post_session_distillation

    fire_post_session_distillation(
        session_id,
        base_dir=sm.sessions_dir.parent,
        session_manager=sm,
    )
    return JSONResponse(
        status_code=202,
        content={"session_id": session_id, "status": "distillation_scheduled"},
    )
