"""Turn-ledger persistence atomicity tests.

Covers the contract introduced by issue #223: a turn's user message and every
assistant segment must land in one advisory-flock scope so cross-process
readers never observe a partially-committed turn (user message on disk but no
assistant reply, or only the first of multiple segments persisted).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
import time
from multiprocessing.synchronize import Event as MPEvent
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session_manager import SessionManager
from runtime.turn_ledger import TurnLedger, TurnResult


_SPAWN_CTX = mp.get_context("spawn")


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


class TestSaveMessagesBatch:
    def test_single_call_persists_all_messages(self, sm):
        sid = sm.create_session()
        sm.save_messages_batch(
            sid,
            [
                {"role": "user", "content": "hi", "request_id": "r-1"},
                {
                    "role": "assistant",
                    "content": "hello",
                    "request_id": "r-1",
                    "blocks": [{"type": "text", "text": "hello"}],
                },
            ],
        )
        msgs = sm.load_session(sid)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert [m["content"] for m in msgs] == ["hi", "hello"]
        assert all(m["request_id"] == "r-1" for m in msgs)

    def test_empty_batch_is_noop(self, sm):
        sid = sm.create_session()
        sm.save_messages_batch(sid, [])
        assert sm.load_session(sid) == []

    def test_batch_writes_once_single_updated_at(self, sm):
        sid = sm.create_session()
        before = sm.get_session_meta(sid)["updated_at"]
        time.sleep(0.01)
        sm.save_messages_batch(
            sid,
            [
                {"role": "user", "content": "q"},
                {"role": "assistant", "content": "a1"},
                {"role": "assistant", "content": "a2"},
            ],
        )
        after = sm.get_session_meta(sid)["updated_at"]
        assert after > before
        assert sm.get_session_meta(sid)["message_count"] == 3


class TestTurnLedgerBatchPersistence:
    def test_persist_segments_writes_user_and_segments_in_one_call(self, sm):
        sid = sm.create_session()
        ledger = TurnLedger(
            session_manager=sm,
            session_id=sid,
            request_id="turn-1",
            user_message="hello agent",
        )
        ledger.consume({"type": "token", "content": "reply"})
        result = ledger.finalize(turn_status="ok")
        ledger.persist_segments(result)

        msgs = sm.load_session(sid)
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "hello agent"
        assert msgs[1]["content"] == "reply"
        assert all(m["request_id"] == "turn-1" for m in msgs)

    def test_persist_user_message_alone_is_a_noop(self, sm):
        """Mid-stream persist_user_message must NOT write; otherwise the
        turn is split across two advisory-flock scopes and cross-process
        readers can see a user-message-only state."""
        sid = sm.create_session()
        ledger = TurnLedger(
            session_manager=sm,
            session_id=sid,
            request_id="turn-2",
            user_message="buffered",
        )
        ledger.persist_user_message()
        assert sm.load_session(sid) == []

        ledger.persist_segments(
            TurnResult(segments=[], turn_status="ok", final_content="")
        )
        msgs = sm.load_session(sid)
        assert [m["role"] for m in msgs] == ["user"]
        assert msgs[0]["content"] == "buffered"

    def test_persist_segments_idempotent_on_user_message(self, sm):
        """Calling persist_segments twice (e.g. done+cancel racing) must not
        duplicate the user message."""
        sid = sm.create_session()
        ledger = TurnLedger(
            session_manager=sm,
            session_id=sid,
            request_id="turn-3",
            user_message="once",
        )
        ledger.consume({"type": "token", "content": "a"})
        first = ledger.finalize(turn_status="ok")
        ledger.persist_segments(first)

        # Second call simulates a redundant flush on a terminal event.
        ledger.persist_segments(
            TurnResult(segments=[], turn_status="ok", final_content="")
        )

        msgs = sm.load_session(sid)
        user_count = sum(1 for m in msgs if m["role"] == "user")
        assert user_count == 1

    def test_persist_without_session_manager_is_noop(self):
        ledger = TurnLedger()
        ledger.persist_user_message()
        ledger.persist_segments(
            TurnResult(segments=[], turn_status="ok", final_content="")
        )

    def test_persist_segments_does_not_duplicate_assistant_segments(self, sm):
        """Calling persist_segments twice with the same finalized result must
        not duplicate assistant records. This guards the ``finally``-based
        defensive finalization in stream_chat: if a generic exception fires
        after the done path already persisted, the redundant flush should be
        a no-op rather than appending the segments again.
        """
        sid = sm.create_session()
        ledger = TurnLedger(
            session_manager=sm,
            session_id=sid,
            request_id="turn-dup",
            user_message="ask",
        )
        ledger.consume({"type": "token", "content": "first"})
        ledger.consume({"type": "new_response"})
        ledger.consume({"type": "token", "content": "second"})
        first = ledger.finalize(turn_status="ok")
        ledger.persist_segments(first)

        # ``finalize`` does not clear ``_segments``; a second call returns the
        # same accumulated segments. Without idempotency this would duplicate.
        second = ledger.finalize(turn_status="error")
        ledger.persist_segments(second)

        msgs = sm.load_session(sid)
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "assistant"]
        assert [m["content"] for m in msgs] == ["ask", "first", "second"]

    def test_persist_segments_appends_only_new_segments(self, sm):
        """A streaming turn that calls persist_segments mid-flight (via the
        ``finally`` guard after partial output) and again on the terminal
        ``done`` event must persist each segment exactly once.
        """
        sid = sm.create_session()
        ledger = TurnLedger(
            session_manager=sm,
            session_id=sid,
            request_id="turn-incremental",
            user_message="streaming ask",
        )
        ledger.consume({"type": "token", "content": "partial"})
        partial = ledger.finalize(turn_status="error")
        ledger.persist_segments(partial)

        # Streaming continues after the defensive flush — a new segment is
        # appended and the terminal persist must only write the new one.
        ledger.consume({"type": "new_response"})
        ledger.consume({"type": "token", "content": "rest"})
        final = ledger.finalize(turn_status="ok")
        ledger.persist_segments(final)

        msgs = sm.load_session(sid)
        assert [m["role"] for m in msgs] == ["user", "assistant", "assistant"]
        assert [m["content"] for m in msgs] == ["streaming ask", "partial", "rest"]


# ──────────────────────────────────────────────────────────────────────────
# Cross-process atomicity: a reader polling the session JSON while a turn
# is persisting must only ever observe the pre-turn or post-turn state —
# never a user-message-only intermediate state.
# ──────────────────────────────────────────────────────────────────────────


def _run_turn_worker(
    base_dir: str,
    session_id: str,
    request_id: str,
    user_message: str,
    segments: list[tuple[str, str]],
    ready: MPEvent,
    release: MPEvent,
) -> None:
    """Build a TurnLedger and persist a turn under one batch flock."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from graph.session_manager import SessionManager  # noqa: WPS433
    from runtime.turn_ledger import (  # noqa: WPS433
        TurnLedger,
        TurnResult,
        TurnSegment,
    )

    sm = SessionManager(base_dir=Path(base_dir))
    ledger = TurnLedger(
        session_manager=sm,
        session_id=session_id,
        request_id=request_id,
        user_message=user_message,
    )
    turn_segments = [
        TurnSegment(content=content, blocks=[{"type": "text", "text": content}])
        for _, content in segments
    ]
    result = TurnResult(
        segments=turn_segments,
        turn_status="ok",
        final_content=" ".join(s.content for s in turn_segments),
    )

    ready.set()
    release.wait(timeout=10.0)
    ledger.persist_segments(result)


class TestTurnLedgerCrossProcessAtomicity:
    def test_reader_never_observes_partial_turn(self, tmp_path):
        """The sequence {no messages} → {user+assistants all present} must
        be the only observable transition. The intermediate
        ``user-only`` state (which the pre-fix code produced) must never
        appear in a polling reader's snapshots.
        """
        sm = SessionManager(base_dir=tmp_path)
        session_id = sm.create_session()

        ready = _SPAWN_CTX.Event()
        release = _SPAWN_CTX.Event()

        segments = [("s0", "first reply"), ("s1", "second reply")]
        writer = _SPAWN_CTX.Process(
            target=_run_turn_worker,
            args=(
                str(tmp_path),
                session_id,
                "turn-xproc",
                "user asks question",
                segments,
                ready,
                release,
            ),
        )
        writer.start()
        try:
            assert ready.wait(timeout=10.0), "writer process never signalled ready"

            session_path = tmp_path / "sessions" / f"{session_id}.json"
            observed_counts: set[int] = set()
            observed_role_orderings: set[tuple[str, ...]] = set()

            # Reader is a separate SessionManager instance in this process,
            # polling via the same atomic-rename-backed file read path used
            # by list_sessions, load_session, compaction, and archive.
            release.set()

            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(session_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    continue
                except json.JSONDecodeError:
                    pytest.fail("reader observed torn JSON — atomic rename broken")

                messages = raw.get("messages", [])
                observed_counts.add(len(messages))
                observed_role_orderings.add(tuple(m.get("role") for m in messages))

                if len(messages) == 1 + len(segments):
                    break

                if not writer.is_alive():
                    # Give the reader one more look after the writer exits so
                    # the final post-turn state is always in the set.
                    break

            writer.join(timeout=5.0)
            assert writer.exitcode == 0, (
                f"writer exited with {writer.exitcode} — likely a deadlock or "
                f"unhandled exception"
            )

            # Final state must be the complete post-turn message list.
            final = json.loads(session_path.read_text(encoding="utf-8"))
            final_roles = [m["role"] for m in final.get("messages", [])]
            assert final_roles == ["user", "assistant", "assistant"]

            # The reader must never have observed the user-message-only
            # intermediate state — that was the pre-fix bug.
            partial_user_only = ("user",)
            assert partial_user_only not in observed_role_orderings, (
                f"reader saw partial turn state {partial_user_only} — "
                f"expected atomic transition from () to "
                f"('user', 'assistant', 'assistant'); "
                f"observed orderings: {sorted(observed_role_orderings)}"
            )

            # Likewise a trailing-segment-missing state must never surface.
            partial_missing_last = ("user", "assistant")
            assert partial_missing_last not in observed_role_orderings, (
                f"reader saw partial turn state {partial_missing_last} — "
                f"segments must land atomically, not one at a time"
            )
        finally:
            if writer.is_alive():
                writer.terminate()
                writer.join(timeout=5.0)
