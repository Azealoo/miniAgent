"""
Tests for SessionManager — all file I/O uses tmp_path (no side effects).
"""
import json
import sys
import time
from pathlib import Path

import pytest
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session_manager import SessionManager


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


# ──────────────────────────────────────────────────────────────────────────────
# create / basic CRUD
# ──────────────────────────────────────────────────────────────────────────────

class TestCreateAndRead:
    def test_create_session_returns_uuid(self, sm):
        sid = sm.create_session()
        assert len(sid) == 36  # UUID format

    def test_create_session_writes_file(self, sm, tmp_path):
        sid = sm.create_session()
        assert (tmp_path / "sessions" / f"{sid}.json").exists()

    def test_new_session_has_empty_messages(self, sm):
        sid = sm.create_session()
        assert sm.load_session(sid) == []

    def test_new_session_title_is_new_chat(self, sm):
        sid = sm.create_session()
        meta = sm.get_session_meta(sid)
        assert meta["title"] == "New Chat"

    def test_load_nonexistent_session_returns_empty(self, sm):
        assert sm.load_session("does-not-exist") == []

    def test_session_meta_fields(self, sm):
        sid = sm.create_session()
        meta = sm.get_session_meta(sid)
        assert set(meta.keys()) == {"id", "title", "created_at", "updated_at", "message_count"}
        assert meta["id"] == sid
        assert meta["message_count"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# save / load messages
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveAndLoad:
    def test_save_user_message(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "Hello")
        msgs = sm.load_session(sid)
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "Hello"}

    def test_save_assistant_message(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "assistant", "Hi there")
        msgs = sm.load_session(sid)
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == "Hi there"

    def test_save_message_with_tool_calls(self, sm):
        sid = sm.create_session()
        tool_calls = [{"tool": "terminal", "input": "echo hi", "output": "hi"}]
        sm.save_message(sid, "assistant", "Done", tool_calls)
        msgs = sm.load_session(sid)
        assert msgs[0]["tool_calls"] == tool_calls

    def test_no_tool_calls_key_when_none(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "text")
        msgs = sm.load_session(sid)
        assert "tool_calls" not in msgs[0]

    def test_multiple_messages_in_order(self, sm):
        sid = sm.create_session()
        for i in range(5):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"msg{i}")
        msgs = sm.load_session(sid)
        assert len(msgs) == 5
        assert [m["content"] for m in msgs] == [f"msg{i}" for i in range(5)]

    def test_updated_at_changes_on_save(self, sm):
        sid = sm.create_session()
        before = sm.get_session_meta(sid)["updated_at"]
        time.sleep(0.01)
        sm.save_message(sid, "user", "ping")
        after = sm.get_session_meta(sid)["updated_at"]
        assert after > before

    def test_message_count_in_meta(self, sm):
        sid = sm.create_session()
        for i in range(3):
            sm.save_message(sid, "user", f"m{i}")
        assert sm.get_session_meta(sid)["message_count"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# load_session_for_agent — merge + compressed_context
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadSessionForAgent:
    def test_single_messages_unchanged(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "Q1")
        sm.save_message(sid, "assistant", "A1")
        history = sm.load_session_for_agent(sid)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_consecutive_assistant_messages_merged(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "Q")
        sm.save_message(sid, "assistant", "Part1")
        sm.save_message(sid, "assistant", "Part2")
        sm.save_message(sid, "assistant", "Part3")
        history = sm.load_session_for_agent(sid)
        # user + 1 merged assistant
        assert len(history) == 2
        assert history[1]["role"] == "assistant"
        assert "Part1" in history[1]["content"]
        assert "Part2" in history[1]["content"]
        assert "Part3" in history[1]["content"]

    def test_non_consecutive_not_merged(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "assistant", "A1")
        sm.save_message(sid, "user", "Q")
        sm.save_message(sid, "assistant", "A2")
        history = sm.load_session_for_agent(sid)
        assert len(history) == 3

    def test_compressed_context_prepended(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "new question")
        # manually inject compressed_context
        data = sm._read(sid)
        data["compressed_context"] = "Summary of old stuff"
        sm._write(sid, data)

        history = sm.load_session_for_agent(sid)
        assert history[0]["role"] == "assistant"
        assert "[Summary of previous conversation]" in history[0]["content"]
        assert "Summary of old stuff" in history[0]["content"]

    def test_no_compressed_context_no_synthetic(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "hello")
        history = sm.load_session_for_agent(sid)
        assert history[0]["role"] == "user"


# ──────────────────────────────────────────────────────────────────────────────
# compress_history
# ──────────────────────────────────────────────────────────────────────────────

class TestCompressHistory:
    def _populate(self, sm, sid, n):
        for i in range(n):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"msg{i}")

    def test_compress_archives_first_n(self, sm, tmp_path):
        sid = sm.create_session()
        self._populate(sm, sid, 10)
        archived, remaining = sm.compress_history(sid, "summary text", 4)
        assert archived == 4
        assert remaining == 6
        # Archive file written
        archive_files = list((tmp_path / "sessions" / "archive").glob("*.json"))
        assert len(archive_files) == 1
        archived_data = json.loads(archive_files[0].read_text())
        assert len(archived_data) == 4

    def test_compress_stores_summary(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 8)
        sm.compress_history(sid, "my summary", 4)
        assert sm.get_compressed_context(sid) == "my summary"

    def test_multiple_compressions_separated_by_dashes(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 20)
        sm.compress_history(sid, "first summary", 4)
        self._populate(sm, sid, 20)
        sm.compress_history(sid, "second summary", 4)
        ctx = sm.get_compressed_context(sid)
        assert "first summary" in ctx
        assert "second summary" in ctx
        assert "---" in ctx

    def test_remaining_messages_correct(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 10)
        sm.compress_history(sid, "summary", 4)
        msgs = sm.load_session(sid)
        assert len(msgs) == 6
        assert msgs[0]["content"] == "msg4"


# ──────────────────────────────────────────────────────────────────────────────
# rename / delete / list
# ──────────────────────────────────────────────────────────────────────────────

class TestRenameDeleteList:
    def test_rename_session(self, sm):
        sid = sm.create_session()
        sm.rename_session(sid, "My Custom Title")
        meta = sm.get_session_meta(sid)
        assert meta["title"] == "My Custom Title"

    def test_delete_session(self, sm, tmp_path):
        sid = sm.create_session()
        sm.delete_session(sid)
        assert not (tmp_path / "sessions" / f"{sid}.json").exists()

    def test_delete_nonexistent_no_error(self, sm):
        sm.delete_session("ghost-session-id")  # should not raise

    def test_list_sessions_returns_all(self, sm):
        ids = [sm.create_session() for _ in range(3)]
        listed = sm.list_sessions()
        listed_ids = {s["id"] for s in listed}
        for sid in ids:
            assert sid in listed_ids

    def test_list_sessions_sorted_by_updated_at_desc(self, sm):
        s1 = sm.create_session()
        time.sleep(0.02)
        s2 = sm.create_session()
        time.sleep(0.02)
        s3 = sm.create_session()
        listed = sm.list_sessions()
        ids_in_order = [s["id"] for s in listed]
        assert ids_in_order[0] == s3
        assert ids_in_order[-1] == s1


# ──────────────────────────────────────────────────────────────────────────────
# v1 migration
# ──────────────────────────────────────────────────────────────────────────────

class TestV1Migration:
    def test_plain_array_migrated_to_v2(self, sm, tmp_path):
        sid = "legacy-session"
        path = tmp_path / "sessions" / f"{sid}.json"
        path.write_text(
            json.dumps([
                {"role": "user", "content": "old message"},
                {"role": "assistant", "content": "old reply"},
            ]),
            encoding="utf-8",
        )
        msgs = sm.load_session(sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"

    def test_migrated_file_is_v2_format(self, sm, tmp_path):
        sid = "legacy-2"
        path = tmp_path / "sessions" / f"{sid}.json"
        path.write_text(json.dumps([{"role": "user", "content": "x"}]), encoding="utf-8")
        sm.load_session(sid)  # triggers migration
        upgraded = json.loads(path.read_text())
        assert isinstance(upgraded, dict)
        assert "messages" in upgraded
        assert "compressed_context" in upgraded


# ──────────────────────────────────────────────────────────────────────────────
# auto_compress_if_needed (sync threshold check only — no LLM call)
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoCompress:
    @pytest.mark.asyncio
    async def test_below_threshold_returns_false(self, sm):
        sid = sm.create_session()
        for i in range(10):
            sm.save_message(sid, "user", f"m{i}")
        result = await sm.auto_compress_if_needed(sid, llm=None, threshold=40)
        assert result is False

    @pytest.mark.asyncio
    async def test_at_threshold_tries_to_compress(self, sm):
        """With a mock LLM, compression should succeed."""
        sid = sm.create_session()
        for i in range(40):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_resp = MagicMock()
        mock_resp.content = "Auto summary"

        async def fake_ainvoke(msgs):
            return mock_resp

        mock_llm.ainvoke = fake_ainvoke

        mock_llm.bind.return_value.ainvoke = fake_ainvoke

        result = await sm.auto_compress_if_needed(sid, llm=mock_llm, threshold=40)
        assert result is True
        assert len(sm.load_session(sid)) < 40

    @pytest.mark.asyncio
    async def test_llm_failure_returns_false_nonfatal(self, sm):
        sid = sm.create_session()
        for i in range(40):
            sm.save_message(sid, "user", f"m{i}")

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)

        async def fail_ainvoke(msgs):
            raise RuntimeError("LLM unavailable")

        mock_llm.ainvoke = fail_ainvoke
        mock_llm.bind.return_value.ainvoke = fail_ainvoke

        result = await sm.auto_compress_if_needed(sid, llm=mock_llm, threshold=40)
        assert result is False
        assert len(sm.load_session(sid)) == 40  # untouched
