from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from runtime.model_factory import invoke_with_escalation

_TITLE_SYSTEM_PROMPT = "You generate concise chat titles. Reply with ONLY the title."


def _build_title_request(first_message: str) -> str:
    return (
        "Generate a short English title for a conversation that starts with: "
        f"'{first_message[:200]}'. "
        "Maximum 10 words. No punctuation, no quotes."
    )


async def generate_chat_title(agent_manager: Any, first_message: str) -> str:
    title_llm = getattr(agent_manager, "title_llm", None) or agent_manager.llm
    if title_llm is None:
        raise RuntimeError("title model is not configured")

    messages = [
        SystemMessage(content=_TITLE_SYSTEM_PROMPT),
        HumanMessage(content=_build_title_request(first_message)),
    ]
    response = await invoke_with_escalation(
        "title",
        messages,
        model=title_llm,
        base_dir=getattr(agent_manager, "base_dir", None),
        streaming=False,
    )
    content = getattr(response, "content", "")
    if isinstance(content, list):
        content = "".join(str(part) for part in content)
    return str(content).strip()[:60]


async def try_generate_chat_title(agent_manager: Any, first_message: str) -> str:
    try:
        return await generate_chat_title(agent_manager, first_message)
    except Exception:
        return ""
