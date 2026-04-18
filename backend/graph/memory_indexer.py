import hashlib
import logging
import re
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

_TEXT_MEMORY_SUFFIXES = {".md", ".markdown", ".txt"}
_MARKDOWN_MEMORY_SUFFIXES = {".md", ".markdown"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_MAX_RESULT_TEXT_CHARS = 320
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

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.memory_dir = base_dir / "memory"
        self.memory_path = self.memory_dir / "MEMORY.md"
        self._storage_path = base_dir / "storage" / "memory_index"
        self._index: Optional[Any] = None
        self._nodes: list = []
        self._sections: list[_MemorySection] = []
        self._last_md5: str = ""

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

        raw_sections: list[_MemorySection] = []
        current_heading: str | None = None
        current_lines: list[str] = []

        def flush_current_section() -> None:
            text = "\n".join(current_lines).strip()
            if not text:
                return

            section_source = document.source
            if current_heading:
                anchor = self._slugify_heading(current_heading)
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

        for line in document.body.splitlines():
            heading_match = _MARKDOWN_HEADING_RE.match(line.strip())
            if heading_match:
                flush_current_section()
                current_heading = heading_match.group(2).strip()
                current_lines = [line]
                continue

            if not current_lines and not line.strip():
                continue
            current_lines.append(line)

        flush_current_section()

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

    def _memory_state_md5(self) -> str:
        digest = hashlib.md5()
        saw_file = False

        for path in self._memory_files():
            try:
                content = path.read_bytes()
            except OSError:
                continue

            saw_file = True
            digest.update(self._relative_source(path).encode("utf-8"))
            digest.update(b"\0")
            digest.update(content)
            digest.update(b"\0")

        if not saw_file:
            return ""

        return digest.hexdigest()

    def _maybe_rebuild(self) -> None:
        current = self._memory_state_md5()
        if current != self._last_md5:
            self.rebuild_index()

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

    def rebuild_index(self) -> None:
        """
        Build a VectorStoreIndex from memory/ documents and persist to storage/memory_index/.

        Fast path: if the persisted index exists and its stored MD5 matches the current
        memory state, load from disk (no re-embedding). Slow path: parse, embed, persist.
        """
        current_md5 = self._memory_state_md5()
        md5_file = self._storage_path / "md5.txt"

        self._log_malformed_documents()

        sections = self._memory_sections()
        self._sections = sections
        if not sections:
            self._index = None
            self._nodes = []
            self._last_md5 = current_md5
            return

        # Record the observed file hash before optional indexing work so callers
        # do not repeatedly retrigger rebuild attempts when LlamaIndex or the
        # embedding backend is unavailable.
        self._index = None
        self._nodes = []
        self._last_md5 = current_md5

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
            if md5_file.read_text(encoding="utf-8").strip() == current_md5:
                try:
                    storage_context = StorageContext.from_defaults(
                        persist_dir=str(self._storage_path)
                    )
                    self._index = load_index_from_storage(storage_context)
                    self._nodes = list(self._index.docstore.docs.values())
                    return
                except Exception:
                    pass  # Fall through to full rebuild

        docs = []
        for section in sections:
            metadata = {"source": section.source}
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
            docs.append(Document(text=section.text, metadata=metadata))
        splitter = SentenceSplitter(chunk_size=256, chunk_overlap=32)
        self._nodes = splitter.get_nodes_from_documents(docs)

        if self._nodes:
            try:
                self._storage_path.mkdir(parents=True, exist_ok=True)
                storage_context = StorageContext.from_defaults()
                self._index = VectorStoreIndex(self._nodes, storage_context=storage_context)
                self._index.storage_context.persist(persist_dir=str(self._storage_path))
                md5_file.write_text(current_md5, encoding="utf-8")
            except Exception:
                # Missing embeddings or transient index-storage failures should not
                # block lexical/BM25 memory retrieval for the current turn.
                self._index = None

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
