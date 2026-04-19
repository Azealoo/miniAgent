"""
Tests for the sessions ``_index.json`` sidecar.

Covers write-path updates (create / save / rename / delete), self-heal on
missing / malformed / schema-mismatched sidecars, and a sub-100 ms listing
budget for 10k synthetic entries.
"""
import concurrent.futures
import json
import sys
import time
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session.session_index import (
    SESSION_INDEX_FILENAME,
    SESSION_INDEX_SCHEMA_VERSION,
    rebuild_index,
    remove_session_from_index,
    upsert_session_entry,
)
from graph.session_manager import SessionManager


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


def _new_session_id() -> str:
    return str(uuid.uuid4())


def _seed_synthetic_sessions_index(sessions_dir: Path, n: int) -> list[str]:
    """Seed the sidecar with *n* synthetic session entries (+ stub files).

    Stub session files are created alongside the sidecar because ``_load_index``
    revalidates entries against on-disk files. The stubs are empty — if the
    listing fell back to reading each file, titles/counts would be wrong.
    """
    sessions_dir.mkdir(parents=True, exist_ok=True)
    ids = [_new_session_id() for _ in range(n)]
    entries = {
        sid: {
            "title": f"Session {i}",
            "updated_at": float(1_700_000_000 + i),
            "message_count": i % 17,
        }
        for i, sid in enumerate(ids)
    }
    payload = {
        "schema_version": SESSION_INDEX_SCHEMA_VERSION,
        "sessions": entries,
    }
    (sessions_dir / SESSION_INDEX_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    for sid in ids:
        (sessions_dir / f"{sid}.json").touch()
    return ids


class TestSessionIndexSidecar:
    def test_create_session_populates_sidecar(self, sm, tmp_path):
        sid = sm.create_session()

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        assert sidecar.exists()
        payload = json.loads(sidecar.read_text())
        assert payload["schema_version"] == SESSION_INDEX_SCHEMA_VERSION
        assert sid in payload["sessions"]
        assert payload["sessions"][sid]["message_count"] == 0

    def test_save_message_updates_sidecar_message_count(self, sm, tmp_path):
        sid = sm.create_session()
        sm.save_message(sid, "user", "hello")
        sm.save_message(sid, "assistant", "hi")

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert payload["sessions"][sid]["message_count"] == 2

    def test_rename_session_updates_sidecar_title(self, sm, tmp_path):
        sid = sm.create_session()
        sm.rename_session(sid, "Renamed session")

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert payload["sessions"][sid]["title"] == "Renamed session"

    def test_delete_session_prunes_sidecar(self, sm, tmp_path):
        sid_a = sm.create_session()
        sid_b = sm.create_session()

        sm.delete_session(sid_a)

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert sid_a not in payload["sessions"]
        assert sid_b in payload["sessions"]

    def test_list_sessions_reads_from_sidecar_without_reading_files(
        self, sm, tmp_path
    ):
        sessions_dir = tmp_path / "sessions"
        ids = _seed_synthetic_sessions_index(sessions_dir, n=5)

        listed = sm.list_sessions()
        # Sorted by updated_at desc, so the highest index comes first.
        assert [row["id"] for row in listed] == list(reversed(ids))
        assert all(row["message_count"] >= 0 for row in listed)
        # Stub files are empty (0 bytes) — titles/counts matching the sidecar
        # payload prove the listing did not fall back to reading each file.
        assert all(row["title"].startswith("Session ") for row in listed)

    def test_list_sessions_under_100ms_for_10k_entries(self, sm, tmp_path):
        sessions_dir = tmp_path / "sessions"
        _seed_synthetic_sessions_index(sessions_dir, n=10_000)

        # Warm-up (filesystem cache, import costs).
        sm.list_sessions()

        start = time.perf_counter()
        listed = sm.list_sessions()
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(listed) == 10_000
        assert elapsed_ms < 100, f"listing took {elapsed_ms:.1f}ms (>100ms budget)"

    def test_self_heal_when_sidecar_missing(self, sm, tmp_path):
        sid = sm.create_session()
        sm.save_message(sid, "user", "hello")

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        sidecar.unlink()

        listed = sm.list_sessions()
        assert len(listed) == 1
        assert listed[0]["id"] == sid
        assert listed[0]["message_count"] == 1
        # Sidecar was rebuilt from disk.
        assert sidecar.exists()
        rebuilt = json.loads(sidecar.read_text())
        assert rebuilt["sessions"][sid]["message_count"] == 1

    def test_self_heal_when_sidecar_is_malformed(self, sm, tmp_path):
        sid = sm.create_session()
        sm.save_message(sid, "user", "hello")

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        sidecar.write_text("{not valid json", encoding="utf-8")

        listed = sm.list_sessions()
        assert len(listed) == 1
        assert listed[0]["id"] == sid
        # Sidecar was overwritten with a valid rebuild.
        rebuilt = json.loads(sidecar.read_text())
        assert rebuilt["schema_version"] == SESSION_INDEX_SCHEMA_VERSION

    def test_self_heal_when_sidecar_schema_unknown(self, sm, tmp_path):
        sid = sm.create_session()

        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        sidecar.write_text(
            json.dumps({"schema_version": "unknown", "sessions": {}}),
            encoding="utf-8",
        )

        listed = sm.list_sessions()
        assert [row["id"] for row in listed] == [sid]
        rebuilt = json.loads(sidecar.read_text())
        assert rebuilt["schema_version"] == SESSION_INDEX_SCHEMA_VERSION

    def test_rebuild_index_helper_writes_sidecar_from_scratch(
        self, sm, tmp_path
    ):
        sid_a = sm.create_session()
        sid_b = sm.create_session()
        sm.save_message(sid_a, "user", "hello")

        sessions_dir = tmp_path / "sessions"
        (sessions_dir / SESSION_INDEX_FILENAME).unlink()

        rebuilt = rebuild_index(sessions_dir)
        assert sorted(rebuilt.keys()) == sorted([sid_a, sid_b])
        assert rebuilt[sid_a]["message_count"] == 1
        assert rebuilt[sid_b]["message_count"] == 0

    def test_rebuild_skips_the_index_file_itself_and_non_uuid_files(
        self, tmp_path
    ):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        sid = _new_session_id()
        (sessions_dir / f"{sid}.json").write_text(
            json.dumps({"title": "keep", "updated_at": 1.0, "messages": []}),
            encoding="utf-8",
        )
        # Stray files that should be ignored.
        (sessions_dir / "stray.json").write_text("[]", encoding="utf-8")
        (sessions_dir / "not-a-uuid.json").write_text("[]", encoding="utf-8")

        rebuilt = rebuild_index(sessions_dir)
        assert list(rebuilt.keys()) == [sid]
        # The ``_index.json`` file was written; rescan must ignore it on the
        # next rebuild.
        assert (sessions_dir / SESSION_INDEX_FILENAME).exists()
        second = rebuild_index(sessions_dir)
        assert list(second.keys()) == [sid]

    def test_upsert_session_entry_is_idempotent(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        sid = _new_session_id()

        upsert_session_entry(
            sessions_dir, sid, title="v1", updated_at=1.0, message_count=3
        )
        upsert_session_entry(
            sessions_dir, sid, title="v2", updated_at=2.0, message_count=5
        )

        sidecar = sessions_dir / SESSION_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert len(payload["sessions"]) == 1
        assert payload["sessions"][sid]["title"] == "v2"
        assert payload["sessions"][sid]["message_count"] == 5

    def test_remove_session_noop_when_sidecar_missing(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        # Must not raise even though the sidecar has never been created.
        remove_session_from_index(sessions_dir, _new_session_id())
        assert not (sessions_dir / SESSION_INDEX_FILENAME).exists()

    def test_empty_sessions_dir_does_not_create_sidecar_on_read(
        self, sm, tmp_path
    ):
        listed = sm.list_sessions()
        assert listed == []
        sidecar = tmp_path / "sessions" / SESSION_INDEX_FILENAME
        assert not sidecar.exists()

    def test_phantom_sidecar_entries_are_pruned_on_read(self, sm, tmp_path):
        """Out-of-band deletions (e.g. retention runner) must not surface."""
        sid_keep = sm.create_session()
        sid_gone = sm.create_session()

        sessions_dir = tmp_path / "sessions"
        # Simulate the retention runner unlinking a session file directly
        # without going through ``delete_session`` (and thus without updating
        # the sidecar).
        (sessions_dir / f"{sid_gone}.json").unlink()

        listed = sm.list_sessions()
        assert [row["id"] for row in listed] == [sid_keep]

        # The sidecar was rewritten to drop the phantom entry.
        sidecar = sessions_dir / SESSION_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        assert sid_gone not in payload["sessions"]
        assert sid_keep in payload["sessions"]

    def test_concurrent_writes_do_not_race_on_tmp_path(self, tmp_path):
        """Regression test: each writer must use a unique tmp filename.

        Without per-call tmp names, concurrent writers collide on
        ``_index.json.tmp`` and one writer's ``tmp.replace(path)`` raises
        ``FileNotFoundError`` after another writer renamed the shared tmp
        away. Under the fix, many parallel writers complete without error.
        """
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        ids = [_new_session_id() for _ in range(50)]

        def do_upsert(sid: str) -> None:
            upsert_session_entry(
                sessions_dir,
                sid,
                title=sid,
                updated_at=1.0,
                message_count=0,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
            # ``list(ex.map(...))`` re-raises any worker exception; without
            # the fix FileNotFoundError would surface here.
            list(ex.map(do_upsert, ids))

        sidecar = sessions_dir / SESSION_INDEX_FILENAME
        payload = json.loads(sidecar.read_text())
        # Last writer wins under lost-update; at minimum the sidecar must be
        # a valid payload with no leftover ``.tmp`` files.
        assert payload["schema_version"] == SESSION_INDEX_SCHEMA_VERSION
        assert not list(sessions_dir.glob(f"{SESSION_INDEX_FILENAME}.*.tmp"))
