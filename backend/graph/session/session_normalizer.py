"""Translate session messages between legacy shape and typed blocks."""

from typing import Any

from graph.session.session_schema import (
    SessionContentBlock, SessionPlanBlock, SessionRetrievalBlock,
    SessionTextBlock, SessionToolResultBlock, SessionToolUseBlock,
    SessionUsageBlock, SessionVerificationBlock, _tool_block_key,
)


def _normalize_record_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _build_blocks_from_legacy_message(
    role: str,
    content: str,
    tool_calls: list[dict[str, Any]],
    retrievals: list[dict[str, Any]],
) -> list[SessionContentBlock]:
    blocks: list[SessionContentBlock] = []

    if role == "assistant":
        if retrievals:
            blocks.append(
                SessionRetrievalBlock(
                    type="retrieval",
                    results=[dict(item) for item in retrievals],
                )
            )

        for call in tool_calls:
            tool_name = call.get("tool")
            if not isinstance(tool_name, str):
                continue

            use_block: SessionToolUseBlock = {
                "type": "tool_use",
                "tool": tool_name,
                "input": call.get("input") if isinstance(call.get("input"), str) else "",
            }
            run_id = call.get("run_id")
            if isinstance(run_id, str) and run_id:
                use_block["run_id"] = run_id
            blocks.append(use_block)

            result_block: SessionToolResultBlock = {
                "type": "tool_result",
                "tool": tool_name,
                "output": call.get("output") if isinstance(call.get("output"), str) else "",
            }
            if isinstance(run_id, str) and run_id:
                result_block["run_id"] = run_id
            if isinstance(call.get("result"), dict):
                result_block["result"] = dict(call["result"])
            blocks.append(result_block)

    if content:
        blocks.append(SessionTextBlock(type="text", text=content))

    return blocks


def _normalize_blocks(value: Any) -> list[SessionContentBlock]:
    if not isinstance(value, list):
        return []

    blocks: list[SessionContentBlock] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        block_type = item.get("type")
        if block_type == "text":
            text = item.get("text")
            if isinstance(text, str):
                blocks.append(SessionTextBlock(type="text", text=text))
        elif block_type == "tool_use":
            tool_name = item.get("tool")
            if not isinstance(tool_name, str):
                continue
            block: SessionToolUseBlock = {
                "type": "tool_use",
                "tool": tool_name,
                "input": item.get("input") if isinstance(item.get("input"), str) else "",
            }
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            blocks.append(block)
        elif block_type == "tool_result":
            tool_name = item.get("tool")
            if not isinstance(tool_name, str):
                continue
            block = SessionToolResultBlock(
                type="tool_result",
                tool=tool_name,
                output=item.get("output") if isinstance(item.get("output"), str) else "",
            )
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            result = item.get("result")
            if isinstance(result, dict):
                block["result"] = dict(result)
            blocks.append(block)
        elif block_type == "retrieval":
            results = item.get("results")
            if not isinstance(results, list):
                continue
            block = SessionRetrievalBlock(
                type="retrieval",
                results=[dict(entry) for entry in results if isinstance(entry, dict)],
            )
            query = item.get("query")
            if isinstance(query, str) and query:
                block["query"] = query
            blocks.append(block)
        elif block_type == "usage":
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                blocks.append(SessionUsageBlock(type="usage", metadata=dict(metadata)))
        elif block_type == "plan":
            event = item.get("event")
            summary = item.get("summary")
            plan = item.get("plan")
            if event not in {"created", "updated"}:
                continue
            if not isinstance(summary, str) or not isinstance(plan, dict):
                continue
            block: SessionPlanBlock = {
                "type": "plan",
                "event": event,
                "summary": summary,
                "plan": dict(plan),
            }
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            tool_trace = item.get("tool_trace")
            if isinstance(tool_trace, list):
                block["tool_trace"] = [
                    dict(entry) for entry in tool_trace if isinstance(entry, dict)
                ]
            blocks.append(block)
        elif block_type == "verification":
            summary = item.get("summary")
            verdict = item.get("verdict")
            verification = item.get("verification")
            if verdict not in {"pass", "repair_required", "fail"}:
                continue
            if not isinstance(summary, str) or not isinstance(verification, dict):
                continue
            block: SessionVerificationBlock = {
                "type": "verification",
                "summary": summary,
                "verdict": verdict,
                "verification": dict(verification),
            }
            run_id = item.get("run_id")
            if isinstance(run_id, str) and run_id:
                block["run_id"] = run_id
            tool_trace = item.get("tool_trace")
            if isinstance(tool_trace, list):
                block["tool_trace"] = [
                    dict(entry) for entry in tool_trace if isinstance(entry, dict)
                ]
            blocks.append(block)

    return blocks


def _derive_legacy_fields_from_blocks(
    blocks: list[SessionContentBlock],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    retrievals: list[dict[str, Any]] = []
    pending_tool_uses: dict[str, list[SessionToolUseBlock]] = {}

    for block in blocks:
        block_type = block["type"]

        if block_type == "text":
            text_parts.append(block["text"])
            continue

        if block_type == "tool_use":
            key = _tool_block_key(block["tool"], block.get("run_id"))
            pending_tool_uses.setdefault(key, []).append(block)
            continue

        if block_type == "tool_result":
            key = _tool_block_key(block["tool"], block.get("run_id"))
            pending = pending_tool_uses.get(key, [])
            started = pending.pop(0) if pending else None
            if not pending:
                pending_tool_uses.pop(key, None)

            call: dict[str, Any] = {
                "tool": block["tool"],
                "input": started.get("input", "") if started else "",
                "output": block.get("output", ""),
            }
            if isinstance(block.get("run_id"), str):
                call["run_id"] = block["run_id"]
            elif started and isinstance(started.get("run_id"), str):
                call["run_id"] = started["run_id"]
            if isinstance(block.get("result"), dict):
                call["result"] = dict(block["result"])
            tool_calls.append(call)
            continue

        if block_type == "retrieval":
            retrievals.extend(dict(item) for item in block["results"])
            continue

    return "".join(text_parts), tool_calls, retrievals


def _ensure_blocks(message: dict[str, Any]) -> tuple[dict[str, Any], list[SessionContentBlock]]:
    """Return a shallow-copied message with role/content normalized, plus its blocks.

    Falls back to building blocks from legacy ``tool_calls``/``retrievals`` if
    the message has no ``blocks`` field, so callers can treat blocks as canonical.
    """
    normalized = dict(message)
    role = normalized.get("role")
    normalized["role"] = role if isinstance(role, str) else "assistant"

    content_value = normalized.get("content")
    normalized["content"] = content_value if isinstance(content_value, str) else ""

    blocks = _normalize_blocks(normalized.get("blocks"))
    if not blocks:
        blocks = _build_blocks_from_legacy_message(
            normalized["role"],
            normalized["content"],
            _normalize_record_list(normalized.get("tool_calls")),
            _normalize_record_list(normalized.get("retrievals")),
        )
    return normalized, blocks


def _normalize_message(message: dict[str, Any]) -> dict[str, Any]:
    """Read-side normalization: derive legacy arrays from canonical blocks."""
    normalized, blocks = _ensure_blocks(message)

    if blocks:
        normalized["blocks"] = blocks
        derived_text, derived_tool_calls, derived_retrievals = (
            _derive_legacy_fields_from_blocks(blocks)
        )
        if not normalized["content"] and derived_text:
            normalized["content"] = derived_text
    else:
        normalized.pop("blocks", None)
        derived_tool_calls, derived_retrievals = [], []

    if derived_tool_calls:
        normalized["tool_calls"] = derived_tool_calls
    else:
        normalized.pop("tool_calls", None)

    if derived_retrievals:
        normalized["retrievals"] = derived_retrievals
    else:
        normalized.pop("retrievals", None)

    return normalized


def _normalize_message_for_storage(message: dict[str, Any]) -> dict[str, Any]:
    """Write-side normalization: keep blocks canonical, drop legacy arrays."""
    normalized, blocks = _ensure_blocks(message)
    if blocks:
        normalized["blocks"] = blocks
    else:
        normalized.pop("blocks", None)
    normalized.pop("tool_calls", None)
    normalized.pop("retrievals", None)
    return normalized


def _normalize_messages(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [_normalize_message(item) for item in messages if isinstance(item, dict)]


def _normalize_messages_for_storage(messages: Any) -> list[dict[str, Any]]:
    if not isinstance(messages, list):
        return []
    return [
        _normalize_message_for_storage(item) for item in messages if isinstance(item, dict)
    ]
