"""
Fetches a URL and converts the response to clean Markdown (HTML pages)
or returns JSON directly.
"""
import ipaddress
import re
import urllib.parse
from typing import Type

import httpx
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

_TIMEOUT = 15.0
_MAX_OUTPUT = 5_000
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; miniOpenClaw/1.0; +https://fufan.ai)"
    )
}

# Block SSRF-prone hostnames (cloud metadata, localhost, internal services)
_BLOCKED_HOSTS_RE = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|::1|"
    r"169\.254\.\d+\.\d+|"   # link-local (AWS/GCP metadata)
    r"metadata\.google\.internal|"
    r"169\.254\.169\.254)$",
    re.I,
)
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),  # Carrier-grade NAT
]


def _is_blocked_url(url: str) -> str | None:
    """Return a reason string if the URL should be blocked, else None."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "invalid URL"

    if parsed.scheme not in ("http", "https"):
        return f"scheme '{parsed.scheme}' is not allowed (only http/https)"

    host = parsed.hostname or ""
    if not host:
        return "missing host"

    if _BLOCKED_HOSTS_RE.match(host):
        return f"host '{host}' is blocked (SSRF protection)"

    # Block requests to private IP ranges
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_loopback or addr.is_link_local or addr.is_private:
            return f"IP address '{host}' is in a private/reserved range"
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return f"IP address '{host}' is in a private range"
    except ValueError:
        pass  # host is a domain name, not an IP — allow

    return None


class FetchURLInput(BaseModel):
    url: str = Field(description="The full URL to fetch (http or https).")


class FetchURLTool(BaseTool):
    name: str = "fetch_url"
    description: str = (
        "Fetch the content of a URL. HTML pages are converted to clean Markdown. "
        "JSON responses are returned as-is. "
        "Input: a valid http/https URL."
    )
    args_schema: Type[BaseModel] = FetchURLInput

    def _run(self, url: str) -> str:
        url = url.strip()
        blocked = _is_blocked_url(url)
        if blocked:
            return f"[BLOCKED] URL refused — {blocked}."

        def _ssrf_redirect_hook(request: httpx.Request) -> None:
            """Re-validate every URL httpx will request, including redirect targets."""
            reason = _is_blocked_url(str(request.url))
            if reason:
                raise httpx.InvalidURL(f"[BLOCKED] Redirect target refused — {reason}.")

        try:
            with httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers=_HEADERS,
                # Intercept every request (including redirects) and re-check the URL
                event_hooks={"request": [_ssrf_redirect_hook]},
            ) as client:
                resp = client.get(url)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()

            if "json" in content_type:
                text = resp.text
            elif "html" in content_type or "xml" in content_type:
                import html2text

                h = html2text.HTML2Text()
                h.ignore_links = False
                h.ignore_images = True
                h.body_width = 0
                text = h.handle(resp.text)
            else:
                text = resp.text

            text = text.strip()
            if len(text) > _MAX_OUTPUT:
                text = text[:_MAX_OUTPUT] + "\n...[output truncated]"
            return text or "(empty response)"

        except httpx.TimeoutException:
            return f"[ERROR] Request timed out after {_TIMEOUT}s."
        except httpx.HTTPStatusError as exc:
            return f"[ERROR] HTTP {exc.response.status_code}: {exc.response.reason_phrase}"
        except httpx.InvalidURL as exc:
            # Raised by the redirect hook when a redirect target is blocked
            return str(exc)
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, url: str) -> str:  # type: ignore[override]
        return self._run(url)
