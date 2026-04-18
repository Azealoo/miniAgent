"""
Tests for the archive ``_index.json`` sidecar.

Covers sub-100 ms listing for ~10k synthetic entries, index self-heal on
missing/malformed sidecars, idempotent writes, and cleanup on
``delete_session``.
"""
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session.session_archive_index import (
    ARCHIVE_INDEX_FILENAME,
    ARCHIVE_INDEX_SCHEMA_VERSION,
    append_archive_entry,
    list_archive_entries,
    rebuild_index,
    remove_session_from_index,
)
from graph.session_manager import SessionManager


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _write_archive_file(archive_dir: Path, session_id: str, archive_id: str,
                        message_count: int) -> None:
    messages = [{"role": "user", "content": f"m{i}"} for i in range(message_count)]
    path = archive_dir / f"{session_id}_{archive_id}.json"
    path.write_text(json.dumps(messages), encoding="utf-8")


def _seed_synthetic_archive_index(archive_dir: Path, session_id: str,
                                   n: int) -> list[dict]:
    """Seed the sidecar directly with *n* synthetic archive entries.

    The archive files themselves are not created — the fast path only needs
    the sidecar. Tests that exercise rebuild paths create real files instead.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    entries = [
        {"archive_id": str(1_000_000_000_000 + i), "message_count": i % 16}
        for i in range(n)
    ]
    payload = {
        "schema_version": ARCHIVE_INDEX_SCHEMA_VERSION,
        "sessions": {session_id: entries},
    }
    (archive_dir / ARCHIVE_INDEX_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return entries


class TestArchiveIndexSidecar:
    def test_compress_history_creates_and_updates_sidecar(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")

        sm.compress_history(sid, "summary one", 4)

        sidecar = tmp_path / "sessions" / "archive" / ARCHIVE_INDEX_FILENAME
        assert sidecar.exists()
        payload = json.loads(sidecar.read_text())
        assert payload["schema_version"] == ARCHIVE_INDEX_SCHEMA_VERSION
        entries = payload["sessions"][sid]
        assert len(entries) == 1
        assert entries[0]["message_count"] == 4

        # A second compression appends, not overwrites.
        for i in range(6, 12):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        sm.compress_history(sid, "summary two", 4)

        payload = json.loads(sidecar.read_text())
        assert len(payload["sessions"][sid]) == 2

    def test_list_archived_batches_reads_from_sidecar_without_reading_files(
        self, sm, tmp_path
    ):
        sid = sm.create_session()
        # Need the session file to exist so list_archived_history_batches
        # does not early-return.
        assert (tmp_path / "sessions" / f"{sid}.json").exists()

        archive_dir = tmp_path / "sessions" / "archive"
        entries = _seed_synthetic_archive_index(archive_dir, sid, n=5)

        batches = sm.list_archived_history_batches(sid)
        assert [b["archive_id"] for b in batches] == [e["archive_id"] for e in entries]
        assert [b["message_count"] for b in batches] == [
            e["message_count"] for e in entries
        ]
        # No archive files were created on disk, proving the listing did not
        # fall back to the old glob+read path.
        assert not list(archive_dir.glob(f"{sid}_*.json"))

    def test_list_archived_batches_under_100ms_for_10k_entries(self, sm, tmp_path):
        sid = sm.create_session()
        archive_dir = tmp_path / "sessions" / "archive"
        _seed_synthetic_archive_index(archive_dir, sid, n=10_000)

        # Warm-up (filesystem cache, import costs).
        sm.list_archived_history_batches(sid)

        start = time.perf_counter()
        batches = sm.list_archived_history_batches(sid)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(batches) == 10_000
        assert elapsed_ms < 100, f"listing took {elapsed_ms:.1f}ms (>100ms budget)"

    def test_self_heal_when_sidecar_missing(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        sm.compress_history(sid, "summary", 4)

        archive_dir = tmp_path / "sessions" / "archive"
        sidecar = archive_dir / ARCHIVE_INDEX_FILENAME
        sidecar.unlink()

        batches = sm.list_archived_history_batches(sid)
        assert len(batches) == 1
        assert batches[0]["message_count"] == 4
        # Sidecar was rebuilt from disk.
        assert sidecar.exists()
        rebuilt = json.loads(sidecar.read_text())
        assert rebuilt["sessions"][sid][0]["message_count"] == 4

    def test_self_heal_when_sidecar_is_malformed(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        sm.compress_history(sid, "summary", 4)

        archive_dir = tmp_path / "sessions" / "archive"
        sidecar = archive_dir / ARCHIVE_INDEX_FILENAME
        sidecar.write_text("{not valid json", encoding="utf-8")

        batches = sm.list_archived_history_batches(sid)
        assert len(batches) == 1
        assert batches[0]["message_count"] == 4
        # Sidecar was overwritten with a valid rebuild.
        rebuilt = json.loads(sidecar.read_text())
        assert rebuilt["schema_version"] == ARCHIVE_INDEX_SCHEMA_VERSION
        assert rebuilt["sessions"][sid][0]["message_count"] == 4

    def test_self_heal_when_sidecar_schema_unknown(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        sm.compress_history(sid, "summary", 4)

        archive_dir = tmp_path / "sessions" / "archive"
        sidecar = archive_dir / ARCHIVE_INDEX_FILENAME
        # Missing "sessions" key — rejected by _normalize_loaded_index and
        # treated as corrupt, triggering a rebuild.
        sidecar.write_text(
            json.dumps({"schema_version": "unknown"}), encoding="utf-8"
        )

        batches = sm.list_archived_history_batches(sid)
        assert len(batches) == 1

    def test_delete_session_prunes_sidecar(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        sm.compress_history(sid, "summary", 4)

        sidecar = tmp_path / "sessions" / "archive" / ARCHIVE_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert sid in payload["sessions"]

        sm.delete_session(sid)

        payload = json.loads(sidecar.read_text())
        assert sid not in payload["sessions"]

    def test_rebuild_index_helper_writes_sidecar_from_scratch(self, tmp_path):
        archive_dir = tmp_path / "sessions" / "archive"
        archive_dir.mkdir(parents=True)

        sid_a = _new_session_id()
        sid_b = _new_session_id()
        _write_archive_file(archive_dir, sid_a, "1000", 3)
        _write_archive_file(archive_dir, sid_a, "2000", 5)
        _write_archive_file(archive_dir, sid_b, "3000", 7)

        rebuilt = rebuild_index(archive_dir)
        assert sorted(rebuilt.keys()) == sorted([sid_a, sid_b])
        assert [e["message_count"] for e in rebuilt[sid_a]] == [3, 5]
        assert rebuilt[sid_b][0]["message_count"] == 7

        sidecar = archive_dir / ARCHIVE_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert payload["schema_version"] == ARCHIVE_INDEX_SCHEMA_VERSION

    def test_rebuild_skips_the_index_file_itself_and_bad_filenames(self, tmp_path):
        archive_dir = tmp_path / "sessions" / "archive"
        archive_dir.mkdir(parents=True)

        sid = _new_session_id()
        _write_archive_file(archive_dir, sid, "9999", 2)
        # Stray files that should be ignored.
        (archive_dir / "stray.json").write_text("[]", encoding="utf-8")
        (archive_dir / "not-a-uuid_1.json").write_text("[]", encoding="utf-8")

        rebuilt = rebuild_index(archive_dir)
        assert list(rebuilt.keys()) == [sid]
        assert rebuilt[sid][0]["archive_id"] == "9999"

    def test_append_archive_entry_is_idempotent(self, tmp_path):
        archive_dir = tmp_path / "sessions" / "archive"
        archive_dir.mkdir(parents=True)
        sid = _new_session_id()

        append_archive_entry(archive_dir, sid, "100", 3)
        append_archive_entry(archive_dir, sid, "100", 7)  # same id, new count

        entries = list_archive_entries(archive_dir, sid)
        assert len(entries) == 1
        assert entries[0]["message_count"] == 7

    def test_remove_session_noop_when_sidecar_missing(self, tmp_path):
        archive_dir = tmp_path / "sessions" / "archive"
        archive_dir.mkdir(parents=True)
        # Must not raise even though the sidecar has never been created.
        remove_session_from_index(archive_dir, _new_session_id())
        assert not (archive_dir / ARCHIVE_INDEX_FILENAME).exists()

    def test_empty_archive_dir_does_not_create_sidecar_on_read(self, sm, tmp_path):
        sid = sm.create_session()
        batches = sm.list_archived_history_batches(sid)
        assert batches == []
        sidecar = tmp_path / "sessions" / "archive" / ARCHIVE_INDEX_FILENAME
        assert not sidecar.exists()
