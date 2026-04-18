"""
UniProt REST API helper: search and fetch protein entries by gene or ID.
"""
from dataclasses import dataclass
import json
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

_BASE = "https://rest.uniprot.org"
_MAX = 50_000


@dataclass(frozen=True)
class UniprotApiResponse:
    query: str
    fields: str
    format: str
    url: str
    status_code: int
    text: str
    json_payload: Any | None = None


def fetch_uniprot_response(
    *,
    query: str,
    fields: Optional[str] = None,
    format: str = "json",
    size: int = 5,
) -> UniprotApiResponse:
    resolved_fields = fields or "accession,gene_names,protein_name,organism_name,function"
    url = (
        f"{_BASE}/uniprotkb/search?query={urllib.parse.quote(query)}"
        f"&fields={urllib.parse.quote(resolved_fields)}&format={format}&size={size}"
    )

    import httpx

    response = httpx.get(url, timeout=25)
    response.raise_for_status()
    text = response.text
    json_payload = None
    if format == "json":
        try:
            json_payload = response.json()
        except (json.JSONDecodeError, ValueError):
            json_payload = None

    return UniprotApiResponse(
        query=query,
        fields=resolved_fields,
        format=format,
        url=url,
        status_code=response.status_code,
        text=text,
        json_payload=json_payload,
    )


class UniprotApiInput(BaseModel):
    query: str = Field(
        description="Search query (e.g. gene_exact:TP53), UniProt accession (e.g. P04637), or UniProt entry name (e.g. P53_HUMAN)."
    )
    fields: Optional[str] = Field(
        default="accession,gene_names,protein_name,organism_name,function",
        description="Comma-separated fields to return (default: accession,gene_names,protein_name,organism_name,function)."
    )
    format: str = Field(default="json", description="Format: json or list.")


class UniprotApiTool(BaseTool):
    name: str = "uniprot_api"
    description: str = (
        "Query UniProt REST API for protein information. "
        "Use query like gene_exact:TP53, a UniProt accession, or a UniProt entry name. "
        "Input: query, optional fields and format."
    )
    args_schema: Type[BaseModel] = UniprotApiInput
    response_format: str = "content_and_artifact"

    def _run(
        self,
        query: str = "",
        fields: Optional[str] = None,
        format: str = "json",
    ) -> tuple[str, dict]:
        if not query.strip():
            return invalid_input_result(
                self.name,
                "query is required.",
                metadata={"format": format},
            )
        fields = fields or "accession,gene_names,protein_name,organism_name,function"
        url = ""
        try:
            import httpx
            response = fetch_uniprot_response(
                query=query,
                fields=fields,
                format=format,
                size=5,
            )
            url = response.url
            text = response.text
            source_payload = None
            warnings: list[str] = []

            if format == "json" and response.json_payload is not None:
                parsed = response.json_payload
                summary, truncated = json_to_pretty_text(parsed, _MAX)
                if truncated:
                    warnings.append("output_truncated")
                structured_payload = parsed
                result_count = len(parsed.get("results", [])) if isinstance(parsed, dict) else None
            elif format == "json":
                try:
                    parsed = json.loads(text)
                    summary, truncated = json_to_pretty_text(parsed, _MAX)
                    if truncated:
                        warnings.append("output_truncated")
                    structured_payload = parsed
                    result_count = len(parsed.get("results", [])) if isinstance(parsed, dict) else None
                except (json.JSONDecodeError, ValueError):
                    summary, truncated = truncate_text(text, _MAX)
                    if truncated:
                        warnings.append("output_truncated")
                    structured_payload = {"raw_text": summary, "format": format}
                    source_payload = summary
                    result_count = None
            elif format == "list":
                summary, truncated = truncate_text(text, _MAX)
                if truncated:
                    warnings.append("output_truncated")
                entries = [line for line in summary.splitlines() if line.strip()]
                structured_payload = {"entries": entries, "format": format}
                result_count = len(entries)
            else:
                summary, truncated = truncate_text(text, _MAX)
                if truncated:
                    warnings.append("output_truncated")
                structured_payload = {"format": format}
                source_payload = summary
                result_count = None

            metadata = {
                "query": query,
                "fields": fields,
                "format": format,
                "request_url": url,
                "http_status": response.status_code,
            }
            if result_count is not None:
                metadata["result_count"] = result_count

            if _is_uniprot_empty(structured_payload, summary):
                return empty_result(
                    self.name,
                    summary or "No UniProt results returned.",
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
                "UniProt request timed out.",
                metadata={"query": query, "format": format, "request_url": url},
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            message = f"HTTP {status_code}: {exc.response.reason_phrase}"
            metadata = {"query": query, "format": format, "request_url": url, "http_status": status_code}
            if status_code == 429 or status_code >= 500:
                return retriable_error_result(self.name, message, metadata=metadata)
            if 400 <= status_code < 500:
                return invalid_input_result(self.name, message, metadata=metadata)
            return execution_error_result(self.name, message, metadata=metadata)
        except httpx.RequestError as exc:
            return retriable_error_result(
                self.name,
                f"UniProt request failed: {exc}",
                metadata={"query": query, "format": format, "request_url": url},
            )
        except Exception as exc:
            return execution_error_result(
                self.name,
                str(exc),
                metadata={"query": query, "format": format, "request_url": url},
            )

    async def _arun(
        self,
        query: str = "",
        fields: Optional[str] = None,
        format: str = "json",
    ) -> tuple[str, dict]:
        return self._run(query=query, fields=fields, format=format)


def _is_uniprot_empty(structured_payload: object, summary: str) -> bool:
    if isinstance(structured_payload, dict):
        results = structured_payload.get("results")
        if isinstance(results, list):
            return len(results) == 0
        entries = structured_payload.get("entries")
        if isinstance(entries, list):
            return len(entries) == 0
    return not summary.strip()
