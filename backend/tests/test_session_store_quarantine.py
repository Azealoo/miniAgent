"""Retention tests for ``SessionStore.prune_quarantine``.

Quarantined corrupt-session JSONs accumulate under
``backend/sessions/_quarantine/`` whenever ``_quarantine_corrupt_file``
runs. Without a retention pass the directory grows unbounded (issue #261).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session.session_store import (
    QUARANTINE_RETENTION_SECONDS,
    SessionStore,
)


VALID_SID = "11111111-2222-4333-8444-555555555555"


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path)


def _write_quarantined(store: SessionStore, ts: int, sid: str = VALID_SID) -> Path:
    store.quarantine_dir.mkdir(parents=True, exist_ok=True)
    path = store.quarantine_dir / f"{ts}_{sid}.json"
    path.write_text("{corrupt", encoding="utf-8")
    return path


class TestPruneQuarantine:
    def test_aged_file_is_deleted(self, store):
        # Write a quarantine entry whose filename timestamp is well past the
        # default 7-day retention window.
        aged_ts = int(time.time()) - QUARANTINE_RETENTION_SECONDS - 3600
        aged_path = _write_quarantined(store, aged_ts)

        removed = store.prune_quarantine()

        assert removed == 1
        assert not aged_path.exists()

    def test_fresh_file_is_kept(self, store):
        # A file inside the retention window must survive the pass.
        fresh_ts = int(time.time()) - 60
        fresh_path = _write_quarantined(store, fresh_ts)

        removed = store.prune_quarantine()

        assert removed == 0
        assert fresh_path.exists()

    def test_malformed_filename_is_ignored(self, store):
        # Filenames that don't parse as ``{ts}_{sid}.json`` are skipped — the
        # spec is "skip rather than guess", so even files that look very old
        # by mtime must be left alone if the name format is wrong.
        store.quarantine_dir.mkdir(parents=True, exist_ok=True)
        odd = store.quarantine_dir / "operator-notes.txt"
        odd.write_text("hand-written triage notes", encoding="utf-8")

        no_ts = store.quarantine_dir / f"corrupt_{VALID_SID}.json"
        no_ts.write_text("{corrupt", encoding="utf-8")

        bad_sid = store.quarantine_dir / "1700000000_not-a-uuid.json"
        bad_sid.write_text("{corrupt", encoding="utf-8")

        # Backdate mtime far past retention to prove mtime is not the trigger.
        old_mtime = time.time() - QUARANTINE_RETENTION_SECONDS - 86400
        for path in (odd, no_ts, bad_sid):
            import os

            os.utime(path, (old_mtime, old_mtime))

        removed = store.prune_quarantine()

        assert removed == 0
        assert odd.exists()
        assert no_ts.exists()
        assert bad_sid.exists()

    def test_mixed_directory_only_prunes_aged_matching_files(self, store):
        # Sanity check that the three rules compose: aged matching → deleted,
        # fresh matching → kept, malformed → ignored, regardless of age.
        aged_ts = int(time.time()) - QUARANTINE_RETENTION_SECONDS - 1
        fresh_ts = int(time.time()) - 60
        aged = _write_quarantined(store, aged_ts, sid=VALID_SID)
        fresh = _write_quarantined(
            store, fresh_ts, sid="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        )
        store.quarantine_dir.mkdir(parents=True, exist_ok=True)
        garbage = store.quarantine_dir / "garbage.json"
        garbage.write_text("{corrupt", encoding="utf-8")

        removed = store.prune_quarantine()

        assert removed == 1
        assert not aged.exists()
        assert fresh.exists()
        assert garbage.exists()

    def test_no_quarantine_dir_is_a_no_op(self, tmp_path):
        # Fresh SessionStore on an empty base_dir must not raise even though
        # the quarantine subdir has not been materialised.
        store = SessionStore(tmp_path)
        # Remove the quarantine dir if the opportunistic init accidentally
        # created it; ``prune_quarantine`` must still no-op cleanly.
        if store.quarantine_dir.exists():
            for child in store.quarantine_dir.iterdir():
                child.unlink()
            store.quarantine_dir.rmdir()

        assert store.prune_quarantine() == 0

    def test_custom_max_age_seconds(self, store):
        # Caller-provided window is honoured (used by the admin script's
        # ``--max-age-days`` flag).
        ts = int(time.time()) - 120
        path = _write_quarantined(store, ts)

        # 60s window: file is older than 60s, so it goes.
        removed = store.prune_quarantine(max_age_seconds=60)

        assert removed == 1
        assert not path.exists()


class TestOpportunisticInitPrune:
    def test_init_prunes_aged_quarantine_files(self, tmp_path):
        # Seed an aged quarantine file before constructing a fresh store, then
        # confirm the constructor's opportunistic prune picked it up.
        sessions_dir = tmp_path / "sessions"
        quarantine_dir = sessions_dir / "_quarantine"
        quarantine_dir.mkdir(parents=True)
        aged_ts = int(time.time()) - QUARANTINE_RETENTION_SECONDS - 1
        aged = quarantine_dir / f"{aged_ts}_{VALID_SID}.json"
        aged.write_text("{corrupt", encoding="utf-8")

        SessionStore(tmp_path)

        assert not aged.exists()
