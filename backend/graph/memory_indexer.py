import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from .memory_types import (
    ParsedMemoryDocument,
    TypedMemoryMetadata,
    default_scope_for_kind,
    display_memory_type,
    infer_kind_from_source,
    parse_memory_document,
)

logger = logging.getLogger(__name__)

# Hard cap on chars per-file entry rendered in the LLM-probe file index. Keeps
# one oversized description from starving the rest of the corpus listing.
_PROBE_INDEX_ENTRY_CHARS = 280
# How many files the probe LLM is asked to return at most. Results feed the
# same retrieved-memory block as keyword RAG, so the cap mirrors the typical
# `top_k=3-5` used by `retrieve()`.
_PROBE_DEFAULT_TOP_K = 5

_TEXT_MEMORY_SUFFIXES = {".md", ".markdown", ".txt"}
_MARKDOWN_MEMORY_SUFFIXES = {".md", ".markdown"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_MAX_RESULT_TEXT_CHARS = 320
# Sections with fewer body chars than this are folded into their parent
# heading's section so long files do not fragment into thousands of tiny
# entries. Measured on the body *excluding* the section's own heading line.
_SMALL_SECTION_BODY_THRESHOLD = 300
_DEFAULT_MAX_SECTIONS_PER_FILE = 64
_LEXICAL_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "how",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "use",
    "with",
}


@dataclass(frozen=True)
class _MemorySection:
    source: str
    text: str
    search_text: str
    memory_type: str | None = None
    memory_name: str | None = None
    memory_description: str | None = None
    memory_kind: str | None = None
    memory_scope: str | None = None
    memory_tags: tuple[str, ...] = ()


def _truncate_entry(text: str, max_chars: int) -> tuple[str, bool]:
    """Cap a probe-index entry line; returns ``(maybe_truncated, was_truncated)``."""
    if len(text) <= max_chars:
        return text, False
    return text[: max_chars - 3].rstrip() + "...", True


def _normalize_filter_values(value: Any) -> set[str] | None:
    """Coerce a single string or iterable of strings into a lowercase set; None -> no filter."""
    if value is None:
        return None
    if isinstance(value, str):
        token = value.strip().lower()
        return {token} if token else None
    try:
        tokens = {str(item).strip().lower() for item in value}
    except TypeError:
        return None
    tokens.discard("")
    return tokens or None


class MemoryIndexer:
    """
    Manages a LlamaIndex vector index over text files under memory/.
    Rebuilds automatically when the memory directory state changes.
    Index is persisted to storage/memory_index/ between restarts.
    Uses BM25 + vector hybrid retrieval.
    """

    def __init__(
        self,
        base_dir: Path,
        *,
        max_sections_per_file: int | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.memory_dir = base_dir / "memory"
        self.memory_path = self.memory_dir / "MEMORY.md"
        self._storage_path = base_dir / "storage" / "memory_index"
        self._index: Optional[Any] = None
        self._nodes: list = []
        self._sections: list[_MemorySection] = []
        self._last_md5: str = ""
        # Upper bound on the sections produced per markdown file. Invalid or
        # non-positive values fall back to the built-in default so a
        # misconfigured value can never disable indexing entirely.
        try:
            cap = (
                int(max_sections_per_file)
                if max_sections_per_file is not None
                else _DEFAULT_MAX_SECTIONS_PER_FILE
            )
        except (TypeError, ValueError):
            cap = _DEFAULT_MAX_SECTIONS_PER_FILE
        self._max_sections_per_file = (
            cap if cap >= 1 else _DEFAULT_MAX_SECTIONS_PER_FILE
        )
        # Per-file state map: file source (relative posix path) ->
        # (mtime, size, md5). Drives the incremental diff in `_maybe_rebuild`
        # so we only re-embed the files that actually changed since last scan.
        self._file_states: dict[str, tuple[float, int, str]] = {}
        # file source -> sections currently indexed for that file. Lets us
        # locate the stale doc_ids to delete when a file is removed or edited.
        self._file_sections: dict[str, list[_MemorySection]] = {}
        # (session_id, corpus_digest) -> cached probe-selected source paths.
        # In-process only: invalidates on restart and whenever the memory
        # corpus digest changes (i.e. any file added/modified/removed).
        self._probe_cache: dict[tuple[str, str], list[str]] = {}
        # Background rebuild coordination. `_schedule_lock` guards the
        # `_rebuild_in_flight` flag so concurrent `_maybe_rebuild` callers
        # coalesce to a single worker rather than queueing duplicates.
        # `_rebuild_thread` is retained so callers (tests, shutdown paths) can
        # join the worker when they need deterministic completion.
        self._schedule_lock = threading.Lock()
        self._rebuild_in_flight: bool = False
        self._rebuild_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _relative_source(self, path: Path) -> str:
        return path.relative_to(self.base_dir).as_posix()

    def _memory_files(self) -> list[Path]:
        if not self.memory_dir.exists():
            return []

        memory_files: list[Path] = []
        for path in sorted(
            self.memory_dir.rglob("*"),
            key=lambda candidate: candidate.relative_to(self.memory_dir).as_posix(),
        ):
            if not path.is_file():
                continue

            relative_path = path.relative_to(self.memory_dir)
            if any(part.startswith(".") for part in relative_path.parts):
                continue

            if relative_path.name != "MEMORY.md" and len(relative_path.parts) == 1:
                continue

            if path.suffix.lower() not in _TEXT_MEMORY_SUFFIXES:
                continue

            memory_files.append(path)

        return memory_files

    def _parsed_memory_documents(self) -> list[ParsedMemoryDocument]:
        documents: list[ParsedMemoryDocument] = []
        for path in self._memory_files():
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue

            parsed = parse_memory_document(self._relative_source(path), content)
            if not parsed.body:
                continue

            documents.append(parsed)

        return documents

    def _memory_documents(self) -> list[tuple[str, str]]:
        return [
            (document.source, document.body)
            for document in self._parsed_memory_documents()
        ]

    def _split_document_sections(
        self,
        document: ParsedMemoryDocument,
    ) -> list[_MemorySection]:
        suffix = Path(document.source).suffix.lower()
        inferred_kind = infer_kind_from_source(document.source)
        if suffix not in _MARKDOWN_MEMORY_SUFFIXES:
            return [
                self._build_section(
                    document.source,
                    document.body,
                    document.metadata,
                    inferred_kind=inferred_kind,
                )
            ]

        # Parse markdown into a flat list of heading-scoped entries. Level 0
        # is the pre-heading body (if any); levels 1–6 track H1–H6. Entries
        # stay addressable by index so the merge passes below can collapse a
        # child into its parent without reshuffling the list.
        entries: list[dict[str, Any]] = []
        current_level = 0
        current_heading: str | None = None
        current_lines: list[str] = []

        def _flush_entry() -> None:
            if not any(line.strip() for line in current_lines):
                return
            entries.append(
                {
                    "level": current_level,
                    "heading": current_heading,
                    "lines": list(current_lines),
                    "alive": True,
                }
            )

        for line in document.body.splitlines():
            heading_match = _MARKDOWN_HEADING_RE.match(line.strip())
            if heading_match:
                _flush_entry()
                current_level = len(heading_match.group(1))
                current_heading = heading_match.group(2).strip()
                current_lines = [line]
                continue

            if not current_lines and not line.strip():
                continue
            current_lines.append(line)

        _flush_entry()

        self._merge_small_and_overflow_entries(entries)

        raw_sections: list[_MemorySection] = []
        for entry in entries:
            if not entry["alive"]:
                continue
            text = "\n".join(entry["lines"]).strip()
            if not text:
                continue
            section_source = document.source
            heading = entry["heading"]
            if heading:
                anchor = self._slugify_heading(heading)
                if anchor:
                    section_source = f"{document.source}#{anchor}"
            raw_sections.append(
                self._build_section(
                    section_source,
                    text,
                    document.metadata,
                    inferred_kind=inferred_kind,
                )
            )

        if not raw_sections:
            return [
                self._build_section(
                    document.source,
                    document.body,
                    document.metadata,
                    inferred_kind=inferred_kind,
                )
            ]

        deduped_sections: list[_MemorySection] = []
        seen_sources: dict[str, int] = {}
        for section in raw_sections:
            occurrence = seen_sources.get(section.source, 0) + 1
            seen_sources[section.source] = occurrence
            if occurrence > 1:
                metadata_copy: TypedMemoryMetadata | None = None
                if (
                    section.memory_type is not None
                    and section.memory_name is not None
                    and section.memory_description is not None
                ):
                    metadata_copy = TypedMemoryMetadata(
                        memory_type=section.memory_type,
                        name=section.memory_name,
                        description=section.memory_description,
                        kind=section.memory_kind,
                        scope=section.memory_scope,
                        tags=section.memory_tags,
                    )
                deduped_sections.append(
                    self._build_section(
                        f"{section.source}-{occurrence}",
                        section.text,
                        metadata_copy,
                        inferred_kind=inferred_kind,
                    )
                )
                continue
            deduped_sections.append(section)

        return deduped_sections

    def _merge_small_and_overflow_entries(
        self, entries: list[dict[str, Any]]
    ) -> None:
        """Collapse tiny child entries into their parent heading's entry.

        Two passes, each mutating ``entries`` in place:

        1. Fold any child whose body is shorter than
           ``_SMALL_SECTION_BODY_THRESHOLD`` (measured on the lines *after*
           its own heading) into the nearest alive ancestor at a shallower
           heading level. This is the common case that prevents a file with
           many one-liner H3s / H4s from fragmenting.
        2. If the surviving entry count still exceeds
           ``self._max_sections_per_file``, repeatedly merge the shortest
           remaining child into its parent (breaking ties by preferring
           deeper headings so top-level structure is preserved last).
        """
        if not entries:
            return

        def _body_chars(entry: dict[str, Any]) -> int:
            lines = entry["lines"]
            start = 1 if entry["heading"] else 0
            return len("\n".join(lines[start:]).strip())

        def _alive_indices() -> list[int]:
            return [i for i, entry in enumerate(entries) if entry["alive"]]

        def _compute_parents(
            indices: list[int],
        ) -> dict[int, int | None]:
            parents: dict[int, int | None] = {}
            stack: list[tuple[int, int]] = []
            for i in indices:
                level = entries[i]["level"]
                while stack and stack[-1][1] >= level:
                    stack.pop()
                parents[i] = stack[-1][0] if stack else None
                stack.append((i, level))
            return parents

        def _merge_into_parent(child_idx: int, parent_idx: int) -> None:
            entries[parent_idx]["lines"] = (
                entries[parent_idx]["lines"] + entries[child_idx]["lines"]
            )
            entries[child_idx]["alive"] = False

        # Pass 1 — size-based fold. Re-run until a pass produces no merges so
        # a child orphaned by its parent's own merge still lands under the
        # correct surviving ancestor.
        changed = True
        while changed:
            changed = False
            indices = _alive_indices()
            parents = _compute_parents(indices)
            for i in indices:
                if not entries[i]["alive"]:
                    continue
                parent = parents.get(i)
                if parent is None or not entries[parent]["alive"]:
                    continue
                if _body_chars(entries[i]) < _SMALL_SECTION_BODY_THRESHOLD:
                    _merge_into_parent(i, parent)
                    changed = True

        # Pass 2 — cap enforcement. Only runs when the file is still over the
        # per-file cap after size folding.
        cap = self._max_sections_per_file
        indices = _alive_indices()
        while len(indices) > cap:
            parents = _compute_parents(indices)
            candidates = [i for i in indices if parents.get(i) is not None]
            if not candidates:
                break
            candidates.sort(
                key=lambda idx: (_body_chars(entries[idx]), -entries[idx]["level"])
            )
            chosen = candidates[0]
            _merge_into_parent(chosen, parents[chosen])
            indices = _alive_indices()

    def _memory_sections(self) -> list[_MemorySection]:
        sections: list[_MemorySection] = []
        for document in self._parsed_memory_documents():
            sections.extend(self._split_document_sections(document))
        return sections

    def _slugify_heading(self, heading: str) -> str:
        tokens = _TOKEN_RE.findall(heading.lower())
        return "-".join(tokens)

    def _build_section(
        self,
        source: str,
        text: str,
        metadata: TypedMemoryMetadata | None,
        *,
        inferred_kind: str | None = None,
    ) -> _MemorySection:
        search_parts = [source.lower(), self._normalize_text(text)]
        memory_type: str | None = None
        memory_name: str | None = None
        memory_description: str | None = None
        memory_kind: str | None = inferred_kind
        memory_scope: str | None = None
        memory_tags: tuple[str, ...] = ()

        if metadata is not None:
            memory_type = metadata.memory_type
            memory_name = metadata.name
            memory_description = metadata.description
            if metadata.kind:
                memory_kind = metadata.kind
            memory_scope = metadata.scope
            memory_tags = metadata.tags
            search_parts.extend(
                [
                    metadata.memory_type,
                    display_memory_type(metadata.memory_type),
                    self._normalize_text(metadata.name),
                    self._normalize_text(metadata.description),
                ]
            )
            if memory_tags:
                search_parts.append(" ".join(memory_tags))

        # Legacy files with no frontmatter still belong to a kind (by directory).
        # Give them the matching default scope so `retrieve(scope=kind)` behaves
        # the same for legacy and typed files.
        if memory_scope is None and memory_kind:
            memory_scope = default_scope_for_kind(memory_kind)

        return _MemorySection(
            source=source,
            text=text,
            search_text=" ".join(part for part in search_parts if part),
            memory_type=memory_type,
            memory_name=memory_name,
            memory_description=memory_description,
            memory_kind=memory_kind,
            memory_scope=memory_scope,
            memory_tags=memory_tags,
        )

    def _normalize_text(self, text: str) -> str:
        return " ".join(text.split()).strip().lower()

    def _typed_result_fields(
        self,
        *,
        memory_type: str | None,
        memory_name: str | None,
        memory_description: str | None,
        memory_kind: str | None = None,
        memory_scope: str | None = None,
        memory_tags: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if memory_type:
            fields["memory_type"] = memory_type
            fields["memory_type_label"] = display_memory_type(memory_type)
        if memory_name:
            fields["memory_name"] = memory_name
        if memory_description:
            fields["memory_description"] = memory_description
        if memory_kind:
            fields["memory_kind"] = memory_kind
        if memory_scope:
            fields["memory_scope"] = memory_scope
        if memory_tags:
            fields["memory_tags"] = list(memory_tags)
        return fields

    def _section_matches_filters(
        self,
        section_kind: str | None,
        section_scope: str | None,
        section_tags: Iterable[str],
        *,
        kind_filter: set[str] | None,
        scope_filter: set[str] | None,
        tag_filter: set[str] | None,
    ) -> bool:
        if kind_filter is not None:
            if not section_kind or section_kind not in kind_filter:
                return False
        if scope_filter is not None:
            if not section_scope or section_scope not in scope_filter:
                return False
        if tag_filter is not None:
            section_tag_set = {tag.lower() for tag in section_tags or ()}
            if not section_tag_set.intersection(tag_filter):
                return False
        return True

    def _summarize_text(self, text: str) -> str:
        normalized = " ".join(text.split()).strip()
        if len(normalized) <= _MAX_RESULT_TEXT_CHARS:
            return normalized
        return normalized[: _MAX_RESULT_TEXT_CHARS - 3].rstrip() + "..."

    def _query_terms(self, query: str) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for token in _TOKEN_RE.findall(query.lower()):
            if token in _LEXICAL_STOPWORDS:
                continue
            if len(token) < 2:
                continue
            if token in seen:
                continue
            seen.add(token)
            terms.append(token)
        return terms

    def _lexical_results(
        self,
        query: str,
        top_k: int,
        *,
        kind_filter: set[str] | None = None,
        scope_filter: set[str] | None = None,
        tag_filter: set[str] | None = None,
    ) -> list[dict]:
        terms = self._query_terms(query)
        if not terms:
            return []

        scored_results: list[dict[str, Any]] = []
        phrase = " ".join(terms)
        for section in self._sections:
            if not self._section_matches_filters(
                section.memory_kind,
                section.memory_scope,
                section.memory_tags,
                kind_filter=kind_filter,
                scope_filter=scope_filter,
                tag_filter=tag_filter,
            ):
                continue
            matched_terms = [term for term in terms if term in section.search_text]
            if not matched_terms:
                continue

            score = len(matched_terms) / len(terms)
            score += sum(section.search_text.count(term) for term in matched_terms) * 0.05
            if phrase and phrase in section.search_text:
                score += 0.35

            scored_results.append(
                {
                    "text": self._summarize_text(section.text),
                    "score": round(score, 4),
                    "source": section.source,
                    **self._typed_result_fields(
                        memory_type=section.memory_type,
                        memory_name=section.memory_name,
                        memory_description=section.memory_description,
                        memory_kind=section.memory_kind,
                        memory_scope=section.memory_scope,
                        memory_tags=section.memory_tags,
                    ),
                }
            )

        scored_results.sort(key=lambda item: item["score"], reverse=True)
        return scored_results[:top_k]

    def _memory_state_map(self) -> dict[str, tuple[float, int, str]]:
        """Walk `memory/` and return {source: (mtime, size, md5)} per eligible file.

        Reuses `self._file_states` as a cache: when a file's mtime and size both
        match the prior scan, the cached md5 is trusted and the file is not
        re-read. This turns the common "no change" path into an O(N) stat scan
        instead of an O(N) content hash.
        """
        states: dict[str, tuple[float, int, str]] = {}
        cache = self._file_states
        for path in self._memory_files():
            try:
                stat_result = path.stat()
            except OSError:
                continue
            source = self._relative_source(path)
            cached = cache.get(source)
            if (
                cached is not None
                and cached[0] == stat_result.st_mtime
                and cached[1] == stat_result.st_size
            ):
                states[source] = cached
                continue
            try:
                content = path.read_bytes()
            except OSError:
                continue
            file_md5 = hashlib.md5(content).hexdigest()
            states[source] = (stat_result.st_mtime, stat_result.st_size, file_md5)
        return states

    def _digest_state_map(
        self, state_map: dict[str, tuple[float, int, str]]
    ) -> str:
        """Combine per-file md5s into a single stable digest over the corpus."""
        if not state_map:
            return ""
        digest = hashlib.md5()
        for source in sorted(state_map):
            _, _, file_md5 = state_map[source]
            digest.update(source.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_md5.encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    def _memory_state_md5(self) -> str:
        """Back-compat helper — returns the corpus-wide digest, or "" if empty."""
        return self._digest_state_map(self._memory_state_map())

    def _diff_state_maps(
        self,
        old: dict[str, tuple[float, int, str]],
        new: dict[str, tuple[float, int, str]],
    ) -> tuple[set[str], set[str], set[str]]:
        old_keys = set(old)
        new_keys = set(new)
        added = new_keys - old_keys
        removed = old_keys - new_keys
        modified = {
            source
            for source in (old_keys & new_keys)
            if old[source][2] != new[source][2]
        }
        return added, modified, removed

    def _file_source_from_section(self, section: _MemorySection) -> str:
        """Section sources are `<file>` or `<file>#<anchor>[-N]`; strip the anchor."""
        return section.source.split("#", 1)[0]

    def _group_sections_by_file(
        self, sections: list[_MemorySection]
    ) -> dict[str, list[_MemorySection]]:
        grouped: dict[str, list[_MemorySection]] = {}
        for section in sections:
            grouped.setdefault(self._file_source_from_section(section), []).append(
                section
            )
        return grouped

    def _section_to_document(self, Document: Any, section: _MemorySection) -> Any:
        metadata: dict[str, Any] = {"source": section.source}
        if section.memory_type:
            metadata["memory_type"] = section.memory_type
        if section.memory_name:
            metadata["memory_name"] = section.memory_name
        if section.memory_description:
            metadata["memory_description"] = section.memory_description
        if section.memory_kind:
            metadata["memory_kind"] = section.memory_kind
        if section.memory_scope:
            metadata["memory_scope"] = section.memory_scope
        if section.memory_tags:
            metadata["memory_tags"] = list(section.memory_tags)
        # Using `section.source` as the doc_id is what lets us call
        # `index.delete_ref_doc(section.source)` during incremental updates.
        return Document(text=section.text, metadata=metadata, doc_id=section.source)

    def _persist_state_map(self) -> None:
        try:
            self._storage_path.mkdir(parents=True, exist_ok=True)
            payload = {
                source: [mtime, size, file_md5]
                for source, (mtime, size, file_md5) in self._file_states.items()
            }
            (self._storage_path / "state.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        except OSError:
            pass

    def _load_persisted_state_map(self) -> dict[str, tuple[float, int, str]]:
        state_file = self._storage_path / "state.json"
        try:
            raw = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        loaded: dict[str, tuple[float, int, str]] = {}
        for source, entry in (raw or {}).items():
            try:
                mtime, size, file_md5 = entry
                loaded[str(source)] = (float(mtime), int(size), str(file_md5))
            except (TypeError, ValueError):
                continue
        return loaded

    def _maybe_rebuild(self) -> None:
        current_map = self._memory_state_map()
        current_digest = self._digest_state_map(current_map)
        if current_digest == self._last_md5:
            return
        # First-ever build (cold start or empty state) — hand off to the full
        # rebuild path so the persisted-index fast-load has a chance to run.
        # The cold path must block: callers have no retrievable state yet.
        if not self._file_states or self._index is None and not self._sections:
            self.rebuild_index(
                current_map=current_map, current_digest=current_digest
            )
            return
        # Warm-cache path: hand the diff-and-update work to a single daemon
        # worker so the calling agent turn does not block on a re-embed of a
        # large corpus change. Readers keep serving the current (now-stale)
        # sections/index/nodes until the worker commits the new state.
        with self._schedule_lock:
            if self._rebuild_in_flight:
                # A worker is already handling the divergence. It re-scans on
                # entry, so any change that arrived between scheduling and
                # worker start is picked up there; otherwise the next
                # `_maybe_rebuild` call after the worker exits will catch it.
                return
            self._rebuild_in_flight = True
            thread = threading.Thread(
                target=self._run_background_rebuild,
                name="memory-indexer-rebuild",
                daemon=True,
            )
            self._rebuild_thread = thread
        thread.start()

    def _run_background_rebuild(self) -> None:
        try:
            current_map = self._memory_state_map()
            current_digest = self._digest_state_map(current_map)
            if current_digest == self._last_md5:
                return
            added, modified, removed = self._diff_state_maps(
                self._file_states, current_map
            )
            if not (added or modified or removed):
                self._file_states = dict(current_map)
                self._last_md5 = current_digest
                return
            self._apply_incremental_update(
                added=added,
                modified=modified,
                removed=removed,
                current_map=current_map,
                current_digest=current_digest,
            )
        except Exception:
            # `_last_md5` / `_file_states` are only updated at the tail of
            # `_apply_incremental_update`, so an exception above leaves the
            # existing snapshot intact. The next `_maybe_rebuild` call will
            # see a divergent digest and schedule another attempt.
            logger.exception("Background memory-index rebuild failed")
        finally:
            with self._schedule_lock:
                self._rebuild_in_flight = False

    def _apply_incremental_update(
        self,
        *,
        added: set[str],
        modified: set[str],
        removed: set[str],
        current_map: dict[str, tuple[float, int, str]],
        current_digest: str,
    ) -> None:
        """Surgically patch `_sections`, `_file_sections`, and the vector index."""
        stale_files = removed | modified
        fresh_files = added | modified

        # Parse only the files that changed. Malformed frontmatter is logged
        # inline (mirroring rebuild_index's _log_malformed_documents behavior)
        # so downstream reviewers still see bad files without paying a full
        # corpus scan per write.
        new_sections_by_file: dict[str, list[_MemorySection]] = {}
        for source in fresh_files:
            path = self.base_dir / source
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            parsed = parse_memory_document(source, content)
            if parsed.errors:
                logger.warning(
                    "Malformed typed memory file %s: %s",
                    parsed.source,
                    "; ".join(parsed.errors),
                )
            if not parsed.body:
                new_sections_by_file[source] = []
                continue
            new_sections_by_file[source] = self._split_document_sections(parsed)

        # Collect sections to remove *before* we mutate _file_sections so we
        # can issue the matching `delete_ref_doc` calls against the index.
        sections_to_delete: list[_MemorySection] = []
        for source in stale_files:
            sections_to_delete.extend(self._file_sections.get(source, []))

        for source in stale_files:
            self._file_sections.pop(source, None)
        for source, sections in new_sections_by_file.items():
            if sections:
                self._file_sections[source] = sections

        # Rebuild the flat section list in deterministic (file-sorted) order so
        # retrieval behavior matches what rebuild_index would produce.
        flat_sections: list[_MemorySection] = []
        for file_source in sorted(self._file_sections):
            flat_sections.extend(self._file_sections[file_source])
        self._sections = flat_sections

        new_sections_flat: list[_MemorySection] = []
        for source in fresh_files:
            new_sections_flat.extend(new_sections_by_file.get(source, []))

        if self._index is not None and (sections_to_delete or new_sections_flat):
            try:
                from llama_index.core import Document
            except Exception:
                # LlamaIndex disappeared between the initial build and now —
                # fall back to lexical-only retrieval without crashing.
                self._index = None
                self._nodes = []
            else:
                for section in sections_to_delete:
                    try:
                        self._index.delete_ref_doc(
                            section.source, delete_from_docstore=True
                        )
                    except Exception:
                        # Best-effort: if a doc was never embedded (e.g.
                        # previous insert failed) the delete is a no-op.
                        pass
                if new_sections_flat:
                    try:
                        for section in new_sections_flat:
                            doc = self._section_to_document(Document, section)
                            self._index.insert(doc)
                    except Exception:
                        # Embedding backend unavailable — drop the index so
                        # retrieval falls back to the lexical path and the
                        # next cold start triggers a full rebuild.
                        self._index = None
                        self._nodes = []
                if self._index is not None:
                    try:
                        self._index.storage_context.persist(
                            persist_dir=str(self._storage_path)
                        )
                        (self._storage_path / "md5.txt").write_text(
                            current_digest, encoding="utf-8"
                        )
                    except Exception:
                        pass
                    try:
                        self._nodes = list(self._index.docstore.docs.values())
                    except Exception:
                        pass

        self._file_states = dict(current_map)
        self._last_md5 = current_digest
        if self._index is not None:
            self._persist_state_map()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def _log_malformed_documents(self) -> None:
        """
        Walk memory/ at rebuild time and log any files with malformed typed-memory
        frontmatter. The backend keeps booting — misconfigured files are skipped
        from typed-section indexing but their body text is still retrievable.
        """
        for path in self._memory_files():
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                continue
            parsed = parse_memory_document(self._relative_source(path), content)
            if parsed.errors:
                logger.warning(
                    "Malformed typed memory file %s: %s",
                    parsed.source,
                    "; ".join(parsed.errors),
                )

    def rebuild_index(
        self,
        *,
        current_map: dict[str, tuple[float, int, str]] | None = None,
        current_digest: str | None = None,
    ) -> None:
        """
        Build a VectorStoreIndex from memory/ documents and persist to storage/memory_index/.

        Fast path: if the persisted index exists and its stored MD5 matches the current
        memory state, load from disk (no re-embedding). Slow path: parse, embed, persist.

        Callers may pass a pre-computed `current_map` / `current_digest` (as done from
        `_maybe_rebuild`) to avoid walking the memory tree twice.
        """
        if current_map is None:
            current_map = self._memory_state_map()
        if current_digest is None:
            current_digest = self._digest_state_map(current_map)
        md5_file = self._storage_path / "md5.txt"

        self._log_malformed_documents()

        sections = self._memory_sections()
        self._sections = sections
        self._file_sections = self._group_sections_by_file(sections)
        if not sections:
            self._index = None
            self._nodes = []
            self._file_states = dict(current_map)
            self._last_md5 = current_digest
            return

        # Record the observed file hash before optional indexing work so callers
        # do not repeatedly retrigger rebuild attempts when LlamaIndex or the
        # embedding backend is unavailable.
        self._index = None
        self._nodes = []
        self._file_states = dict(current_map)
        self._last_md5 = current_digest

        try:
            from llama_index.core import (
                Document,
                StorageContext,
                VectorStoreIndex,
                load_index_from_storage,
            )
            from llama_index.core.node_parser import SentenceSplitter
        except Exception:
            return

        # ── Fast path: load persisted index if file hasn't changed ────────
        if self._storage_path.exists() and md5_file.exists():
            if md5_file.read_text(encoding="utf-8").strip() == current_digest:
                try:
                    storage_context = StorageContext.from_defaults(
                        persist_dir=str(self._storage_path)
                    )
                    self._index = load_index_from_storage(storage_context)
                    self._nodes = list(self._index.docstore.docs.values())
                    # Prefer the persisted per-file state (it was written
                    # atomically with the index) so stat values round-trip
                    # exactly across restarts.
                    persisted_state = self._load_persisted_state_map()
                    if persisted_state:
                        self._file_states = persisted_state
                    return
                except Exception:
                    pass  # Fall through to full rebuild

        docs = [self._section_to_document(Document, section) for section in sections]
        splitter = SentenceSplitter(chunk_size=256, chunk_overlap=32)
        self._nodes = splitter.get_nodes_from_documents(docs)

        if self._nodes:
            try:
                self._storage_path.mkdir(parents=True, exist_ok=True)
                storage_context = StorageContext.from_defaults()
                self._index = VectorStoreIndex(self._nodes, storage_context=storage_context)
                self._index.storage_context.persist(persist_dir=str(self._storage_path))
                md5_file.write_text(current_digest, encoding="utf-8")
                self._persist_state_map()
            except Exception:
                # Missing embeddings or transient index-storage failures should not
                # block lexical/BM25 memory retrieval for the current turn.
                self._index = None

    # ------------------------------------------------------------------ #
    # LLM-probe retrieval                                                  #
    # ------------------------------------------------------------------ #

    def memory_file_count(self) -> int:
        """Return the number of eligible memory files currently on disk."""
        return len(self._memory_files())

    def memory_corpus_digest(self) -> str:
        """Return the stable digest used as the probe-cache invalidation key."""
        return self._memory_state_md5()

    def build_probe_index(self, *, max_chars: int) -> tuple[str, list[str]]:
        """Render a compact ``<source> — <name>: <description>`` listing for the probe LLM.

        Returns ``(rendered_index, valid_sources)`` where ``valid_sources`` is
        the list of file paths actually included in the listing (after the
        char budget). The caller sends ``rendered_index`` to the probe and
        constrains parsed results to ``valid_sources`` to reject hallucinated
        paths.
        """
        self._maybe_rebuild()
        documents = self._parsed_memory_documents()
        lines: list[str] = []
        valid_sources: list[str] = []
        total_chars = 0
        for document in documents:
            source = document.source
            metadata = document.metadata
            name = metadata.name.strip() if metadata and metadata.name else ""
            description = (
                metadata.description.strip()
                if metadata and metadata.description
                else ""
            )
            entry = f"- {source}"
            if name:
                entry += f" — {name}"
            if description:
                entry += f": {description}"
            entry, _ = _truncate_entry(entry, _PROBE_INDEX_ENTRY_CHARS)
            # +1 for the newline separator we will join with below.
            if total_chars + len(entry) + 1 > max_chars and lines:
                break
            lines.append(entry)
            valid_sources.append(source)
            total_chars += len(entry) + 1
        return "\n".join(lines), valid_sources

    def parse_probe_selection(
        self,
        response_text: str,
        valid_sources: list[str],
        *,
        top_k: int = _PROBE_DEFAULT_TOP_K,
    ) -> list[str]:
        """Extract a list of source paths from the probe LLM's response.

        Accepts a JSON array embedded anywhere in ``response_text``. Falls
        back to scanning every non-empty line for a known source path from
        ``valid_sources`` so lightweight / non-JSON-native models still work.
        Unknown (hallucinated) paths are filtered out. The result is
        deduplicated and capped at ``top_k`` entries preserving the model's
        ordering.
        """
        if not response_text or not valid_sources:
            return []
        valid_set = set(valid_sources)
        picked: list[str] = []

        def _extend(candidates: Iterable[Any]) -> None:
            for candidate in candidates:
                if not isinstance(candidate, str):
                    continue
                normalized = candidate.strip().strip("`\"' ,")
                if normalized in valid_set and normalized not in picked:
                    picked.append(normalized)
                    if len(picked) >= top_k:
                        return

        match = re.search(r"\[(?:[^\[\]]|\n)*\]", response_text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, list):
                _extend(parsed)
                if picked:
                    return picked[:top_k]

        # Fallback: scan the full response for any valid source path. Preserve
        # first-occurrence order so a numbered / bulleted list still ranks.
        for source in sorted(valid_sources, key=len, reverse=True):
            if source in response_text and source not in picked:
                picked.append(source)
                if len(picked) >= top_k:
                    break
        # Re-sort by first-appearance position so the model's ordering wins.
        picked.sort(key=lambda s: response_text.find(s))
        return picked[:top_k]

    def build_probe_results(self, sources: list[str]) -> list[dict]:
        """Turn probe-selected source paths into the same result shape ``retrieve()`` emits.

        Each returned dict mirrors the ``build_retrieved_memory_block`` input
        contract (``text``, ``score``, ``source``, plus typed-memory fields)
        so the downstream prompt-assembly path is identical to keyword RAG.
        The synthetic ``score`` decays by probe rank so callers that sort by
        score preserve the model's ordering.
        """
        if not sources:
            return []
        first_section_by_file: dict[str, _MemorySection] = {}
        for section in self._sections:
            file_source = self._file_source_from_section(section)
            first_section_by_file.setdefault(file_source, section)

        results: list[dict] = []
        total = len(sources)
        for rank, source in enumerate(sources):
            section = first_section_by_file.get(source)
            if section is None:
                continue
            score = round(1.0 - rank / max(total, 1) * 0.1, 4)
            result: dict[str, Any] = {
                "text": self._summarize_text(section.text),
                "score": score,
                "source": section.source,
            }
            result.update(
                self._typed_result_fields(
                    memory_type=section.memory_type,
                    memory_name=section.memory_name,
                    memory_description=section.memory_description,
                    memory_kind=section.memory_kind,
                    memory_scope=section.memory_scope,
                    memory_tags=section.memory_tags,
                )
            )
            results.append(result)
        return results

    def get_cached_probe_selection(
        self, session_id: str, corpus_digest: str
    ) -> list[str] | None:
        """Return cached source paths for (session_id, digest), or None on miss."""
        if not session_id:
            return None
        return self._probe_cache.get((session_id, corpus_digest))

    def cache_probe_selection(
        self, session_id: str, corpus_digest: str, sources: list[str]
    ) -> None:
        """Cache the probe's pick for this session + corpus digest."""
        if not session_id or not sources:
            return
        self._probe_cache[(session_id, corpus_digest)] = list(sources)

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        *,
        kind: str | Iterable[str] | None = None,
        scope: str | Iterable[str] | None = None,
        tags: str | Iterable[str] | None = None,
    ) -> list[dict]:
        """
        Hybrid BM25 + vector retrieval.

        Results are deduplicated by source and returned up to top_k, sorted by score.
        Each result dict carries typed-memory fields when the source has frontmatter:
        `memory_type`, `memory_type_label`, `memory_name`, `memory_description`,
        `memory_kind`, `memory_scope`, `memory_tags`.

        Optional filters (all default to no filtering):
          * `kind` — one of or an iterable over {'project', 'user', 'agent'}.
          * `scope` — one of or an iterable over {'session', 'project', 'user', 'global'}.
          * `tags` — one tag or an iterable of tags; a section matches when its tag set
            intersects the filter set.
        """
        self._maybe_rebuild()

        if not self._sections and (self._index is None or not self._nodes):
            return []

        kind_filter = _normalize_filter_values(kind)
        scope_filter = _normalize_filter_values(scope)
        tag_filter = _normalize_filter_values(tags)

        results_by_source: dict[str, dict[str, Any]] = {}

        def _coerce_tag_list(raw: Any) -> list[str]:
            if isinstance(raw, list):
                return [str(item) for item in raw if str(item).strip()]
            return []

        def remember_result(
            text: str,
            score: float,
            source: str,
            *,
            memory_type: str | None = None,
            memory_name: str | None = None,
            memory_description: str | None = None,
            memory_kind: str | None = None,
            memory_scope: str | None = None,
            memory_tags: tuple[str, ...] | list[str] | None = None,
        ) -> None:
            if not source:
                return
            summarized_text = self._summarize_text(text)
            if not summarized_text:
                return

            effective_kind = memory_kind or infer_kind_from_source(source)
            effective_scope = memory_scope or default_scope_for_kind(effective_kind)
            tag_list = list(memory_tags or ())
            if not self._section_matches_filters(
                effective_kind,
                effective_scope,
                tag_list,
                kind_filter=kind_filter,
                scope_filter=scope_filter,
                tag_filter=tag_filter,
            ):
                return

            existing = results_by_source.get(source)
            normalized_score = float(score or 0.0)
            typed_fields = self._typed_result_fields(
                memory_type=memory_type,
                memory_name=memory_name,
                memory_description=memory_description,
                memory_kind=effective_kind,
                memory_scope=effective_scope,
                memory_tags=tag_list,
            )
            if existing is not None and normalized_score <= float(existing["score"]):
                if typed_fields and not all(key in existing for key in typed_fields):
                    existing.update(typed_fields)
                return
            updated_result = {
                "text": summarized_text,
                "score": normalized_score,
                "source": source,
            }
            updated_result.update(typed_fields)
            if existing is not None:
                for key, value in existing.items():
                    if key not in updated_result and key.startswith("memory_"):
                        updated_result[key] = value
            results_by_source[source] = updated_result

        def _node_kwargs(node_metadata: dict[str, Any]) -> dict[str, Any]:
            return {
                "memory_type": (
                    str(node_metadata["memory_type"])
                    if node_metadata.get("memory_type")
                    else None
                ),
                "memory_name": (
                    str(node_metadata["memory_name"])
                    if node_metadata.get("memory_name")
                    else None
                ),
                "memory_description": (
                    str(node_metadata["memory_description"])
                    if node_metadata.get("memory_description")
                    else None
                ),
                "memory_kind": (
                    str(node_metadata["memory_kind"])
                    if node_metadata.get("memory_kind")
                    else None
                ),
                "memory_scope": (
                    str(node_metadata["memory_scope"])
                    if node_metadata.get("memory_scope")
                    else None
                ),
                "memory_tags": _coerce_tag_list(node_metadata.get("memory_tags")),
            }

        # Vector retrieval
        if self._index is not None and self._nodes:
            try:
                vector_retriever = self._index.as_retriever(similarity_top_k=top_k)
                for node in vector_retriever.retrieve(query):
                    remember_result(
                        node.text,
                        float(node.score or 0.0),
                        str(node.metadata.get("source", "memory/MEMORY.md")),
                        **_node_kwargs(node.metadata),
                    )
            except Exception:
                pass

        # BM25 retrieval
        if self._nodes:
            try:
                from llama_index.retrievers.bm25 import BM25Retriever

                bm25 = BM25Retriever.from_defaults(nodes=self._nodes, similarity_top_k=top_k)
                for node in bm25.retrieve(query):
                    remember_result(
                        node.text,
                        float(node.score or 0.0),
                        str(node.metadata.get("source", "memory/MEMORY.md")),
                        **_node_kwargs(node.metadata),
                    )
            except Exception:
                pass

        for result in self._lexical_results(
            query,
            top_k=max(top_k * 2, top_k),
            kind_filter=kind_filter,
            scope_filter=scope_filter,
            tag_filter=tag_filter,
        ):
            remember_result(
                str(result["text"]),
                float(result["score"]),
                str(result["source"]),
                memory_type=(
                    str(result["memory_type"])
                    if result.get("memory_type")
                    else None
                ),
                memory_name=(
                    str(result["memory_name"])
                    if result.get("memory_name")
                    else None
                ),
                memory_description=(
                    str(result["memory_description"])
                    if result.get("memory_description")
                    else None
                ),
                memory_kind=(
                    str(result["memory_kind"])
                    if result.get("memory_kind")
                    else None
                ),
                memory_scope=(
                    str(result["memory_scope"])
                    if result.get("memory_scope")
                    else None
                ),
                memory_tags=_coerce_tag_list(result.get("memory_tags")),
            )

        # Return up to top_k, sorted by score descending
        results = sorted(
            results_by_source.values(),
            key=lambda item: item["score"],
            reverse=True,
        )
        return results[:top_k]
