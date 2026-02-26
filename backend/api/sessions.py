"""
Session management endpoints.

GET    /api/sessions
POST   /api/sessions
PUT    /api/sessions/{id}
DELETE /api/sessions/{id}
GET    /api/sessions/{id}/messages   — full history including system prompt
GET    /api/sessions/{id}/history    — raw messages with tool_calls
POST   /api/sessions/{id}/generate-title
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from graph.session_manager import _validate_session_id

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
def list_sessions():
    return _sm().list_sessions()


@router.post("/sessions", status_code=201)
def create_session():
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
def rename_session(session_id: str, body: RenameRequest):
    _check_session_id(session_id)
    _sm().rename_session(session_id, body.title)
    return _sm().get_session_meta(session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    _check_session_id(session_id)
    _sm().delete_session(session_id)


# ------------------------------------------------------------------ #
# Messages                                                             #
# ------------------------------------------------------------------ #


@router.get("/sessions/{session_id}/messages")
def get_messages(session_id: str):
    """Returns full message list including a leading system prompt entry."""
    _check_session_id(session_id)
    from graph.agent import agent_manager
    from graph.prompt_builder import build_system_prompt
    from config import get_rag_mode

    system_prompt = build_system_prompt(agent_manager.base_dir, get_rag_mode())  # type: ignore[arg-type]
    messages = _sm().load_session(session_id)
    return [{"role": "system", "content": system_prompt}] + messages


@router.get("/sessions/{session_id}/history")
def get_history(session_id: str):
    """Returns raw stored messages (with tool_calls, without system prompt)."""
    _check_session_id(session_id)
    return _sm().load_session(session_id)


# ------------------------------------------------------------------ #
# Title generation                                                     #
# ------------------------------------------------------------------ #


@router.post("/sessions/{session_id}/generate-title")
async def generate_title(session_id: str):
    _check_session_id(session_id)
    from graph.agent import agent_manager
    from langchain_core.messages import HumanMessage, SystemMessage

    messages = _sm().load_session(session_id)
    if not messages:
        raise HTTPException(400, "Session has no messages")

    first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
    if not first_user:
        raise HTTPException(400, "No user messages found")

    try:
        resp = await agent_manager.llm.ainvoke(  # type: ignore[union-attr]
            [
                SystemMessage(
                    content="You generate concise chat titles. Reply with ONLY the title."
                ),
                HumanMessage(
                    content=(
                        f"Generate a short English title for a conversation that starts with: '{first_user[:200]}'. "
                        "Maximum 10 words. No punctuation, no quotes."
                    )
                ),
            ]
        )
        title = resp.content.strip()[:60]
    except Exception as exc:
        raise HTTPException(500, str(exc))

    _sm().rename_session(session_id, title)
    return {"session_id": session_id, "title": title}
