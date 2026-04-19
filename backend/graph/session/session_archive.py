"""Session archive lifecycle: compression, archived history retrieval,
continuity, and auto-compress scheduling.

``SessionManager`` extends :class:`SessionStore` so callers import one class
and get both basic storage and archive features.
"""

import json
import time
from typing import Any

from graph.session.session_archive_index import (
    _atomic_write_text,
    append_archive_entry,
    list_archive_entries,
)
from graph.session.session_normalizer import (
    _normalize_messages,
    _normalize_messages_for_storage,
)
from graph.session.session_schema import (
    SessionArchiveIndexEntry,
    _ARCHIVE_ID_RE,
    _validate_session_id,
)
from graph.session.session_store import SessionStore
from graph.session_summary import (
    append_compressed_summary,
    generate_structured_summary,
    parse_compressed_context,
)


def _empty_archive_index_entry() -> SessionArchiveIndexEntry:
    return {"archive_id": None, "message_count": 0}


def _normalize_archive_index(value: Any) -> list[SessionArchiveIndexEntry]:
    if not isinstance(value, list):
        return []

    entries: list[SessionArchiveIndexEntry] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        archive_id = item.get("archive_id")
        if not isinstance(archive_id, str) or not _ARCHIVE_ID_RE.match(archive_id):
            archive_id = None

        message_count = item.get("message_count")
        if not isinstance(message_count, int) or message_count < 0:
            message_count = 0

        entries.append({"archive_id": archive_id, "message_count": message_count})

    return entries


def _pad_archive_index(
    entries: list[SessionArchiveIndexEntry], summary_count: int
) -> list[SessionArchiveIndexEntry]:
    padded = list(entries[:summary_count])
    if len(padded) < summary_count:
        padded.extend(_empty_archive_index_entry() for _ in range(summary_count - len(padded)))
    return padded


COMPRESSION_PHASES: tuple[str, ...] = ("snip", "microcompact", "collapse", "autocompact")


class SessionManager(SessionStore):
    def compress_history(
        self,
        session_id: str,
        summary: str,
        n: int,
        *,
        phase: str | None = None,
        replace_compressed_context: bool = False,
    ) -> tuple[int, int]:
        """
        Archive the first *n* messages and store *summary* in compressed_context.
        Returns (archived_count, remaining_count).

        ``phase`` records which rung of the four-phase compaction ladder
        (``snip`` → ``microcompact`` → ``collapse`` → ``autocompact``) produced
        this compression. It is persisted on the session JSON as
        ``context_compression_phase`` so the UI and audit tools can surface
        the most recent rung without replaying the SSE stream.

        ``replace_compressed_context`` switches the ``compressed_context``
        update from the default append-and-accumulate behavior to a full
        rewrite: the prior context is discarded, the new ``summary`` becomes
        the sole entry, and the archive index is compacted to just this
        batch. The ``autocompact`` rung uses this so cheap-phase summary
        accumulation cannot grow the prompt without bound.
        """
        if phase is not None and phase not in COMPRESSION_PHASES:
            raise ValueError(
                f"Unknown compression phase {phase!r}; "
                f"expected one of {COMPRESSION_PHASES}"
            )

        with self._locked(session_id):
            return self._compress_history_locked(
                session_id,
                summary,
                n,
                phase=phase,
                replace_compressed_context=replace_compressed_context,
            )

    def _compress_history_locked(
        self,
        session_id: str,
        summary: str,
        n: int,
        *,
        phase: str | None,
        replace_compressed_context: bool,
    ) -> tuple[int, int]:
        data = self._read(session_id)
        messages = _normalize_messages_for_storage(data.get("messages", []))

        archived = messages[:n]
        remaining = messages[n:]

        # Write archive file
        archive_id = str(time.time_ns())
        archive_path = self.archive_dir / f"{session_id}_{archive_id}.json"
        _atomic_write_text(
            archive_path, json.dumps(archived, ensure_ascii=False, indent=2)
        )

        # Update the on-disk sidecar so ``list_archived_history_batches`` can
        # answer without reading every file on subsequent calls.
        append_archive_entry(
            self.archive_dir, session_id, archive_id, len(archived)
        )

        if replace_compressed_context:
            # Autocompact rewrite: prior summaries are folded into ``summary``
            # by the caller, so the on-disk context collapses to a single
            # entry. Older archive files stay on disk (so
            # ``load_archived_history`` remains useful for audit), but the
            # in-session index only points at this new batch.
            data["compressed_context"] = summary.strip()
            data["compressed_archive_index"] = [
                {"archive_id": archive_id, "message_count": len(archived)}
            ]
        else:
            existing = data.get("compressed_context", "").strip()
            archive_index = _pad_archive_index(
                _normalize_archive_index(data.get("compressed_archive_index")),
                len(parse_compressed_context(existing)),
            )
            archive_index.append(
                {"archive_id": archive_id, "message_count": len(archived)}
            )
            data["compressed_context"] = append_compressed_summary(existing, summary)
            data["compressed_archive_index"] = archive_index

        data["messages"] = remaining
        # Always overwrite the stored phase so a later unphased compression
        # (e.g., ``auto_compress_if_needed``) clears the stale rung rather
        # than leaving a misleading value in session metadata.
        if phase is None:
            data.pop("context_compression_phase", None)
        else:
            data["context_compression_phase"] = phase
        self._write(session_id, data)

        return len(archived), len(remaining)

    def get_context_compression_phase(self, session_id: str) -> str | None:
        """Return the most recent compaction phase applied to *session_id*."""
        value = self._read(session_id).get("context_compression_phase")
        if isinstance(value, str) and value in COMPRESSION_PHASES:
            return value
        return None

    def get_compressed_context(self, session_id: str) -> str:
        return self._read(session_id).get("compressed_context", "")

    def get_compressed_summaries(self, session_id: str) -> list[dict]:
        summaries = parse_compressed_context(self.get_compressed_context(session_id))
        return [
            {
                "source_format": summary.source_format,
                "legacy_summary": summary.legacy_summary,
                "decisions_and_rationale": summary.decisions_and_rationale,
                "results_register": summary.results_register,
                "evidence_register": summary.evidence_register,
                "compliance_register": summary.compliance_register,
                "open_questions_and_next_actions": summary.open_questions_and_next_actions,
            }
            for summary in summaries
        ]

    def list_archived_history_batches(self, session_id: str) -> list[dict[str, Any]]:
        _validate_session_id(session_id)
        if not self._path(session_id).exists():
            return []

        return [
            {
                "archive_id": entry["archive_id"],
                "message_count": entry["message_count"],
            }
            for entry in list_archive_entries(self.archive_dir, session_id)
        ]

    def load_archived_history(self, session_id: str, archive_id: str) -> list[dict]:
        _validate_session_id(session_id)
        if not _ARCHIVE_ID_RE.match(archive_id):
            raise ValueError(f"Invalid archive_id: {archive_id!r}")
        if not self._path(session_id).exists():
            raise FileNotFoundError(self._path(session_id))

        path = self.archive_dir / f"{session_id}_{archive_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)

        raw_messages = json.loads(path.read_text(encoding="utf-8"))
        return _normalize_messages(raw_messages)

    def _resolve_archive_index_for_summaries(
        self, session_id: str, summaries: list[dict[str, Any]], data: dict[str, Any]
    ) -> list[SessionArchiveIndexEntry]:
        summary_count = len(summaries)
        if summary_count == 0:
            return []

        stored_index = _normalize_archive_index(data.get("compressed_archive_index"))
        if stored_index:
            return _pad_archive_index(stored_index, summary_count)

        batches = self.list_archived_history_batches(session_id)
        archive_index = [
            {"archive_id": batch["archive_id"], "message_count": batch["message_count"]}
            for batch in batches
        ]
        if len(archive_index) == summary_count:
            return archive_index

        leading_legacy_count = 0
        for summary in summaries:
            if summary.get("source_format") == "legacy":
                leading_legacy_count += 1
                continue
            break

        if leading_legacy_count and len(archive_index) == summary_count - leading_legacy_count:
            return [
                *(_empty_archive_index_entry() for _ in range(leading_legacy_count)),
                *archive_index,
            ]

        return [_empty_archive_index_entry() for _ in range(summary_count)]

    def get_session_continuity(self, session_id: str) -> list[dict[str, Any]]:
        data = self._read(session_id)
        summaries = self.get_compressed_summaries(session_id)
        archive_index = self._resolve_archive_index_for_summaries(session_id, summaries, data)
        continuity: list[dict[str, Any]] = []

        for summary, archive in zip(summaries, archive_index):
            continuity.append(
                {
                    **summary,
                    "archive_id": archive["archive_id"],
                    "archived_message_count": archive["message_count"],
                }
            )

        return continuity

    async def auto_compress_if_needed(
        self, session_id: str, llm, threshold: int = 40
    ) -> bool:
        """
        If the session has >= *threshold* messages, compress the oldest 50%.
        Uses *llm* to generate a concise summary (same logic as the manual
        /compress endpoint). Returns True if compression was performed.
        Non-fatal: any LLM failure silently skips compression.

        A per-session asyncio.Lock prevents concurrent requests from compressing
        the same session simultaneously (which would double-archive messages).
        """
        async with self.get_or_create_compress_lock(session_id):
            return await self._do_compress_if_needed(session_id, llm, threshold)

    async def _do_compress_if_needed(
        self, session_id: str, llm, threshold: int
    ) -> bool:
        """Inner compress logic — must be called with the session lock held."""
        data = self._read(session_id)
        messages = self.load_session(session_id)

        if len(messages) < threshold:
            return False

        n = max(4, len(messages) // 2)
        to_compress = messages[:n]

        try:
            summary = await generate_structured_summary(to_compress, llm)
        except Exception:
            return False  # non-fatal — skip compression this turn

        self.compress_history(session_id, summary, n)
        return True
