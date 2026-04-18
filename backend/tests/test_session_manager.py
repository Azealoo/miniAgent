"""
Tests for SessionManager — all file I/O uses tmp_path (no side effects).
"""
import json
import sys
import time
from pathlib import Path

import pytest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.session_manager import SessionManager
from graph.session_summary import (
    MAX_SUMMARY_CHARS,
    STRUCTURED_SUMMARY_HEADER,
    build_summary_prompt,
    format_messages_for_summary,
    normalize_generated_summary,
    parse_summary_block,
)


@pytest.fixture
def sm(tmp_path):
    return SessionManager(base_dir=tmp_path)


def _valid_session_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _structured_summary(label: str) -> str:
    return (
        f"{STRUCTURED_SUMMARY_HEADER}\n"
        "Decisions and rationale:\n"
        f"- {label} decision\n\n"
        "Results register:\n"
        f"- {label} result\n\n"
        "Evidence register:\n"
        f"- PMID:{1000 + len(label)} linked to {label}\n\n"
        "Compliance register:\n"
        f"- {label} compliance note\n\n"
        "Open questions and next actions:\n"
        f"- Follow up on {label}\n"
    )


class TestSessionSummaryHelpers:
    def test_normalize_generated_summary_enforces_size_limit(self):
        oversized = (
            f"{STRUCTURED_SUMMARY_HEADER}\n"
            "Decisions and rationale:\n"
            f"- {'decision ' * 120}\n\n"
            "Results register:\n"
            f"- {'result ' * 120}\n\n"
            "Evidence register:\n"
            f"- PMID:12345 {'evidence ' * 120}\n\n"
            "Compliance register:\n"
            f"- {'approved ' * 120}\n\n"
            "Open questions and next actions:\n"
            f"- {'next ' * 120}\n"
        )

        normalized = normalize_generated_summary(oversized)
        assert normalized.startswith(STRUCTURED_SUMMARY_HEADER)
        assert len(normalized) <= MAX_SUMMARY_CHARS
        assert "PMID:12345" in normalized

    def test_parse_summary_block_accepts_heading_variants(self):
        varied = (
            f"{STRUCTURED_SUMMARY_HEADER}\n"
            "## 1. Decisions / Rationale:\n"
            "- keep the current threshold\n\n"
            "## Results:\n"
            "- run-20260318T190203Z-deadbeef completed\n\n"
            "## Evidence:\n"
            "- PMID:12345 supports the claim\n\n"
            "## Compliance / Safety:\n"
            "- blocked risky action until review\n\n"
            "## Next Steps:\n"
            "- inspect /tmp/output/report.txt\n"
        )

        parsed = parse_summary_block(varied)
        assert parsed.decisions_and_rationale == ["keep the current threshold"]
        assert parsed.results_register == ["run-20260318T190203Z-deadbeef completed"]
        assert parsed.evidence_register == ["PMID:12345 supports the claim"]
        assert parsed.compliance_register == ["blocked risky action until review"]
        assert parsed.open_questions_and_next_actions == ["inspect /tmp/output/report.txt"]

    def test_build_summary_prompt_preserves_salient_references_from_long_text(self):
        long_prefix = "background " * 700
        important_tail = (
            "PMID:12345 linked to claim https://example.org/paper "
            "run-20260318T190203Z-deadbeef wrote /tmp/output/report.txt "
            "blocked risky action pending review"
        )
        prompt = build_summary_prompt(
            [{"role": "assistant", "content": f"{long_prefix}{important_tail}"}]
        )
        human_prompt = prompt[-1].content

        assert "PMID:12345" in human_prompt
        assert "run-20260318T190203Z-deadbeef" in human_prompt
        assert "/tmp/output/report.txt" in human_prompt
        assert "blocked risky action pending review" in human_prompt

    def test_format_messages_for_summary_ignores_unknown_legacy_event_context(self):
        rendered = format_messages_for_summary(
            [
                {
                    "role": "assistant",
                    "content": "Legacy run metadata should not leak into the summary.",
                    "legacy_events": [
                        {
                            "type": "legacy_run_event",
                            "run_id": "run-20260319T120000Z-demo1234",
                            "payload": {
                                "path": (
                                    "artifacts/rna-seq-qc/2026-03-19/"
                                    "run-20260319T120000Z-demo1234/run.json"
                                ),
                            },
                        },
                    ],
                }
            ]
        )

        assert "Legacy run metadata should not leak into the summary." in rendered
        assert "legacy_run_event" not in rendered
        assert "run-20260319T120000Z-demo1234" not in rendered

    def test_format_messages_for_summary_includes_tool_artifacts_and_evidence_review_markers(self):
        rendered = format_messages_for_summary(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "tool": "evidence_review_gate",
                            "input": "What is the evidence for TP53 stress response?",
                            "output": "Evidence review is required before answering this biology request.",
                            "result": {
                                "warnings": ["evidence_review_required"],
                                "artifact_refs": [],
                                "structured_payload": {
                                    "requires_review": True,
                                    "reasons": ["biology-signal", "factual-biology-question"],
                                },
                            },
                        },
                        {
                            "tool": "evidence_review",
                            "input": '{"question":"What is the evidence for TP53 stress response?"}',
                            "output": "Reviewed 1 evidence card(s); support status: supported; confidence: medium.",
                            "result": {
                                "warnings": [],
                                "artifact_refs": [
                                    {
                                        "artifact_type": "evidence_review",
                                        "path": "artifacts/evidence-review/2026-03-20/run-20260320T210000Z-deadbeef/evidence_review.json",
                                    }
                                ],
                                "structured_payload": {
                                    "question": "What is the evidence for TP53 stress response?",
                                    "review_status": "supported",
                                    "unsupported_claims_present": False,
                                },
                            },
                        },
                    ],
                }
            ]
        )

        assert "Tool warning: evidence_review_required" in rendered
        assert "Tool artifact: artifacts/evidence-review/2026-03-20/" in rendered
        assert "Evidence review required: yes" in rendered
        assert "Evidence review status: supported" in rendered
        assert "Evidence review question: What is the evidence for TP53 stress response?" in rendered


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
        assert sm.load_session(_valid_session_id(1)) == []

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
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello"
        assert msgs[0]["blocks"] == [{"type": "text", "text": "Hello"}]
        stored = sm._read(sid)["messages"][0]
        assert stored["blocks"] == [{"type": "text", "text": "Hello"}]

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
        assert msgs[0]["blocks"] == [
            {"type": "tool_use", "tool": "terminal", "input": "echo hi"},
            {"type": "tool_result", "tool": "terminal", "output": "hi"},
            {"type": "text", "text": "Done"},
        ]

    def test_load_session_ignores_unknown_legacy_event_blocks(self, sm):
        sid = sm.create_session()
        sm.save_message(
            sid,
            "assistant",
            "",
            blocks=[
                {
                    "type": "legacy_event",
                    "event": {
                        "contract_version": "legacy_event.v1",
                        "type": "legacy_start",
                        "run_id": "run-20260319T120000Z-demo1234",
                    },
                }
            ],
        )
        msgs = sm.load_session(sid)
        assert "legacy_events" not in msgs[0]
        assert "blocks" not in msgs[0]

    def test_save_message_with_retrievals(self, sm):
        sid = sm.create_session()
        retrievals = [
            {
                "text": "Differential expression used DESeq2 defaults.",
                "score": 0.91,
                "source": "notes/deseq2.md",
            }
        ]
        sm.save_message(sid, "assistant", "Done", retrievals=retrievals)
        msgs = sm.load_session(sid)
        assert msgs[0]["retrievals"] == retrievals
        assert msgs[0]["blocks"] == [
            {"type": "retrieval", "results": retrievals},
            {"type": "text", "text": "Done"},
        ]

    def test_no_tool_calls_key_when_none(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "text")
        msgs = sm.load_session(sid)
        assert "tool_calls" not in msgs[0]

    def test_save_message_persists_blocks_only_no_legacy_arrays_on_disk(self, sm):
        sid = sm.create_session()
        sm.save_message(
            sid,
            "assistant",
            "Done",
            tool_calls=[{"tool": "terminal", "input": "echo hi", "output": "hi"}],
            retrievals=[{"text": "Context", "score": 0.8, "source": "notes/a.md"}],
        )
        stored = sm._read(sid)["messages"][0]
        assert "tool_calls" not in stored
        assert "retrievals" not in stored
        assert stored["blocks"] == [
            {"type": "retrieval", "results": [
                {"text": "Context", "score": 0.8, "source": "notes/a.md"}
            ]},
            {"type": "tool_use", "tool": "terminal", "input": "echo hi"},
            {"type": "tool_result", "tool": "terminal", "output": "hi"},
            {"type": "text", "text": "Done"},
        ]

    def test_load_session_migrates_legacy_only_sessions_without_writing_legacy_arrays(self, sm):
        sid = sm.create_session()
        data = sm._read(sid)
        data["messages"] = [
            {
                "role": "assistant",
                "content": "Legacy reply",
                "tool_calls": [
                    {"tool": "terminal", "input": "ls", "output": "file.txt"}
                ],
                "retrievals": [
                    {"text": "Prior note", "score": 0.7, "source": "notes/b.md"}
                ],
            }
        ]
        sm._write(sid, data)

        msgs = sm.load_session(sid)
        assert msgs[0]["content"] == "Legacy reply"
        assert msgs[0]["tool_calls"][0]["tool"] == "terminal"
        assert msgs[0]["retrievals"][0]["source"] == "notes/b.md"
        assert msgs[0]["blocks"] == [
            {"type": "retrieval", "results": [
                {"text": "Prior note", "score": 0.7, "source": "notes/b.md"}
            ]},
            {"type": "tool_use", "tool": "terminal", "input": "ls"},
            {"type": "tool_result", "tool": "terminal", "output": "file.txt"},
            {"type": "text", "text": "Legacy reply"},
        ]

    def test_compress_history_archive_file_is_blocks_only(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(
                sid,
                "assistant",
                f"reply{i}",
                tool_calls=[{"tool": "terminal", "input": f"cmd{i}", "output": f"out{i}"}],
            )
        sm.compress_history(sid, "summary", 4)

        archive_path = next((tmp_path / "sessions" / "archive").glob(f"{sid}_*.json"))
        archived = json.loads(archive_path.read_text(encoding="utf-8"))
        for msg in archived:
            assert "tool_calls" not in msg
            assert "retrievals" not in msg
            assert isinstance(msg.get("blocks"), list)

        stored_remaining = sm._read(sid)["messages"]
        for msg in stored_remaining:
            assert "tool_calls" not in msg
            assert "retrievals" not in msg

    def test_load_session_derives_legacy_fields_from_blocks_only_messages(self, sm):
        sid = sm.create_session()
        data = sm._read(sid)
        data["messages"] = [
            {
                "role": "assistant",
                "request_id": "request-1",
                "blocks": [
                    {
                        "type": "retrieval",
                        "query": "Find TP53 evidence",
                        "results": [
                            {
                                "text": "TP53 regulates stress response genes.",
                                "score": 0.88,
                                "source": "knowledge/tp53.md",
                            }
                        ],
                    },
                    {
                        "type": "tool_use",
                        "tool": "read_file",
                        "input": "memory/MEMORY.md",
                        "run_id": "tool-run-1",
                    },
                    {
                        "type": "tool_result",
                        "tool": "read_file",
                        "output": "# Memory",
                        "run_id": "tool-run-1",
                        "result": {
                            "contract_version": "tool_result.v1",
                            "tool_name": "read_file",
                            "summary": "# Memory",
                            "structured_payload": {
                                "path": "memory/MEMORY.md",
                                "content": "# Memory",
                            },
                            "artifact_refs": [],
                            "warnings": [],
                            "status": "success",
                            "outcome": "success",
                            "error": None,
                            "metadata": {},
                            "source_payload": None,
                        },
                    },
                    {
                        "type": "legacy_event",
                        "event": {
                            "contract_version": "legacy_event.v1",
                            "type": "legacy_done",
                            "run_id": "run-1",
                            "run_record_path": "artifacts/rna-seq-qc/demo/run.json",
                        },
                    },
                    {
                        "type": "text",
                        "text": "Structured blocks only.",
                    },
                ],
            }
        ]
        sm._write(sid, data)

        msgs = sm.load_session(sid)
        assert msgs[0]["content"] == "Structured blocks only."
        assert msgs[0]["retrievals"][0]["source"] == "knowledge/tp53.md"
        assert msgs[0]["tool_calls"][0]["tool"] == "read_file"
        assert msgs[0]["tool_calls"][0]["input"] == "memory/MEMORY.md"
        assert msgs[0]["tool_calls"][0]["result"]["tool_name"] == "read_file"
        assert "legacy_events" not in msgs[0]

    def test_multiple_messages_in_order(self, sm):
        sid = sm.create_session()
        for i in range(5):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"msg{i}")
        msgs = sm.load_session(sid)
        assert len(msgs) == 5
        assert [m["content"] for m in msgs] == [f"msg{i}" for i in range(5)]

    def test_load_request_messages_filters_by_request_id(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "First", request_id="request-1")
        sm.save_message(sid, "assistant", "Reply one", request_id="request-1")
        sm.save_message(sid, "user", "Second", request_id="request-2")

        msgs = sm.load_request_messages(sid, "request-1")

        assert [msg["content"] for msg in msgs] == ["First", "Reply one"]

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
        assert history[0]["role"] == "system"
        assert "[Summary of earlier conversation" in history[0]["content"]
        assert "Summary of old stuff" in history[0]["content"]

    def test_structured_compressed_context_loaded_for_agent(self, sm):
        sid = sm.create_session()
        sm.save_message(sid, "user", "What happened earlier?")
        data = sm._read(sid)
        data["compressed_context"] = _structured_summary("session memory")
        sm._write(sid, data)

        history = sm.load_session_for_agent(sid)
        assert history[0]["role"] == "system"
        assert STRUCTURED_SUMMARY_HEADER in history[0]["content"]
        assert "Evidence register:" in history[0]["content"]
        assert "session memory result" in history[0]["content"]

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
        sm.compress_history(sid, _structured_summary("first"), 4)
        self._populate(sm, sid, 20)
        sm.compress_history(sid, _structured_summary("second"), 4)
        ctx = sm.get_compressed_context(sid)
        assert "first result" in ctx
        assert "second result" in ctx
        assert "---" in ctx

    def test_remaining_messages_correct(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 10)
        sm.compress_history(sid, "summary", 4)
        msgs = sm.load_session(sid)
        assert len(msgs) == 6
        assert msgs[0]["content"] == "msg4"

    def test_get_compressed_summaries_migrates_legacy_text(self, sm):
        sid = sm.create_session()
        data = sm._read(sid)
        data["compressed_context"] = "Legacy summary with PMID:12345 and /tmp/run-1/output.txt"
        sm._write(sid, data)

        summaries = sm.get_compressed_summaries(sid)
        assert len(summaries) == 1
        assert summaries[0]["source_format"] == "legacy"
        assert summaries[0]["legacy_summary"] == data["compressed_context"]
        assert summaries[0]["results_register"] == [data["compressed_context"]]

    def test_get_compressed_summaries_parses_multiple_blocks(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 10)
        sm.compress_history(sid, _structured_summary("first block"), 4)
        self._populate(sm, sid, 10)
        sm.compress_history(sid, _structured_summary("second block"), 4)

        summaries = sm.get_compressed_summaries(sid)
        assert len(summaries) == 2
        assert summaries[0]["source_format"] == "structured"
        assert summaries[0]["results_register"] == ["first block result"]
        assert summaries[1]["results_register"] == ["second block result"]

    def test_list_archived_history_batches_returns_archive_metadata(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 6)

        archived, _ = sm.compress_history(sid, _structured_summary("batch one"), 4)
        assert archived == 4

        batches = sm.list_archived_history_batches(sid)
        assert len(batches) == 1
        assert batches[0]["message_count"] == 4
        assert batches[0]["archive_id"].isdigit()

    def test_load_archived_history_returns_normalized_messages(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 6)
        sm.compress_history(sid, _structured_summary("batch two"), 4)

        archive_id = sm.list_archived_history_batches(sid)[0]["archive_id"]
        archived_messages = sm.load_archived_history(sid, archive_id)

        assert len(archived_messages) == 4
        assert archived_messages[0]["role"] == "user"
        assert archived_messages[0]["content"] == "msg0"

    def test_get_session_continuity_pairs_summaries_with_archives(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 10)
        sm.compress_history(sid, _structured_summary("first block"), 4)
        self._populate(sm, sid, 10)
        sm.compress_history(sid, _structured_summary("second block"), 4)

        continuity = sm.get_session_continuity(sid)

        assert len(continuity) == 2
        assert continuity[0]["results_register"] == ["first block result"]
        assert continuity[0]["archived_message_count"] == 4
        assert continuity[0]["archive_id"].isdigit()
        assert continuity[1]["results_register"] == ["second block result"]
        assert continuity[1]["archived_message_count"] == 4

    def test_get_session_continuity_keeps_legacy_summaries_unlinked(self, sm):
        sid = sm.create_session()
        data = sm._read(sid)
        data["compressed_context"] = "Legacy summary with PMID:12345 and archived findings"
        sm._write(sid, data)
        self._populate(sm, sid, 6)

        sm.compress_history(sid, _structured_summary("fresh block"), 4)
        continuity = sm.get_session_continuity(sid)

        assert len(continuity) == 2
        assert continuity[0]["source_format"] == "legacy"
        assert continuity[0]["archive_id"] is None
        assert continuity[0]["archived_message_count"] == 0
        assert continuity[1]["results_register"] == ["fresh block result"]
        assert continuity[1]["archive_id"].isdigit()
        assert continuity[1]["archived_message_count"] == 4

    def test_get_session_continuity_does_not_guess_when_archive_counts_mismatch(self, sm):
        sid = sm.create_session()
        self._populate(sm, sid, 10)
        sm.compress_history(sid, _structured_summary("first block"), 4)
        self._populate(sm, sid, 10)
        sm.compress_history(sid, _structured_summary("second block"), 4)

        data = sm._read(sid)
        data.pop("compressed_archive_index", None)
        sm._write(sid, data)

        first_archive = sorted(sm.archive_dir.glob(f"{sid}_*.json"))[0]
        first_archive.write_text("{invalid", encoding="utf-8")

        continuity = sm.get_session_continuity(sid)

        assert [item["archive_id"] for item in continuity] == [None, None]
        assert [item["archived_message_count"] for item in continuity] == [0, 0]


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

    def test_delete_session_removes_archived_batches(self, sm, tmp_path):
        sid = sm.create_session()
        for i in range(6):
            sm.save_message(sid, "user" if i % 2 == 0 else "assistant", f"msg{i}")
        sm.compress_history(sid, _structured_summary("cleanup check"), 4)

        assert list((tmp_path / "sessions" / "archive").glob(f"{sid}_*.json"))

        sm.delete_session(sid)

        assert not list((tmp_path / "sessions" / "archive").glob(f"{sid}_*.json"))

    def test_delete_nonexistent_no_error(self, sm):
        sm.delete_session(_valid_session_id(2))  # should not raise

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
        sid = _valid_session_id(3)
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
        sid = _valid_session_id(4)
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
        assert STRUCTURED_SUMMARY_HEADER in sm.get_compressed_context(sid)

    @pytest.mark.asyncio
    async def test_auto_compress_includes_tool_calls_in_summary_prompt(self, sm):
        sid = sm.create_session()
        for i in range(20):
            sm.save_message(sid, "user", f"user-{i}")
            sm.save_message(
                sid,
                "assistant",
                f"assistant-{i}",
                tool_calls=[
                    {
                        "tool": "terminal",
                        "input": f"python run_qc.py --run-id RUN{i}",
                        "output": f"wrote /tmp/results/run_{i}.json",
                    }
                ],
            )

        observed_prompt = {}

        async def fake_ainvoke(msgs):
            observed_prompt["content"] = msgs[-1].content
            mock_resp = MagicMock()
            mock_resp.content = _structured_summary("tool capture")
            return mock_resp

        mock_llm = MagicMock()
        mock_llm.bind = MagicMock(return_value=mock_llm)
        mock_llm.ainvoke = fake_ainvoke
        mock_llm.bind.return_value.ainvoke = fake_ainvoke

        result = await sm.auto_compress_if_needed(sid, llm=mock_llm, threshold=40)
        assert result is True
        assert "Tool call 1: terminal" in observed_prompt["content"]
        assert "python run_qc.py --run-id RUN0" in observed_prompt["content"]
        assert "wrote /tmp/results/run_0.json" in observed_prompt["content"]
        assert "tool capture result" in sm.get_compressed_context(sid)

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


# --------------------------------------------------------------------- #
# delete_session post-session distillation hook                         #
# --------------------------------------------------------------------- #


class TestDeleteSessionDistillationHook:
    def test_delete_session_writes_post_session_distillation(self, sm, tmp_path):
        from runtime.memory_distillation import clear_failed_distillations

        clear_failed_distillations()
        session_id = sm.create_session()
        sm.save_message(session_id, "user", "Plan a QC rerun.", request_id="req-1")
        sm.save_message(
            session_id,
            "assistant",
            "Rerunning FastQC then MultiQC.",
            request_id="req-1",
            blocks=[{"type": "text", "text": "Rerunning FastQC then MultiQC."}],
        )

        sm.delete_session(session_id)

        target = tmp_path / "memory" / "agent" / f"session-{session_id}.md"
        assert target.exists(), "delete_session must fire distill_session before unlinking"
        content = target.read_text(encoding="utf-8")
        assert "type: session_distillation" in content
        assert "## Turn req-1" in content
        # Session file itself must be gone.
        assert not (tmp_path / "sessions" / f"{session_id}.json").exists()

    def test_distillation_failure_does_not_block_delete_and_surfaces_in_debug(
        self, sm, tmp_path, monkeypatch
    ):
        from runtime import memory_distillation
        from runtime.memory_distillation import (
            clear_failed_distillations,
            get_failed_distillations,
        )

        clear_failed_distillations()
        session_id = sm.create_session()
        sm.save_message(session_id, "user", "Doomed turn.", request_id="req-doom")

        async def _exploding_distill(*args, **kwargs):
            raise RuntimeError("post-session distillation exploded")

        monkeypatch.setattr(memory_distillation, "distill_session", _exploding_distill)

        # Must not raise, even when distillation fails.
        sm.delete_session(session_id)

        # Session file is deleted despite the failure.
        assert not (tmp_path / "sessions" / f"{session_id}.json").exists()
        # Failure is surfaced via the in-memory set the debug endpoint exposes.
        assert session_id in get_failed_distillations()
