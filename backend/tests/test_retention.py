"""Tests for ``backend/runtime/retention.py``.

Each test uses ``tmp_path`` so no real session / artifact / memory files are
touched. The retention runner is exercised with an explicit ``config`` dict so
tests do not depend on the on-disk ``config.json`` layering.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from runtime.retention import (  # noqa: E402 — sys.path tweak above
    ALLOWED_RETENTION_PREFIXES,
    apply_retention,
    parse_retention_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_file(path: Path, *, size: int, mtime: float, atime: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    os.utime(path, (atime, mtime))
    return path


def _existing(root: Path, names: list[str]) -> list[str]:
    return sorted(n for n in names if (root / n).exists())


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


class TestParseRetentionConfig:
    def test_empty_input_returns_empty_list(self):
        dirs, dry_run = parse_retention_config({})
        assert dirs == []
        assert dry_run is False

    def test_drops_entries_with_neither_cap(self):
        dirs, _ = parse_retention_config(
            {"paths": {"sessions": {"strategy": "fifo"}}}
        )
        assert dirs == []

    def test_rejects_traversal_in_path(self):
        dirs, _ = parse_retention_config(
            {
                "paths": {
                    "escape": {
                        "path": "sessions/../../../etc",
                        "max_bytes": 1,
                    }
                }
            }
        )
        assert dirs == []

    def test_strategy_defaults_to_fifo_when_invalid(self):
        dirs, _ = parse_retention_config(
            {
                "paths": {
                    "archives": {
                        "path": "sessions/archive",
                        "max_age_days": 30,
                        "strategy": "banana",
                    }
                }
            }
        )
        assert len(dirs) == 1
        assert dirs[0].strategy == "fifo"

    def test_dry_run_default_is_surfaced(self):
        _, dry_run = parse_retention_config({"dry_run": True, "paths": {}})
        assert dry_run is True


# ---------------------------------------------------------------------------
# Strategy coverage
# ---------------------------------------------------------------------------


class TestApplyRetention:
    def _make_base(self, tmp_path: Path) -> Path:
        base = tmp_path / "backend"
        base.mkdir()
        return base

    def test_fifo_enforces_byte_quota_by_mtime(self, tmp_path):
        base = self._make_base(tmp_path)
        sessions = base / "sessions"
        now = 1_700_000_000.0
        _write_file(
            sessions / "oldest.json", size=100, mtime=now - 3000, atime=now
        )
        _write_file(
            sessions / "middle.json", size=100, mtime=now - 2000, atime=now
        )
        _write_file(
            sessions / "newest.json", size=100, mtime=now - 1000, atime=now
        )

        config = {
            "paths": {
                "sessions": {
                    "path": "sessions",
                    "max_bytes": 200,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        assert result.dry_run is False
        assert len(result.results) == 1
        dir_result = result.results[0]
        assert dir_result.scanned_files == 3
        # FIFO + 200-byte cap on a 300-byte scan → drops the oldest file.
        assert [a.path.name for a in dir_result.actions] == ["oldest.json"]
        assert _existing(sessions, ["oldest.json", "middle.json", "newest.json"]) == [
            "middle.json",
            "newest.json",
        ]

    def test_lru_enforces_byte_quota_by_atime(self, tmp_path):
        base = self._make_base(tmp_path)
        memory = base / "memory" / "agent"
        now = 1_700_000_000.0
        # Write with an mtime order that inverts the atime order so the two
        # strategies cannot coincidentally agree.
        _write_file(
            memory / "recently_read.md",
            size=150,
            mtime=now - 3000,  # written long ago
            atime=now - 100,   # but read recently
        )
        _write_file(
            memory / "stale_read.md",
            size=150,
            mtime=now - 1000,  # written recently
            atime=now - 5000,  # but not read in ages
        )

        config = {
            "paths": {
                "agent_memory": {
                    "path": "memory/agent",
                    "max_bytes": 200,
                    "strategy": "lru",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        dir_result = result.results[0]
        assert dir_result.strategy == "lru"
        # LRU evicts the file with the oldest atime, even though it has the
        # newer mtime.
        assert [a.path.name for a in dir_result.actions] == ["stale_read.md"]
        assert not (memory / "stale_read.md").exists()
        assert (memory / "recently_read.md").exists()

    def test_age_quota_deletes_entries_older_than_cutoff(self, tmp_path):
        base = self._make_base(tmp_path)
        archive = base / "sessions" / "archive"
        now = 1_700_000_000.0
        day = 86_400.0
        _write_file(archive / "ancient.json", size=10, mtime=now - 40 * day, atime=now)
        _write_file(archive / "old.json", size=10, mtime=now - 8 * day, atime=now)
        _write_file(archive / "fresh.json", size=10, mtime=now - 1 * day, atime=now)

        config = {
            "paths": {
                "archives": {
                    "path": "sessions/archive",
                    "max_age_days": 7,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        dir_result = result.results[0]
        deleted = sorted(a.path.name for a in dir_result.actions if a.reason == "age")
        assert deleted == ["ancient.json", "old.json"]
        assert _existing(archive, ["ancient.json", "old.json", "fresh.json"]) == [
            "fresh.json"
        ]

    def test_dry_run_reports_without_deleting(self, tmp_path):
        base = self._make_base(tmp_path)
        artifacts = base / "artifacts"
        now = 1_700_000_000.0
        _write_file(artifacts / "a.bin", size=500, mtime=now - 90_000, atime=now)
        _write_file(artifacts / "b.bin", size=500, mtime=now - 10_000, atime=now)

        config = {
            "dry_run": True,
            "paths": {
                "artifacts": {
                    "path": "artifacts",
                    "max_bytes": 500,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        assert result.dry_run is True
        dir_result = result.results[0]
        assert len(dir_result.actions) == 1
        assert dir_result.actions[0].deleted is False
        # Filesystem is untouched on dry-run.
        assert (artifacts / "a.bin").exists()
        assert (artifacts / "b.bin").exists()

    def test_dry_run_override_beats_config_default(self, tmp_path):
        base = self._make_base(tmp_path)
        artifacts = base / "artifacts"
        now = 1_700_000_000.0
        _write_file(artifacts / "a.bin", size=500, mtime=now - 90_000, atime=now)
        _write_file(artifacts / "b.bin", size=500, mtime=now - 10_000, atime=now)

        config = {
            "dry_run": False,
            "paths": {
                "artifacts": {
                    "path": "artifacts",
                    "max_bytes": 500,
                    "strategy": "fifo",
                }
            }
        }
        # Caller forces dry-run even though the config says delete.
        result = apply_retention(base, config=config, dry_run=True, now=now)

        assert result.dry_run is True
        dir_result = result.results[0]
        assert dir_result.actions[0].deleted is False
        assert (artifacts / "a.bin").exists()

    def test_protected_filenames_are_never_deleted(self, tmp_path):
        base = self._make_base(tmp_path)
        memory = base / "memory"
        now = 1_700_000_000.0
        _write_file(memory / "MEMORY.md", size=1000, mtime=now - 10 * 86_400, atime=now)
        _write_file(memory / "stale.md", size=1000, mtime=now - 10 * 86_400, atime=now)

        config = {
            "paths": {
                "memory": {
                    "path": "memory",
                    "max_age_days": 1,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        dir_result = result.results[0]
        deleted = [a.path.name for a in dir_result.actions]
        assert deleted == ["stale.md"]
        assert (memory / "MEMORY.md").exists()

    def test_custom_protect_list_skips_named_files(self, tmp_path):
        base = self._make_base(tmp_path)
        artifacts = base / "artifacts"
        now = 1_700_000_000.0
        _write_file(artifacts / "keep.txt", size=100, mtime=now - 10_000, atime=now)
        _write_file(artifacts / "drop.txt", size=100, mtime=now - 10_000, atime=now)

        config = {
            "paths": {
                "artifacts": {
                    "path": "artifacts",
                    "max_bytes": 1,
                    "strategy": "fifo",
                    "protect": ["keep.txt"],
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        dir_result = result.results[0]
        assert [a.path.name for a in dir_result.actions] == ["drop.txt"]
        assert (artifacts / "keep.txt").exists()

    def test_whitelist_blocks_non_allowed_roots(self, tmp_path):
        base = self._make_base(tmp_path)
        forbidden = base / "storage"
        now = 1_700_000_000.0
        _write_file(forbidden / "secret.bin", size=100, mtime=now, atime=now)

        config = {
            "paths": {
                "audit": {
                    "path": "storage",
                    "max_bytes": 1,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        dir_result = result.results[0]
        assert dir_result.skipped_reason is not None
        assert dir_result.actions == ()
        assert (forbidden / "secret.bin").exists()

    def test_missing_directory_is_a_silent_noop(self, tmp_path):
        base = self._make_base(tmp_path)
        config = {
            "paths": {
                "artifacts": {
                    "path": "artifacts",
                    "max_bytes": 1,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=1_700_000_000.0)
        assert len(result.results) == 1
        assert result.results[0].actions == ()
        assert result.results[0].skipped_reason is None

    def test_empty_config_is_noop(self, tmp_path):
        base = self._make_base(tmp_path)
        result = apply_retention(base, config=None or {}, now=1_700_000_000.0)
        assert result.results == ()

    def test_combined_age_and_byte_quota_delete_both_sets(self, tmp_path):
        base = self._make_base(tmp_path)
        sessions = base / "sessions"
        now = 1_700_000_000.0
        day = 86_400.0
        # Two ancient entries (age-evicted) + three recent ones totalling 900
        # bytes. Byte cap of 500 forces two more FIFO deletions.
        _write_file(sessions / "a.json", size=200, mtime=now - 30 * day, atime=now)
        _write_file(sessions / "b.json", size=200, mtime=now - 25 * day, atime=now)
        _write_file(sessions / "c.json", size=300, mtime=now - 5 * day, atime=now)
        _write_file(sessions / "d.json", size=300, mtime=now - 3 * day, atime=now)
        _write_file(sessions / "e.json", size=300, mtime=now - 1 * day, atime=now)

        config = {
            "paths": {
                "sessions": {
                    "path": "sessions",
                    "max_age_days": 14,
                    "max_bytes": 500,
                    "strategy": "fifo",
                }
            }
        }
        result = apply_retention(base, config=config, now=now)

        dir_result = result.results[0]
        age_names = sorted(a.path.name for a in dir_result.actions if a.reason == "age")
        quota_names = sorted(a.path.name for a in dir_result.actions if a.reason == "quota")
        assert age_names == ["a.json", "b.json"]
        # After age eviction c/d/e (900 bytes) remain; FIFO by mtime drops
        # ``c.json`` (300) → 600, then ``d.json`` (300) → 300 ≤ 500.
        assert quota_names == ["c.json", "d.json"]
        assert _existing(sessions, ["a.json", "b.json", "c.json", "d.json", "e.json"]) == [
            "e.json"
        ]


# ---------------------------------------------------------------------------
# Misc invariants
# ---------------------------------------------------------------------------


def test_allowed_prefixes_match_file_api_write_whitelist():
    # The retention whitelist is the file API's read whitelist plus
    # ``sessions/``. If either moves, retention needs to follow.
    assert "sessions/" in ALLOWED_RETENTION_PREFIXES
    for prefix in ("workspace/", "memory/", "skills/", "knowledge/", "artifacts/"):
        assert prefix in ALLOWED_RETENTION_PREFIXES


def test_symlinks_are_skipped(tmp_path):
    base = tmp_path / "backend"
    sessions = base / "sessions"
    sessions.mkdir(parents=True)
    target = sessions / "real.json"
    target.write_bytes(b"x" * 100)
    os.utime(target, (1_700_000_000.0, 1_699_000_000.0))

    outside = tmp_path / "outside.json"
    outside.write_bytes(b"y" * 10_000)
    link = sessions / "link.json"
    link.symlink_to(outside)

    config = {
        "paths": {
            "sessions": {
                "path": "sessions",
                "max_bytes": 1,
                "strategy": "fifo",
            }
        }
    }
    result = apply_retention(base, config=config, now=1_700_000_000.0)

    dir_result = result.results[0]
    # Symlink is ignored; only the real file is scanned and evicted.
    assert dir_result.scanned_files == 1
    assert [a.path.name for a in dir_result.actions] == ["real.json"]
    assert not target.exists()
    assert link.exists()  # symlink itself is left alone
    assert outside.exists()  # target outside base_dir is untouched


@pytest.mark.parametrize("strategy", ["fifo", "lru"])
def test_no_caps_means_no_deletions(tmp_path, strategy):
    base = tmp_path / "backend"
    sessions = base / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "a.json").write_bytes(b"x" * 100)

    # Neither max_bytes nor max_age_days → entry is dropped by the parser.
    config = {
        "paths": {
            "sessions": {
                "path": "sessions",
                "strategy": strategy,
            }
        }
    }
    result = apply_retention(base, config=config, now=1_700_000_000.0)
    assert result.results == ()
    assert (sessions / "a.json").exists()
