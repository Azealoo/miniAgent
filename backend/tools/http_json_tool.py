"""
Structured HTTP tool: GET or POST with JSON response parsing, timeout, retries, and size cap.
Use for APIs instead of raw fetch_url when JSON is expected.
"""
import ipaddress
import re
from typing import Any, Optional, Type
from urllib.parse import urlparse

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_TIMEOUT = 30
_MAX_BODY = 100_000
_RETRIES = 2

# SSRF: block requests to localhost and RFC-1918/link-local networks.
_BLOCKED_HOSTS_RE = re.compile(
    r"^(localhost|.*\.local|.*\.internal|metadata\.google\.internal|"
    r"169\.254\.169\.254|100\.100\.100\.200)$",
    re.IGNORECASE,
)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_blocked_url(url: str) -> bool:
    """Return True if *url* targets localhost or a private/internal network."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if _BLOCKED_HOSTS_RE.match(host):
            return True
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


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
        if _is_blocked_url(url):
            return "[BLOCKED] Requests to localhost or private networks are not allowed."
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
