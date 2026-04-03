from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage

from config import get_agent_runtime_limit
from tools.contracts import normalize_tool_output


@dataclass(frozen=True)
class ScopedAgentRunResult:
    response_text: str
    tool_trace: tuple[dict[str, Any], ...]

HelperAgentExposure = Literal["planner", "verifier"]


def filter_tools_by_exposure(tools: Iterable[Any], exposure: HelperAgentExposure) -> list[Any]:
    selected: list[Any] = []
    for tool in tools:
        manifest = getattr(tool, "manifest", None)
        if manifest is None:
            continue
        if exposure == "planner" and getattr(manifest, "planner_exposed", False):
            selected.append(tool)
        elif exposure == "verifier" and getattr(manifest, "verifier_exposed", False):
            selected.append(tool)
    return selected


def build_tool_catalog(tools: Iterable[Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for tool in tools:
        manifest = getattr(tool, "manifest", None)
        entry = {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", ""),
        }
        if manifest is not None:
            entry.update(
                {
                    "access_scope": getattr(manifest, "access_scope", None),
                    "read_only": getattr(manifest, "read_only", False),
                    "destructive": getattr(manifest, "destructive", False),
                    "concurrency_safe": getattr(manifest, "concurrency_safe", False),
                    "interrupt_behavior": getattr(manifest, "interrupt_behavior", None),
                    "tool_validates_input": getattr(manifest, "tool_validates_input", False),
                    "activity_summary_hint": getattr(manifest, "activity_summary_hint", None),
                    "result_summary_hint": getattr(manifest, "result_summary_hint", None),
                    "planner_exposed": getattr(manifest, "planner_exposed", False),
                    "verifier_exposed": getattr(manifest, "verifier_exposed", False),
                }
            )
        catalog.append(entry)
    return catalog


def extract_json_object(text: str) -> dict[str, Any]:
    import json
    import re

    stripped = text.strip()
    if not stripped:
        raise ValueError("Helper agent returned an empty response.")

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```json\s*(\{.*\})\s*```", stripped, flags=re.S)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        parsed = json.loads(stripped[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("Helper agent did not return a valid JSON object.")


def _coerce_chunk_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "".join(parts)
    return ""


async def run_scoped_agent(
    *,
    llm: Any,
    tools: list[Any],
    system_prompt: str,
    user_prompt: str,
    recursion_limit: int | None = None,
) -> ScopedAgentRunResult:
    agent = create_agent(llm, tools, system_prompt=system_prompt)
    response_chunks: list[str] = []
    tool_trace: list[dict[str, Any]] = []
    pending: dict[str, int] = {}
    resolved_recursion_limit = (
        max(25, recursion_limit)
        if recursion_limit is not None
        else get_agent_runtime_limit("helper_agent_recursion_limit", 1000)
    )

    async for event in agent.astream_events(
        {"messages": [HumanMessage(content=user_prompt)]},
        version="v2",
        config={"recursion_limit": resolved_recursion_limit},
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            text = _coerce_chunk_text(getattr(chunk, "content", ""))
            if text:
                response_chunks.append(text)
        elif kind == "on_tool_start":
            run_id = event["run_id"]
            raw_input = event["data"].get("input", {})
            if isinstance(raw_input, dict) and len(raw_input) == 1:
                tool_input = str(next(iter(raw_input.values())))
            else:
                tool_input = str(raw_input)
            pending[run_id] = len(tool_trace)
            tool_trace.append(
                {
                    "tool": event["name"],
                    "input": tool_input,
                    "run_id": run_id,
                }
            )
        elif kind == "on_tool_end":
            run_id = event["run_id"]
            raw_output = event["data"].get("output", "")
            result = normalize_tool_output(event["name"], raw_output)
            index = pending.pop(run_id, None)
            payload = {
                "tool": event["name"],
                "run_id": run_id,
                "output": result.summary,
                "result": result.model_dump(mode="json"),
            }
            if index is None:
                tool_trace.append(payload)
            else:
                tool_trace[index] = {
                    **tool_trace[index],
                    **payload,
                }

    return ScopedAgentRunResult(
        response_text="".join(response_chunks).strip(),
        tool_trace=tuple(tool_trace),
    )
