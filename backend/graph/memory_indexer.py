import hashlib
from pathlib import Path
from typing import Any, Optional


class MemoryIndexer:
    """
    Manages a LlamaIndex vector index over memory/MEMORY.md.
    Rebuilds automatically when the file changes (MD5-based detection).
    Index is persisted to storage/memory_index/ between restarts.
    Uses BM25 + vector hybrid retrieval.
    """

    def __init__(self, base_dir: Path) -> None:
        self.memory_path = base_dir / "memory" / "MEMORY.md"
        self._storage_path = base_dir / "storage" / "memory_index"
        self._index: Optional[Any] = None
        self._nodes: list = []
        self._last_md5: str = ""

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _file_md5(self) -> str:
        if not self.memory_path.exists():
            return ""
        return hashlib.md5(self.memory_path.read_bytes()).hexdigest()

    def _maybe_rebuild(self) -> None:
        current = self._file_md5()
        if current != self._last_md5:
            self.rebuild_index()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def rebuild_index(self) -> None:
        """
        Build a VectorStoreIndex from MEMORY.md and persist to storage/memory_index/.

        Fast path: if the persisted index exists and its stored MD5 matches the current
        file, load from disk (no re-embedding). Slow path: parse, embed, persist.
        """
        from llama_index.core import (
            Document,
            StorageContext,
            VectorStoreIndex,
            load_index_from_storage,
        )
        from llama_index.core.node_parser import SentenceSplitter

        current_md5 = self._file_md5()
        md5_file = self._storage_path / "md5.txt"

        # ── Fast path: load persisted index if file hasn't changed ────────
        if self._storage_path.exists() and md5_file.exists() and current_md5:
            if md5_file.read_text(encoding="utf-8").strip() == current_md5:
                try:
                    storage_context = StorageContext.from_defaults(
                        persist_dir=str(self._storage_path)
                    )
                    self._index = load_index_from_storage(storage_context)
                    self._nodes = list(self._index.docstore.docs.values())
                    self._last_md5 = current_md5
                    return
                except Exception:
                    pass  # Fall through to full rebuild

        # ── Slow path: rebuild from file ───────────────────────────────────
        self._index = None
        self._nodes = []
        self._last_md5 = current_md5

        if not self.memory_path.exists():
            return

        content = self.memory_path.read_text(encoding="utf-8").strip()
        if not content:
            return

        doc = Document(text=content, metadata={"source": "MEMORY.md"})
        splitter = SentenceSplitter(chunk_size=256, chunk_overlap=32)
        self._nodes = splitter.get_nodes_from_documents([doc])

        if self._nodes:
            self._storage_path.mkdir(parents=True, exist_ok=True)
            storage_context = StorageContext.from_defaults()
            self._index = VectorStoreIndex(self._nodes, storage_context=storage_context)
            self._index.storage_context.persist(persist_dir=str(self._storage_path))
            md5_file.write_text(current_md5, encoding="utf-8")

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Hybrid BM25 + vector retrieval.
        Returns [{text, score, source}, ...] deduplicated, up to top_k results.
        """
        self._maybe_rebuild()

        if self._index is None or not self._nodes:
            return []

        results: list[dict] = []
        seen: set[str] = set()

        # Vector retrieval
        try:
            vector_retriever = self._index.as_retriever(similarity_top_k=top_k)
            for node in vector_retriever.retrieve(query):
                if node.node.node_id not in seen:
                    seen.add(node.node.node_id)
                    results.append(
                        {
                            "text": node.text,
                            "score": float(node.score or 0.0),
                            "source": node.metadata.get("source", "MEMORY.md"),
                        }
                    )
        except Exception:
            pass

        # BM25 retrieval
        try:
            from llama_index.retrievers.bm25 import BM25Retriever

            bm25 = BM25Retriever.from_defaults(nodes=self._nodes, similarity_top_k=top_k)
            for node in bm25.retrieve(query):
                if node.node.node_id not in seen:
                    seen.add(node.node.node_id)
                    results.append(
                        {
                            "text": node.text,
                            "score": float(node.score or 0.0),
                            "source": node.metadata.get("source", "MEMORY.md"),
                        }
                    )
        except Exception:
            pass

        # Return up to top_k, sorted by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
