"""
Ensembl REST API helper: lookup gene, transcript, or sequence.
"""
import urllib.parse
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_BASE = "https://rest.ensembl.org"
_MAX = 50_000


class EnsemblApiInput(BaseModel):
    endpoint: str = Field(
        description="Endpoint path, e.g. lookup/symbol/homo_sapiens/TP53, or search?q=BRCA1."
    )
    content_type: str = Field(default="application/json", description="Content-Type header.")


class EnsemblApiTool(BaseTool):
    name: str = "ensembl_api"
    description: str = (
        "Query Ensembl REST API for gene/transcript/sequence. "
        "Endpoint examples: lookup/symbol/homo_sapiens/TP53, search?q=BRCA1. "
        "Input: endpoint path, optional content_type."
    )
    args_schema: Type[BaseModel] = EnsemblApiInput

    def _run(
        self,
        endpoint: str = "",
        content_type: str = "application/json",
    ) -> str:
        if not endpoint.strip():
            return "[ERROR] endpoint is required."
        endpoint = endpoint.lstrip("/")
        url = f"{_BASE}/{endpoint}"
        try:
            import httpx
            r = httpx.get(url, headers={"Content-Type": content_type}, timeout=25)
            r.raise_for_status()
            text = r.text
            if len(text) > _MAX:
                text = text[:_MAX] + "\n...[truncated]"
            return text
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(
        self,
        endpoint: str = "",
        content_type: str = "application/json",
    ) -> str:
        return self._run(endpoint=endpoint, content_type=content_type)
