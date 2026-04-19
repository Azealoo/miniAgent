"""Multi-worker tests for ``SessionStore`` inter-process file locking.

The production deployment runs multiple uvicorn workers that may hit
``/api/chat`` for the same ``session_id`` concurrently. Before this lock
was in place, a read-modify-write race on the session JSON would cause
lost writes: Worker B reads the file before Worker A's append landed,
then overwrites A's blob with B's own stale-based append.

These tests spawn real OS processes (not just threads) so they exercise
the ``fcntl.flock``-based cross-process serialization rather than the
in-process ``asyncio.Lock`` fast path.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session_manager import SessionManager


# ``spawn`` gives each worker a fresh interpreter, which most closely
# matches the multi-uvicorn-worker deployment model and avoids fork-side
# surprises with an fcntl lock file descriptor inherited across fork.
_SPAWN_CTX = mp.get_context("spawn")


def _hammer_save(
    base_dir: str,
    session_id: str,
    worker_id: int,
    message_count: int,
    barrier: Barrier,
) -> None:
    """Entry point for worker processes — runs in a fresh interpreter."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from graph.session_manager import SessionManager  # noqa: WPS433

    sm = SessionManager(base_dir=Path(base_dir))
    barrier.wait()  # release all workers simultaneously to maximise contention
    for i in range(message_count):
        sm.save_message(
            session_id,
            "user",
            f"worker-{worker_id}-msg-{i}",
            request_id=f"worker-{worker_id}",
        )


class TestInterProcessSaveMessage:
    def test_concurrent_workers_do_not_lose_messages(self, tmp_path):
        sm = SessionManager(base_dir=tmp_path)
        session_id = sm.create_session()

        worker_count = 4
        per_worker = 25
        barrier = _SPAWN_CTX.Barrier(worker_count)

        procs = [
            _SPAWN_CTX.Process(
                target=_hammer_save,
                args=(str(tmp_path), session_id, worker_id, per_worker, barrier),
            )
            for worker_id in range(worker_count)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=60)
            assert p.exitcode == 0, (
                f"worker {p.pid} exited with code {p.exitcode} — "
                f"likely a lock deadlock or unhandled exception"
            )

        # Session JSON must be valid — atomic rename guarantees no torn file.
        session_path = tmp_path / "sessions" / f"{session_id}.json"
        raw = json.loads(session_path.read_text(encoding="utf-8"))

        messages = raw.get("messages", [])
        assert len(messages) == worker_count * per_worker, (
            f"lost messages under multi-worker save_message: "
            f"got {len(messages)}, expected {worker_count * per_worker}"
        )

        # Each worker's full sequence must be present, in order — the lock
        # does not guarantee global ordering across workers, but appends
        # from a single worker are issued sequentially and must land in
        # issue order.
        by_worker: dict[str, list[str]] = {}
        for msg in messages:
            by_worker.setdefault(msg["request_id"], []).append(msg["content"])

        for worker_id in range(worker_count):
            tag = f"worker-{worker_id}"
            assert by_worker.get(tag) == [
                f"worker-{worker_id}-msg-{i}" for i in range(per_worker)
            ], f"{tag} lost or reordered a message"

    def test_session_json_is_never_torn_for_readers(self, tmp_path):
        """A reader racing the writers must always see valid JSON.

        The atomic write-temp-then-``os.replace`` in ``_write`` means the
        reader's ``read_text`` returns either the pre-write or the
        post-write blob, never a truncated intermediate.
        """
        sm = SessionManager(base_dir=tmp_path)
        session_id = sm.create_session()

        worker_count = 3
        per_worker = 30
        barrier = _SPAWN_CTX.Barrier(worker_count)

        procs = [
            _SPAWN_CTX.Process(
                target=_hammer_save,
                args=(str(tmp_path), session_id, worker_id, per_worker, barrier),
            )
            for worker_id in range(worker_count)
        ]
        for p in procs:
            p.start()

        session_path = tmp_path / "sessions" / f"{session_id}.json"
        parse_failures = 0
        reads = 0
        # Poll the session file while writers are in-flight — every read
        # must parse as JSON.
        while any(p.is_alive() for p in procs):
            if session_path.exists():
                try:
                    json.loads(session_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    parse_failures += 1
                reads += 1

        for p in procs:
            p.join(timeout=30)
            assert p.exitcode == 0

        assert parse_failures == 0, (
            f"observed {parse_failures}/{reads} torn JSON reads — "
            f"atomic rename is not holding"
        )
