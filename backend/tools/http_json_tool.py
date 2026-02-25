"""
Structured HTTP tool: GET or POST with JSON response parsing, timeout, retries, and size cap.
Use for APIs instead of raw fetch_url when JSON is expected.
"""
from typing import Any, Optional, Type

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_TIMEOUT = 30
_MAX_BODY = 100_000
_RETRIES = 2


class HttpJsonInput(BaseModel):
    method: str = Field(default="GET", description="HTTP method: GET or POST.")
    url: str = Field(description="Full URL to request.")
    json_body: Optional[dict] = Field(default=None, description="Optional JSON body for POST.")


class HttpJsonTool(BaseTool):
    name: str = "http_json"
    description: str = (
        "Make an HTTP GET or POST request and return the response as JSON. "
        "Use for REST APIs (e.g. NCBI, UniProt, Enrichr). "
        "Input: method (GET/POST), url, and optional json_body for POST."
    )
    args_schema: Type[BaseModel] = HttpJsonInput

    def _run(
        self,
        method: str = "GET",
        url: str = "",
        json_body: Optional[dict] = None,
    ) -> str:
        if not url.strip():
            return "[ERROR] URL is required."
        method = method.upper().strip()
        if method not in ("GET", "POST"):
            return "[ERROR] Method must be GET or POST."
        if method == "POST" and json_body is None:
            json_body = {}

        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                for attempt in range(_RETRIES + 1):
                    try:
                        if method == "GET":
                            r = client.get(url)
                        else:
                            r = client.post(url, json=json_body or {})
                        r.raise_for_status()
                        break
                    except httpx.HTTPStatusError as e:
                        if attempt == _RETRIES:
                            return f"[ERROR] HTTP {e.response.status_code}: {e.response.text[:500]}"
                    except httpx.RequestError as e:
                        if attempt == _RETRIES:
                            return f"[ERROR] Request failed: {e}"

            text = r.text
            if len(text) > _MAX_BODY:
                text = text[:_MAX_BODY] + "\n...[truncated]"

            try:
                data = r.json()
                import json
                return json.dumps(data, ensure_ascii=False, indent=2)[:_MAX_BODY]
            except Exception:
                return text[: _MAX_BODY]
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(
        self,
        method: str = "GET",
        url: str = "",
        json_body: Optional[dict] = None,
    ) -> str:
        return self._run(method=method, url=url, json_body=json_body)
