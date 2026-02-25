"""
NCBI E-utilities helper: esearch, efetch, esummary for PubMed, Gene, etc.
Uses rate limit (no API key required; with API key can increase rate).
"""
import time
import urllib.parse
from typing import Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_LAST_CALL = [0.0]
_MIN_INTERVAL = 0.34  # ~3 requests per second without API key


def _rate_limit() -> None:
    elapsed = time.time() - _LAST_CALL[0]
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL[0] = time.time()


class NcbiEutilsInput(BaseModel):
    operation: str = Field(
        description="One of: esearch, efetch, esummary. Use esearch to get IDs, efetch to get full records, esummary for short summaries."
    )
    db: str = Field(description="Database: pubmed, gene, protein, etc.")
    term: Optional[str] = Field(default=None, description="Search term for esearch (e.g. 'BRCA1[sym]' for gene).")
    id: Optional[str] = Field(default=None, description="Comma-separated IDs for efetch or esummary.")
    retmax: Optional[int] = Field(default=20, description="Max results for esearch (default 20).")
    retmode: str = Field(default="json", description="Return format: json or xml.")


class NcbiEutilsTool(BaseTool):
    name: str = "ncbi_eutils"
    description: str = (
        "Query NCBI E-utilities (PubMed, Gene, etc.). "
        "Operations: esearch (search by term), efetch (fetch by ID), esummary (summaries by ID). "
        "Input: operation, db, and either term (esearch) or id (efetch/esummary)."
    )
    args_schema: Type[BaseModel] = NcbiEutilsInput

    def _run(
        self,
        operation: str = "esearch",
        db: str = "pubmed",
        term: Optional[str] = None,
        id: Optional[str] = None,
        retmax: Optional[int] = 20,
        retmode: str = "json",
    ) -> str:
        operation = operation.lower().strip()
        if operation not in ("esearch", "efetch", "esummary"):
            return "[ERROR] operation must be esearch, efetch, or esummary."
        if operation == "esearch" and not term:
            return "[ERROR] term is required for esearch."
        if operation in ("efetch", "esummary") and not id:
            return "[ERROR] id is required for efetch and esummary."

        params = {"db": db, "retmode": retmode}
        if operation == "esearch":
            params["term"] = term
            params["retmax"] = min(retmax or 20, 100)
        else:
            params["id"] = id

        url = f"{_BASE}/{operation}.fcgi?" + urllib.parse.urlencode(params)
        _rate_limit()

        try:
            import httpx
            r = httpx.get(url, timeout=30)
            r.raise_for_status()
            text = r.text
            if len(text) > 80_000:
                text = text[:80_000] + "\n...[truncated]"
            return text
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(
        self,
        operation: str = "esearch",
        db: str = "pubmed",
        term: Optional[str] = None,
        id: Optional[str] = None,
        retmax: Optional[int] = 20,
        retmode: str = "json",
    ) -> str:
        return self._run(
            operation=operation,
            db=db,
            term=term,
            id=id,
            retmax=retmax,
            retmode=retmode,
        )
