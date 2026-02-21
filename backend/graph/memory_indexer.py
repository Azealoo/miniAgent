import hashlib
from pathlib import Path
from typing import Any, Optional


class MemoryIndexer:
    """
    Manages a LlamaIndex vector index over memory/MEMORY.md.
    Rebuilds automatically when the file changes (MD5-based detection).
    Uses BM25 + vector hybrid retrieval.
    """

    def __init__(self, base_dir: Path) -> None:
        self.memory_path = base_dir / "memory" / "MEMORY.md"
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
        """Read MEMORY.md, chunk it, and build an in-memory vector index."""
        from llama_index.core import VectorStoreIndex, Document
        from llama_index.core.node_parser import SentenceSplitter

        self._index = None
        self._nodes = []
        self._last_md5 = self._file_md5()

        if not self.memory_path.exists():
            return

        content = self.memory_path.read_text(encoding="utf-8").strip()
        if not content:
            return

        doc = Document(text=content, metadata={"source": "MEMORY.md"})
        splitter = SentenceSplitter(chunk_size=256, chunk_overlap=32)
        self._nodes = splitter.get_nodes_from_documents([doc])

        if self._nodes:
            self._index = VectorStoreIndex(self._nodes)

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
