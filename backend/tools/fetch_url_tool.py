"""
Fetches a URL and converts the response to clean Markdown (HTML pages)
or returns JSON directly.
"""
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
        try:
            with httpx.Client(
                timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS
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
        except Exception as exc:
            return f"[ERROR] {exc}"

    async def _arun(self, url: str) -> str:  # type: ignore[override]
        return self._run(url)
