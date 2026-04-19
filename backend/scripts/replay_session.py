"""Deterministic session replay: re-run a recorded session through today's
chat runtime and diff the result.

Usage:
    python -m backend.scripts.replay_session <session_id>
    python -m backend.scripts.replay_session <session_id> --archive-dir PATH
    python -m backend.scripts.replay_session <session_id> --output-dir PATH
    python -m backend.scripts.replay_session <session_id> --allow-diff

Fixture = the persisted session JSON at ``<archive-dir>/<session_id>.json``.
Replay drives ``QueryEngine.stream_turn_sse`` in a sandbox tmpdir with
``agent_manager.astream`` stubbed to emit the internal event sequence
reconstructed from the recorded assistant blocks. LLM calls are never issued
live — provider APIs are not deterministic on seed alone.

Reports are written under ``<output-dir>/<session_id>/<timestamp>/``:
    recorded.normalized.json   -- recorded session with volatile fields stripped
    replayed.normalized.json   -- replayed session with the same normalization
    replayed.raw.json          -- replayed session as written to disk
    sse.jsonl                  -- one JSON line per SSE payload, per turn
    diff.json                  -- structural diff (empty list on match)
    summary.txt                -- human-readable summary

Exit 0 on match, 1 on diff, 2 on error. Use ``--allow-diff`` to always
exit 0 (useful during development).
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import datetime as _dt
import json
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Iterable
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
DEFAULT_ARCHIVE_DIR = BACKEND_ROOT / "sessions"
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "sessions" / "replays"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


# ---------------------------------------------------------------------------
# Event-stream reconstruction
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    user_message: str
    request_id: str | None
    # Each segment is the list of astream events that produced one assistant
    # message in the recorded session. Multi-segment turns replay one astream
    # call per segment (matching QueryEngine's repair-retry contract).
    segments: list[list[dict[str, Any]]]


def _group_turns(messages: list[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    current: Turn | None = None

    for msg in messages:
        role = msg.get("role")
        if role == "user":
            current = Turn(
                user_message=msg.get("content", ""),
                request_id=msg.get("request_id"),
                segments=[],
            )
            turns.append(current)
            continue

        if role == "assistant":
            if current is None:
                # Assistant message without a preceding user message: start a
                # synthetic turn so we don't silently drop it.
                current = Turn(user_message="", request_id=msg.get("request_id"), segments=[])
                turns.append(current)
            current.segments.append(_events_for_segment(msg))

    return turns


def _events_for_segment(assistant_msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a recorded assistant message's blocks back to astream events.

    Plan and verification blocks are skipped because QueryEngine re-derives
    those events from the preceding plan_agent / verification_agent tool_end
    events; emitting them again would double-persist.
    """
    events: list[dict[str, Any]] = []
    pending_tool_starts: dict[str, dict[str, Any]] = {}

    for block in assistant_msg.get("blocks") or []:
        btype = block.get("type")

        if btype == "retrieval":
            events.append(
                {
                    "type": "retrieval",
                    "query": block.get("query", ""),
                    "results": [dict(r) for r in block.get("results") or []],
                }
            )

        elif btype == "text":
            text = block.get("text") or ""
            if text:
                events.append({"type": "token", "content": text})

        elif btype == "tool_use":
            tool = block.get("tool")
            run_id = block.get("run_id") or tool
            start = {
                "type": "tool_start",
                "tool": tool,
                "input": block.get("input", ""),
                "run_id": run_id,
            }
            events.append(start)
            pending_tool_starts[run_id] = start

        elif btype == "tool_result":
            tool = block.get("tool")
            run_id = block.get("run_id") or tool
            pending_tool_starts.pop(run_id, None)
            end: dict[str, Any] = {
                "type": "tool_end",
                "tool": tool,
                "output": block.get("output", ""),
                "run_id": run_id,
            }
            if isinstance(block.get("result"), dict):
                end["result"] = copy.deepcopy(block["result"])
            events.append(end)

        # plan / verification / usage blocks: derived, skip.

    events.append({"type": "done", "turn_status": "ok"})
    return events


# ---------------------------------------------------------------------------
# Replay driver
# ---------------------------------------------------------------------------


class _SegmentQueue:
    """Hands out the next recorded segment's events on each astream call."""

    def __init__(self, segments: Iterable[list[dict[str, Any]]]):
        self._queue: list[list[dict[str, Any]]] = [list(seg) for seg in segments]

    async def astream(
        self, _message: str, _history: list[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        if not self._queue:
            # Repair retry the recording didn't capture: emit an empty done so
            # QueryEngine terminates cleanly rather than hanging.
            yield {"type": "done", "turn_status": "ok"}
            return
        events = self._queue.pop(0)
        for ev in events:
            yield ev

    def drained(self) -> bool:
        return not self._queue


async def _replay_turn(
    agent_manager: Any,
    session_id: str,
    user_message: str,
    segments: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    from runtime.query_engine import QueryEngine

    queue = _SegmentQueue(segments)
    engine = QueryEngine(agent_manager)

    with patch.object(agent_manager, "astream", queue.astream):
        sse_payloads: list[dict[str, Any]] = []
        async for chunk in engine.stream_turn_sse(message=user_message, session_id=session_id):
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    sse_payloads.append(json.loads(line[6:]))
    return sse_payloads


async def _replay_all(session_id: str, turns: list[Turn], sandbox: Path) -> dict[str, Any]:
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_llm = agent_manager.llm
    original_memory_indexer = agent_manager.memory_indexer

    agent_manager.base_dir = sandbox
    agent_manager.session_manager = SessionManager(base_dir=sandbox)
    agent_manager.llm = MagicMock()
    agent_manager.memory_indexer = None

    sandbox_session_path = sandbox / "sessions" / f"{session_id}.json"
    sandbox_session_path.parent.mkdir(parents=True, exist_ok=True)
    # Seed an empty session file so the id is stable across the replay.
    sandbox_session_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "title": "replay",
                "created_at": 0.0,
                "updated_at": 0.0,
                "compressed_context": "",
                "compressed_archive_index": [],
                "messages": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    async def _noop_compress(*_args, **_kwargs):
        return False

    async def _noop_compact(*_args, **_kwargs):
        return None

    sse_per_turn: list[list[dict[str, Any]]] = []
    try:
        with patch.object(
            agent_manager.session_manager,
            "auto_compress_if_needed",
            _noop_compress,
        ), patch(
            "runtime.compaction.maybe_compact_turn_boundary",
            _noop_compact,
        ):
            for turn in turns:
                payloads = await _replay_turn(
                    agent_manager,
                    session_id,
                    turn.user_message,
                    turn.segments,
                )
                sse_per_turn.append(payloads)

        replayed = json.loads(sandbox_session_path.read_text(encoding="utf-8"))
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.llm = original_llm
        agent_manager.memory_indexer = original_memory_indexer

    return {"replayed_session": replayed, "sse_per_turn": sse_per_turn}


# ---------------------------------------------------------------------------
# Normalization + diff
# ---------------------------------------------------------------------------


_VOLATILE_TOP_LEVEL = {
    "created_at",
    "updated_at",
    "deterministic",
    "schema_version",
    "title",
    # ``runtime_config`` carries the per-turn config-freeze timestamp stamped
    # by the query engine. It is non-deterministic by design (wall-clock) and
    # not part of the user-visible session content, so it must be ignored
    # when diffing a replay against the recorded session.
    "runtime_config",
}


def _ordinalize(value: str, table: dict[str, str], prefix: str) -> str:
    if value not in table:
        table[value] = f"{prefix}-{len(table)}"
    return table[value]


def _normalize_blocks(blocks: list[dict[str, Any]], run_id_table: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        b = copy.deepcopy(block)
        if isinstance(b.get("run_id"), str):
            b["run_id"] = _ordinalize(b["run_id"], run_id_table, "run")
        if isinstance(b.get("result"), dict):
            b["result"] = b["result"]
        out.append(b)
    return out


def _normalize_session(session: dict[str, Any]) -> dict[str, Any]:
    norm: dict[str, Any] = {
        k: v for k, v in session.items() if k not in _VOLATILE_TOP_LEVEL
    }
    messages = norm.get("messages") or []
    req_table: dict[str, str] = {}
    run_id_table: dict[str, str] = {}
    normalized_messages: list[dict[str, Any]] = []
    for msg in messages:
        m = copy.deepcopy(msg)
        if isinstance(m.get("request_id"), str):
            m["request_id"] = _ordinalize(m["request_id"], req_table, "req")
        if isinstance(m.get("blocks"), list):
            m["blocks"] = _normalize_blocks(m["blocks"], run_id_table)
        if isinstance(m.get("tool_calls"), list):
            for call in m["tool_calls"]:
                if isinstance(call, dict) and isinstance(call.get("run_id"), str):
                    call["run_id"] = _ordinalize(call["run_id"], run_id_table, "run")
        normalized_messages.append(m)
    norm["messages"] = normalized_messages
    return norm


def _diff(recorded: Any, replayed: Any, path: str = "") -> list[dict[str, Any]]:
    if type(recorded) is not type(replayed):
        return [{"path": path or "/", "kind": "type", "recorded": recorded, "replayed": replayed}]
    if isinstance(recorded, dict):
        diffs: list[dict[str, Any]] = []
        keys = sorted(set(recorded) | set(replayed))
        for key in keys:
            sub = f"{path}/{key}"
            if key not in recorded:
                diffs.append({"path": sub, "kind": "added_in_replay", "replayed": replayed[key]})
            elif key not in replayed:
                diffs.append({"path": sub, "kind": "missing_in_replay", "recorded": recorded[key]})
            else:
                diffs.extend(_diff(recorded[key], replayed[key], sub))
        return diffs
    if isinstance(recorded, list):
        diffs = []
        if len(recorded) != len(replayed):
            diffs.append(
                {
                    "path": path or "/",
                    "kind": "length",
                    "recorded_len": len(recorded),
                    "replayed_len": len(replayed),
                }
            )
        for idx, (a, b) in enumerate(zip(recorded, replayed)):
            diffs.extend(_diff(a, b, f"{path}[{idx}]"))
        return diffs
    if recorded != replayed:
        return [{"path": path or "/", "kind": "value", "recorded": recorded, "replayed": replayed}]
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_outputs(
    out_dir: Path,
    recorded_norm: dict[str, Any],
    replayed_norm: dict[str, Any],
    replayed_raw: dict[str, Any],
    sse_per_turn: list[list[dict[str, Any]]],
    diff: list[dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recorded.normalized.json").write_text(
        json.dumps(recorded_norm, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "replayed.normalized.json").write_text(
        json.dumps(replayed_norm, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "replayed.raw.json").write_text(
        json.dumps(replayed_raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (out_dir / "sse.jsonl").open("w", encoding="utf-8") as fh:
        for turn_idx, payloads in enumerate(sse_per_turn):
            for payload in payloads:
                fh.write(json.dumps({"turn": turn_idx, **payload}, ensure_ascii=False) + "\n")
    (out_dir / "diff.json").write_text(
        json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _summary(
    session_id: str,
    turns: list[Turn],
    diff: list[dict[str, Any]],
    out_dir: Path,
) -> str:
    lines = [
        f"Session: {session_id}",
        f"Turns replayed: {len(turns)}",
        f"Segments replayed: {sum(len(t.segments) for t in turns)}",
        f"Diffs: {len(diff)}",
        f"Report: {out_dir}",
    ]
    if diff:
        lines.append("")
        lines.append("First differences:")
        for entry in diff[:5]:
            lines.append(f"  - {entry.get('kind')} at {entry.get('path')}")
    return "\n".join(lines)


async def _main_async(args: argparse.Namespace) -> int:
    archive_dir = Path(args.archive_dir).resolve()
    session_path = archive_dir / f"{args.session_id}.json"
    if not session_path.exists():
        print(f"error: session file not found: {session_path}", file=sys.stderr)
        return 2

    recorded = json.loads(session_path.read_text(encoding="utf-8"))
    if isinstance(recorded, list):
        # v1 on-disk shape — wrap so _group_turns can consume it.
        recorded = {"messages": recorded}

    # Normalize messages through the session reader so legacy records get
    # canonical blocks before we try to reconstruct events.
    from graph.session.session_normalizer import _normalize_messages

    messages = _normalize_messages(recorded.get("messages") or [])
    turns = _group_turns(messages)
    if not turns:
        print("error: recorded session has no turns to replay", file=sys.stderr)
        return 2

    timestamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.output_dir).resolve() / args.session_id / timestamp

    with tempfile.TemporaryDirectory(prefix="replay-") as tmp:
        sandbox = Path(tmp)
        (sandbox / "artifacts").mkdir(parents=True, exist_ok=True)
        (sandbox / "memory").mkdir(parents=True, exist_ok=True)
        result = await _replay_all(args.session_id, turns, sandbox)

    replayed_messages = _normalize_messages(result["replayed_session"].get("messages") or [])
    recorded_norm = _normalize_session(
        {"messages": messages, **{k: v for k, v in recorded.items() if k != "messages"}}
    )
    replayed_norm = _normalize_session(
        {"messages": replayed_messages, **{k: v for k, v in result["replayed_session"].items() if k != "messages"}}
    )
    diff = _diff(recorded_norm, replayed_norm)

    _write_outputs(
        out_dir,
        recorded_norm,
        replayed_norm,
        result["replayed_session"],
        result["sse_per_turn"],
        diff,
    )

    print(_summary(args.session_id, turns, diff, out_dir))

    if diff and not args.allow_diff:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.replay_session",
        description="Deterministically replay a recorded session and diff it against live code.",
    )
    parser.add_argument("session_id", help="Session id to replay (matches <archive-dir>/<id>.json)")
    parser.add_argument(
        "--archive-dir",
        default=str(DEFAULT_ARCHIVE_DIR),
        help=f"Directory holding <session_id>.json (default: {DEFAULT_ARCHIVE_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Root directory for replay reports (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--allow-diff",
        action="store_true",
        help="Exit 0 even when a diff is detected (report is still written).",
    )
    args = parser.parse_args(argv)

    try:
        return asyncio.run(_main_async(args))
    except Exception:
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
