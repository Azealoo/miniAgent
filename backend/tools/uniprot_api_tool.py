"""
UniProt REST API helper: search and fetch protein entries by gene or ID.
"""
import urllib.parse
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_BASE = "https://rest.uniprot.org"
_MAX = 50_000


class UniprotApiInput(BaseModel):
    query: str = Field(description="Search query (e.g. gene_exact:TP53) or UniProt accession (e.g. P53_HUMAN).")
    fields: Optional[str] = Field(
        default="accession,gene_names,protein_name,organism_name,function",
        description="Comma-separated fields to return (default: accession,gene_names,protein_name,organism_name,function)."
    )
    format: str = Field(default="json", description="Format: json or list.")


class UniprotApiTool(BaseTool):
    name: str = "uniprot_api"
    description: str = (
        "Query UniProt REST API for protein information. "
        "Use query like gene_exact:TP53 or an accession. "
        "Input: query, optional fields and format."
    )
    args_schema: Type[BaseModel] = UniprotApiInput

    def _run(
        self,
        query: str = "",
        fields: Optional[str] = None,
        format: str = "json",
    ) -> str:
        if not query.strip():
            return "[ERROR] query is required."
        fields = fields or "accession,gene_names,protein_name,organism_name,function"
        try:
            import httpx
            url = f"{_BASE}/uniprotkb/search?query={urllib.parse.quote(query)}&fields={urllib.parse.quote(fields)}&format={format}&size=5"
            r = httpx.get(url, timeout=25)
            r.raise_for_status()
            text = r.text
            if len(text) > _MAX:
                text = text[:_MAX] + "\n...[truncated]"
            return text
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(
        self,
        query: str = "",
        fields: Optional[str] = None,
        format: str = "json",
    ) -> str:
        return self._run(query=query, fields=fields, format=format)
