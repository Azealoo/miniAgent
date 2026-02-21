"""
Hybrid BM25 + vector search over the knowledge/ directory using LlamaIndex.
The index is lazily built and persisted to storage/knowledge_index/.
"""
from pathlib import Path
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

_TOP_K = 3


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
    knowledge_dir: str = ""
    storage_dir: str = ""

    _index: Optional[Any] = PrivateAttr(default=None)
    _nodes: list = PrivateAttr(default_factory=list)
    _built: bool = PrivateAttr(default=False)

    def _ensure_index(self) -> None:
        if self._built:
            return
        self._built = True

        knowledge_path = Path(self.knowledge_dir)
        storage_path = Path(self.storage_dir) / "knowledge_index"

        if not knowledge_path.exists():
            return

        # Check for any supported files
        supported_exts = {".md", ".txt", ".pdf"}
        files = [
            f for f in knowledge_path.rglob("*") if f.suffix.lower() in supported_exts
        ]
        if not files:
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

            # Try loading persisted index
            try:
                storage_context = StorageContext.from_defaults(
                    persist_dir=str(storage_path)
                )
                self._index = load_index_from_storage(storage_context)
                # Rebuild nodes list for BM25
                self._nodes = list(self._index.docstore.docs.values())
                return
            except Exception:
                pass

            # Build fresh
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

        except Exception as exc:
            self._index = None
            self._nodes = []

    def _run(self, query: str) -> str:
        self._ensure_index()

        if self._index is None:
            return "The knowledge base is empty or could not be loaded."

        seen: set[str] = set()
        results: list[str] = []

        # Vector retrieval
        try:
            retriever = self._index.as_retriever(similarity_top_k=_TOP_K)
            for node in retriever.retrieve(query):
                nid = node.node.node_id
                if nid not in seen:
                    seen.add(nid)
                    src = node.metadata.get("file_name", "document")
                    results.append(f"[Source: {src}]\n{node.text}")
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
                        results.append(f"[Source: {src}]\n{node.text}")
        except Exception:
            pass

        if not results:
            return "No relevant results found in the knowledge base."

        output = "\n\n---\n\n".join(results[:_TOP_K])
        return output

    async def _arun(self, query: str) -> str:  # type: ignore[override]
        return self._run(query)
