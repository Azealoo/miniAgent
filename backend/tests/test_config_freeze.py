"""Tests for the freeze-at-turn-start runtime config guarantee.

Covers three concerns:

* ``config.snapshot_runtime_config`` returns a ``RuntimeConfigSnapshot`` with a
  ``loaded_at`` timestamp.
* The file API (``api.files._check_path``) rejects writes to tracked config
  files with a clear message, and the ``BIOAPEX_ALLOW_CONFIG_RELOAD`` env var
  opens the gate for dev workflows.
* ``SessionStore.stamp_runtime_config_snapshot`` writes ``_loaded_at`` onto
  the session JSON so later inspection tools can trace which config shaped
  a given turn.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def isolated_base_dir(tmp_path, monkeypatch):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager

    original_base_dir = agent_manager.base_dir
    original_session_manager = agent_manager.session_manager
    original_memory_indexer = agent_manager.memory_indexer

    agent_manager.base_dir = tmp_path
    agent_manager.session_manager = SessionManager(base_dir=tmp_path)
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("workspace", "memory", "skills", "knowledge"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)
    (tmp_path / "memory" / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")

    # Make sure the dev override is off for every test; individual tests opt
    # back in explicitly.
    monkeypatch.delenv("BIOAPEX_ALLOW_CONFIG_RELOAD", raising=False)

    try:
        yield tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.session_manager = original_session_manager
        agent_manager.memory_indexer = original_memory_indexer


class TestRuntimeConfigSnapshot:
    def test_snapshot_has_loaded_at_and_data(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"rag_mode": True}), encoding="utf-8")
        monkeypatch.setattr("config._CONFIG_FILE", cfg_file)

        import config

        before = time.time()
        snapshot = config.snapshot_runtime_config()
        after = time.time()

        assert before <= snapshot.loaded_at <= after
        assert snapshot.config.data["rag_mode"] is True

    def test_config_reload_allowed_reads_env_var(self, monkeypatch):
        import config

        monkeypatch.delenv(config.ALLOW_CONFIG_RELOAD_ENV_VAR, raising=False)
        assert config.config_reload_allowed() is False

        monkeypatch.setenv(config.ALLOW_CONFIG_RELOAD_ENV_VAR, "1")
        assert config.config_reload_allowed() is True

        monkeypatch.setenv(config.ALLOW_CONFIG_RELOAD_ENV_VAR, "0")
        assert config.config_reload_allowed() is False


class TestConfigFileWriteRejection:
    def test_config_json_write_is_rejected_with_clear_message(self, isolated_base_dir):
        from api.files import SaveRequest, save_file
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            save_file(SaveRequest(path="config.json", content='{"rag_mode": true}\n'))

        assert exc_info.value.status_code == 403
        assert "frozen" in str(exc_info.value.detail).lower()
        assert "BIOAPEX_ALLOW_CONFIG_RELOAD" in str(exc_info.value.detail)

    def test_hooks_module_write_is_rejected(self, isolated_base_dir):
        from api.files import SaveRequest, save_file
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            save_file(SaveRequest(path="runtime/hooks.py", content="# evil\n"))

        assert exc_info.value.status_code == 403
        assert "frozen" in str(exc_info.value.detail).lower()

    def test_env_file_write_is_rejected_with_frozen_message(self, isolated_base_dir):
        from api.files import SaveRequest, save_file
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            save_file(SaveRequest(path=".env", content="DEEPSEEK_KEY=abc\n"))

        # The frozen-config check runs before the generic secret-file guard,
        # so we surface the actionable, override-aware message.
        assert exc_info.value.status_code == 403
        assert "frozen" in str(exc_info.value.detail).lower()

    def test_dev_override_allows_config_json_write(
        self, isolated_base_dir, monkeypatch
    ):
        from api.files import SaveRequest, save_file

        monkeypatch.setenv("BIOAPEX_ALLOW_CONFIG_RELOAD", "1")
        response = save_file(
            SaveRequest(path="config.json", content='{"rag_mode": false}\n')
        )

        assert response["saved"] is True
        assert (isolated_base_dir / "config.json").read_text(
            encoding="utf-8"
        ) == '{"rag_mode": false}\n'

    def test_dev_override_off_keeps_other_rejections_working(
        self, isolated_base_dir
    ):
        # Non-config writes outside the whitelist still produce the original
        # generic access-denied error, not the frozen-config message.
        from api.files import SaveRequest, save_file
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            save_file(SaveRequest(path="artifacts/demo/run.json", content="{}\n"))

        assert exc_info.value.status_code == 403
        assert "frozen" not in str(exc_info.value.detail).lower()


class TestSessionRuntimeConfigStamp:
    def test_stamp_runtime_config_snapshot_writes_loaded_at(self, tmp_path):
        from graph.session_manager import SessionManager

        manager = SessionManager(base_dir=tmp_path)
        session_id = manager.create_session()

        manager.stamp_runtime_config_snapshot(session_id, loaded_at=1234.5)

        payload = json.loads(
            (tmp_path / "sessions" / f"{session_id}.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["runtime_config"]["_loaded_at"] == 1234.5

        meta = manager.get_session_meta(session_id)
        assert meta["runtime_config"]["_loaded_at"] == 1234.5

    def test_stamp_is_noop_when_session_file_missing(self, tmp_path):
        from graph.session_manager import SessionManager

        manager = SessionManager(base_dir=tmp_path)
        session_id = "00000000-0000-4000-8000-000000000001"

        # Should not raise and should not create the session file.
        manager.stamp_runtime_config_snapshot(session_id, loaded_at=42.0)

        assert not (tmp_path / "sessions" / f"{session_id}.json").exists()
