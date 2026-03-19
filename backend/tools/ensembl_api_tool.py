"""
Ensembl REST API helper: lookup gene, transcript, or sequence.
"""
import json
from typing import Optional, Type

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
    response_format: str = "content_and_artifact"

    def _run(
        self,
        endpoint: str = "",
        content_type: str = "application/json",
    ) -> tuple[str, dict]:
        if not endpoint.strip():
            return invalid_input_result(
                self.name,
                "endpoint is required.",
                metadata={"content_type": content_type},
            )
        endpoint = endpoint.lstrip("/")
        url = f"{_BASE}/{endpoint}"
        try:
            import httpx
            r = httpx.get(url, headers={"Content-Type": content_type}, timeout=25)
            r.raise_for_status()
            text = r.text
            source_payload = None
            warnings: list[str] = []

            try:
                parsed = r.json()
                summary, truncated = json_to_pretty_text(parsed, _MAX)
                if truncated:
                    warnings.append("output_truncated")
                structured_payload = parsed
            except (json.JSONDecodeError, ValueError):
                summary, truncated = truncate_text(text, _MAX)
                if truncated:
                    warnings.append("output_truncated")
                structured_payload = {
                    "endpoint": endpoint,
                    "content_type": content_type,
                    "response_content_type": r.headers.get("content-type"),
                }
                source_payload = summary

            metadata = {
                "endpoint": endpoint,
                "content_type": content_type,
                "request_url": url,
                "http_status": r.status_code,
                "response_content_type": r.headers.get("content-type"),
            }

            if not summary.strip():
                return empty_result(
                    self.name,
                    "No Ensembl results returned.",
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
                "Ensembl request timed out.",
                metadata={"endpoint": endpoint, "request_url": url},
            )
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            message = f"HTTP {status_code}: {exc.response.reason_phrase}"
            metadata = {"endpoint": endpoint, "request_url": url, "http_status": status_code}
            if status_code == 429 or status_code >= 500:
                return retriable_error_result(self.name, message, metadata=metadata)
            if 400 <= status_code < 500:
                return invalid_input_result(self.name, message, metadata=metadata)
            return execution_error_result(self.name, message, metadata=metadata)
        except httpx.RequestError as exc:
            return retriable_error_result(
                self.name,
                f"Ensembl request failed: {exc}",
                metadata={"endpoint": endpoint, "request_url": url},
            )
        except Exception as exc:
            return execution_error_result(
                self.name,
                str(exc),
                metadata={"endpoint": endpoint, "request_url": url},
            )

    async def _arun(
        self,
        endpoint: str = "",
        content_type: str = "application/json",
    ) -> tuple[str, dict]:
        return self._run(endpoint=endpoint, content_type=content_type)
