"""
NCBI E-utilities helper: esearch, efetch, esummary for PubMed, Gene, etc.
Uses rate limit (no API key required; with API key can increase rate).
"""
from dataclasses import dataclass
import json
import threading
import time
import urllib.parse
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from .contracts import (
    empty_result,
    execution_error_result,
    invalid_input_result,
    json_to_pretty_text,
    retriable_error_result,
    success_result,
    truncate_text,
)

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_LAST_CALL = [0.0]
_MIN_INTERVAL = 0.34  # ~3 requests per second without API key
_rate_lock = threading.Lock()


def _rate_limit() -> None:
    """Thread-safe rate limiter — prevents NCBI 429 responses."""
    with _rate_lock:
        elapsed = time.time() - _LAST_CALL[0]
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)
        _LAST_CALL[0] = time.time()


@dataclass(frozen=True)
class NcbiEutilsResponse:
    operation: str
    db: str
    retmode: str
    url: str
    status_code: int
    text: str
    json_payload: Any | None = None


def fetch_ncbi_eutils_response(
    *,
    operation: str,
    db: str,
    term: Optional[str] = None,
    id: Optional[str] = None,
    retmax: Optional[int] = 20,
    retmode: str = "json",
) -> NcbiEutilsResponse:
    params = {"db": db, "retmode": retmode}
    if operation == "esearch":
        params["term"] = term
        params["retmax"] = min(retmax or 20, 100)
    else:
        params["id"] = id

    url = f"{_BASE}/{operation}.fcgi?" + urllib.parse.urlencode(params)
    _rate_limit()

    import httpx

    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    text = response.text
    json_payload = None
    if retmode == "json":
        try:
            json_payload = response.json()
        except (json.JSONDecodeError, ValueError):
            json_payload = None

    return NcbiEutilsResponse(
        operation=operation,
        db=db,
        retmode=retmode,
        url=url,
        status_code=response.status_code,
        text=text,
        json_payload=json_payload,
    )


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
    response_format: str = "content_and_artifact"

    def _run(
        self,
        operation: str = "esearch",
        db: str = "pubmed",
        term: Optional[str] = None,
        id: Optional[str] = None,
        retmax: Optional[int] = 20,
        retmode: str = "json",
    ) -> tuple[str, dict]:
        operation = operation.lower().strip()
        if operation not in ("esearch", "efetch", "esummary"):
            return invalid_input_result(
                self.name,
                "operation must be esearch, efetch, or esummary.",
                metadata={"operation": operation, "db": db, "retmode": retmode},
            )
        if operation == "esearch" and not term:
            return invalid_input_result(
                self.name,
                "term is required for esearch.",
                metadata={"operation": operation, "db": db, "retmode": retmode},
            )
        if operation in ("efetch", "esummary") and not id:
            return invalid_input_result(
                self.name,
                "id is required for efetch and esummary.",
                metadata={"operation": operation, "db": db, "retmode": retmode},
            )

        try:
            import httpx
            response = fetch_ncbi_eutils_response(
                operation=operation,
                db=db,
                term=term,
                id=id,
                retmax=retmax,
                retmode=retmode,
            )
            text = response.text
            source_payload = None
            warnings: list[str] = []
            structured_payload: object
            summary: str

            if retmode == "json" and response.json_payload is not None:
                summary, truncated = json_to_pretty_text(response.json_payload, 80_000)
                if truncated:
                    warnings.append("output_truncated")
                structured_payload = response.json_payload
            elif retmode == "json":
                try:
                    parsed = json.loads(text)
                    summary, truncated = json_to_pretty_text(parsed, 80_000)
                    if truncated:
                        warnings.append("output_truncated")
                    structured_payload = parsed
                except (json.JSONDecodeError, ValueError):
                    summary, truncated = truncate_text(text, 80_000)
                    if truncated:
                        warnings.append("output_truncated")
                    structured_payload = {"raw_text": summary, "retmode": retmode}
                    source_payload = summary
            else:
                summary, truncated = truncate_text(text, 80_000)
                if truncated:
                    warnings.append("output_truncated")
                structured_payload = {"retmode": retmode}
                source_payload = summary

            metadata = {
                "operation": operation,
                "db": db,
                "retmax": min(retmax or 20, 100) if operation == "esearch" else None,
                "retmode": retmode,
                "request_url": response.url,
                "http_status": response.status_code,
            }
            result_count = _extract_ncbi_result_count(operation, structured_payload)
            if result_count is not None:
                metadata["result_count"] = result_count

            if _is_ncbi_empty_response(operation, structured_payload, summary):
                return empty_result(
                    self.name,
                    summary or "No NCBI results returned.",
                    structured_payload=structured_payload,
                    warnings=warnings,
                    metadata=metadata,
                    source_payload=source_payload,
                )

            return success_result(
                self.name,
                summary,
                structured_payload=structured_payload,
                warnings=warnings,
                metadata=metadata,
                source_payload=source_payload,
            )
        except httpx.TimeoutException:
            return retriable_error_result(
                self.name,
                "NCBI request timed out.",
                metadata={"operation": operation, "db": db},
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            message = f"HTTP {status_code}: {exc.response.reason_phrase}"
            metadata = {"operation": operation, "db": db, "request_url": str(exc.request.url), "http_status": status_code}
            if status_code == 429 or status_code >= 500:
                return retriable_error_result(self.name, message, metadata=metadata)
            if 400 <= status_code < 500:
                return invalid_input_result(self.name, message, metadata=metadata)
            return execution_error_result(self.name, message, metadata=metadata)
        except httpx.RequestError as exc:
            return retriable_error_result(
                self.name,
                f"NCBI request failed: {exc}",
                metadata={
                    "operation": operation,
                    "db": db,
                    "request_url": str(exc.request.url) if exc.request is not None else None,
                },
            )
        except Exception as exc:
            return execution_error_result(
                self.name,
                str(exc),
                metadata={"operation": operation, "db": db},
            )

    async def _arun(
        self,
        operation: str = "esearch",
        db: str = "pubmed",
        term: Optional[str] = None,
        id: Optional[str] = None,
        retmax: Optional[int] = 20,
        retmode: str = "json",
    ) -> tuple[str, dict]:
        import asyncio
        import functools

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self._run,
                operation=operation,
                db=db,
                term=term,
                id=id,
                retmax=retmax,
                retmode=retmode,
            ),
        )


def _extract_ncbi_result_count(operation: str, structured_payload: object) -> int | None:
    if not isinstance(structured_payload, dict):
        return None

    if operation == "esearch":
        result = structured_payload.get("esearchresult")
        if isinstance(result, dict):
            try:
                return int(result.get("count", 0))
            except (TypeError, ValueError):
                id_list = result.get("idlist")
                if isinstance(id_list, list):
                    return len(id_list)

    if operation == "esummary":
        result = structured_payload.get("result")
        if isinstance(result, dict):
            uids = result.get("uids")
            if isinstance(uids, list):
                return len(uids)

    return None


def _is_ncbi_empty_response(operation: str, structured_payload: object, summary: str) -> bool:
    count = _extract_ncbi_result_count(operation, structured_payload)
    if count is not None:
        return count == 0
    return not summary.strip()
