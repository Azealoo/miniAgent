"""
Hybrid BM25 + vector search over the knowledge/ directory using LlamaIndex.
The index is lazily built and persisted to storage/knowledge_index/.
"""
from pathlib import Path
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from .contracts import empty_result, success_result

_TOP_K = 3
_SUPPORTED_EXTS = {".md", ".txt", ".pdf"}


class SearchKnowledgeInput(BaseModel):
    query: str = Field(description="The search query to look up in the knowledge base.")


class SearchKnowledgeBaseTool(BaseTool):
    name: str = "search_knowledge_base"
    description: str = (
        "Search the local knowledge base for relevant information. "
        "Use this when you need to look up documents, manuals, or reference material "
        "stored in the knowledge directory. "
        "Input: a search query string."
    )
    args_schema: Type[BaseModel] = SearchKnowledgeInput
    response_format: str = "content_and_artifact"
    knowledge_dir: str = ""
    storage_dir: str = ""

    _index: Optional[Any] = PrivateAttr(default=None)
    _nodes: list = PrivateAttr(default_factory=list)
    _built: bool = PrivateAttr(default=False)
    _last_mtime: float = PrivateAttr(default=0.0)

    def _dir_mtime(self) -> float:
        """Return the latest modification time of any supported file in knowledge_dir."""
        knowledge_path = Path(self.knowledge_dir)
        if not knowledge_path.exists():
            return 0.0
        latest = 0.0
        for f in knowledge_path.rglob("*"):
            if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTS:
                try:
                    latest = max(latest, f.stat().st_mtime)
                except OSError:
                    pass
        return latest

    def _ensure_index(self) -> None:
        current_mtime = self._dir_mtime()
        # Short-circuit when nothing has changed since the last successful build.
        # We do NOT require _index is not None here: an empty knowledge dir is a
        # legitimate "built" state (index=None) and should not trigger a rebuild
        # on every call just because the index is absent.
        if self._built and current_mtime <= self._last_mtime:
            return

        # Reset state — do NOT mark _built=True until build succeeds
        self._index = None
        self._nodes = []

        knowledge_path = Path(self.knowledge_dir)
        storage_path = Path(self.storage_dir) / "knowledge_index"

        if not knowledge_path.exists():
            # Nothing to index — record mtime so we don't retry on every call
            self._built = True
            self._last_mtime = current_mtime
            return

        # Check for any supported files
        files = [
            f for f in knowledge_path.rglob("*") if f.suffix.lower() in _SUPPORTED_EXTS
        ]
        if not files:
            self._built = True
            self._last_mtime = current_mtime
            return

        try:
            from llama_index.core import (
                SimpleDirectoryReader,
                StorageContext,
                VectorStoreIndex,
                load_index_from_storage,
            )
            from llama_index.core.node_parser import SentenceSplitter

            storage_path.mkdir(parents=True, exist_ok=True)

            # Only load the persisted index when mtime has NOT changed (cold start).
            # If mtime DID change (files added/modified) we skip the stale persisted
            # index and always do a full rebuild so new content is included.
            if self._last_mtime == 0.0 or current_mtime <= self._last_mtime:
                try:
                    storage_context = StorageContext.from_defaults(
                        persist_dir=str(storage_path)
                    )
                    self._index = load_index_from_storage(storage_context)
                    # Rebuild nodes list for BM25
                    self._nodes = list(self._index.docstore.docs.values())
                    self._built = True
                    self._last_mtime = current_mtime
                    return
                except Exception:
                    pass

            # Fresh build (first build or mtime changed) — wipe stale persisted index
            import shutil
            if storage_path.exists():
                try:
                    shutil.rmtree(str(storage_path))
                except Exception:
                    pass
            storage_path.mkdir(parents=True, exist_ok=True)

            reader = SimpleDirectoryReader(
                str(knowledge_path), recursive=True
            )
            docs = reader.load_data()
            splitter = SentenceSplitter(chunk_size=512, chunk_overlap=64)
            self._nodes = splitter.get_nodes_from_documents(docs)

            storage_context = StorageContext.from_defaults()
            self._index = VectorStoreIndex(
                self._nodes, storage_context=storage_context
            )
            self._index.storage_context.persist(persist_dir=str(storage_path))
            self._built = True
            self._last_mtime = current_mtime

        except Exception:
            # Build failed — leave _built=False and _last_mtime unchanged so the
            # next call will retry instead of permanently skipping the rebuild.
            self._index = None
            self._nodes = []

    def _run(self, query: str) -> tuple[str, dict]:
        self._ensure_index()

        if self._index is None:
            return empty_result(
                self.name,
                "The knowledge base is empty or could not be loaded.",
                structured_payload={"query": query, "results": []},
                metadata={
                    "knowledge_dir": self.knowledge_dir,
                    "storage_dir": self.storage_dir,
                    "index_status": "empty_or_unavailable",
                },
            )

        seen: set[str] = set()
        results: list[dict[str, str]] = []

        # Vector retrieval
        try:
            retriever = self._index.as_retriever(similarity_top_k=_TOP_K)
            for node in retriever.retrieve(query):
                nid = node.node.node_id
                if nid not in seen:
                    seen.add(nid)
                    src = node.metadata.get("file_name", "document")
                    results.append(
                        {
                            "source": src,
                            "text": node.text,
                            "retrieval_mode": "vector",
                            "node_id": nid,
                        }
                    )
        except Exception:
            pass

        # BM25 retrieval
        try:
            from llama_index.retrievers.bm25 import BM25Retriever

            if self._nodes:
                bm25 = BM25Retriever.from_defaults(
                    nodes=self._nodes, similarity_top_k=_TOP_K
                )
                for node in bm25.retrieve(query):
                    nid = node.node.node_id
                    if nid not in seen:
                        seen.add(nid)
                        src = node.metadata.get("file_name", "document")
                        results.append(
                            {
                                "source": src,
                                "text": node.text,
                                "retrieval_mode": "bm25",
                                "node_id": nid,
                            }
                        )
        except Exception:
            pass

        if not results:
            return empty_result(
                self.name,
                "No relevant results found in the knowledge base.",
                structured_payload={"query": query, "results": []},
                metadata={
                    "knowledge_dir": self.knowledge_dir,
                    "storage_dir": self.storage_dir,
                    "index_status": "ready",
                },
            )

        top_results = results[:_TOP_K]
        output = "\n\n---\n\n".join(
            f"[Source: {result['source']}]\n{result['text']}"
            for result in top_results
        )
        return success_result(
            self.name,
            output,
            structured_payload={"query": query, "results": top_results},
            metadata={
                "knowledge_dir": self.knowledge_dir,
                "storage_dir": self.storage_dir,
                "index_status": "ready",
                "result_count": len(top_results),
            },
        )

    async def _arun(self, query: str) -> tuple[str, dict]:  # type: ignore[override]
        return self._run(query)
