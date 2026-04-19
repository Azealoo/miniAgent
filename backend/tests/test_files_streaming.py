"""End-to-end streaming tests for /api/files/stream (GET Range + PUT chunked).

These tests verify that neither endpoint materializes the full payload in
memory. The GET side uses a ~2 GiB sparse temp file (no real disk cost) and
the PUT side streams the same volume of zero bytes from a generator, so peak
Python-heap usage tracked by ``tracemalloc`` stays well below payload size.

The heavy memory-flat test drives the ASGI app directly (scope / receive /
send) instead of going through ``TestClient``. ``httpx.ASGITransport`` joins
all response body parts into a single ``bytes`` object before yielding them to
the client, which would make peak memory grow with payload size for any
streamed response — the server behavior we actually care about is hidden
behind that client-side buffer.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tracemalloc
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


# 2 GiB by default; override for constrained CI via env var. The memory-flat
# assertion scales to whatever size is configured.
_DEFAULT_STREAM_BYTES = 2 * 1024 * 1024 * 1024
_STREAM_BYTES = int(os.environ.get("BIOAPEX_STREAM_TEST_BYTES", _DEFAULT_STREAM_BYTES))
_CLIENT_CHUNK = 16 * 1024 * 1024  # 16 MiB per client iteration
_MEM_BUDGET = 256 * 1024 * 1024   # 256 MiB ceiling on Python-heap peak


def _make_sparse_file(path: Path, size_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        if size_bytes > 0:
            fh.seek(size_bytes - 1)
            fh.write(b"\x00")


def _chunk_generator(total: int, chunk_size: int):
    # Reuse a single buffer so the client side of the pipe stays memory-flat.
    buf = b"\x00" * chunk_size
    remaining = total
    while remaining > 0:
        if remaining < chunk_size:
            yield b"\x00" * remaining
            remaining = 0
        else:
            yield buf
            remaining -= chunk_size


@pytest.fixture
def streaming_app(tmp_path, monkeypatch):
    """Build a minimal FastAPI app exposing only the files router.

    Avoids importing the full ``app.py`` (which triggers LlamaIndex / memory
    index rebuilds) while still exercising the live access-control and audit
    hooks.

    Disables the file-API rate limiter so the 2 GiB memory-flat test (which
    streams a payload through ~128 back-to-back Range reads) isn't tripped by
    the production 30-reads/min default. Rate-limit behavior is covered in
    ``test_files_rate_limit.py``.
    """
    from graph.agent import agent_manager
    from api.files import router as files_router
    from rate_limit import clear_buckets

    monkeypatch.setenv("BIOAPEX_RATE_LIMIT_DISABLED", "1")
    clear_buckets()

    original_base_dir = agent_manager.base_dir
    original_memory_indexer = agent_manager.memory_indexer
    agent_manager.base_dir = tmp_path
    agent_manager.memory_indexer = MagicMock()

    for relpath in ("artifacts", "memory", "workspace", "skills", "knowledge"):
        (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

    app = FastAPI()
    app.include_router(files_router, prefix="/api")

    try:
        yield app, tmp_path
    finally:
        agent_manager.base_dir = original_base_dir
        agent_manager.memory_indexer = original_memory_indexer
        clear_buckets()


def _loopback_client(app: FastAPI) -> TestClient:
    # Pin a loopback origin so access_control's dev posture grants access
    # without a bearer token.
    return TestClient(app, client=("127.0.0.1", 12345))


def test_stream_get_range_returns_206_with_content_range(streaming_app):
    app, base_dir = streaming_app
    artifact = base_dir / "artifacts" / "small.bin"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"abcdefghij")  # 10 bytes

    with _loopback_client(app) as client:
        resp = client.get(
            "/api/files/stream",
            params={"path": "artifacts/small.bin"},
            headers={"Range": "bytes=2-5"},
        )

    assert resp.status_code == 206
    assert resp.headers["Content-Range"] == "bytes 2-5/10"
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.headers["Content-Length"] == "4"
    assert resp.content == b"cdef"


def test_stream_get_invalid_range_returns_416(streaming_app):
    app, base_dir = streaming_app
    artifact = base_dir / "artifacts" / "tiny.bin"
    artifact.write_bytes(b"abc")

    with _loopback_client(app) as client:
        resp = client.get(
            "/api/files/stream",
            params={"path": "artifacts/tiny.bin"},
            headers={"Range": "bytes=99-200"},
        )
    assert resp.status_code == 416
    assert resp.headers.get("Content-Range") == "bytes */3"


def test_stream_head_returns_size_and_content_type(streaming_app):
    app, base_dir = streaming_app
    artifact = base_dir / "artifacts" / "metadata.bin"
    artifact.write_bytes(b"abcdefghij")  # 10 bytes

    with _loopback_client(app) as client:
        resp = client.head(
            "/api/files/stream",
            params={"path": "artifacts/metadata.bin"},
        )

    assert resp.status_code == 200
    assert resp.headers["Content-Length"] == "10"
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.headers.get("ETag")
    assert resp.headers.get("Last-Modified")
    assert resp.headers.get("Content-Type")
    assert resp.content == b""


def test_stream_head_does_not_buffer_2gb_file(streaming_app):
    """HEAD against a 2 GiB sparse file returns size headers without reading body."""
    app, base_dir = streaming_app
    sparse = base_dir / "artifacts" / "huge_head.bin"
    _make_sparse_file(sparse, _STREAM_BYTES)

    tracemalloc.start()
    tracemalloc.reset_peak()
    with _loopback_client(app) as client:
        resp = client.head(
            "/api/files/stream",
            params={"path": "artifacts/huge_head.bin"},
        )
    head_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert resp.status_code == 200
    assert resp.headers["Content-Length"] == str(_STREAM_BYTES)
    assert resp.headers["Accept-Ranges"] == "bytes"
    assert resp.content == b""
    assert head_peak < _MEM_BUDGET, (
        f"HEAD on {_STREAM_BYTES} bytes peaked at {head_peak}, "
        f"exceeding budget {_MEM_BUDGET}."
    )


def test_stream_put_rejects_non_artifacts_prefix(streaming_app):
    app, _ = streaming_app
    with _loopback_client(app) as client:
        resp = client.put(
            "/api/files/stream",
            params={"path": "workspace/not-allowed.bin"},
            content=b"payload",
        )
    assert resp.status_code == 403


async def _asgi_stream_get(app: FastAPI, url_path: str, query: dict, headers: dict):
    """Invoke an ASGI app and drain response body chunks without buffering.

    Returns ``(status, response_headers, total_bytes)`` — body bytes are
    discarded as soon as each ``http.response.body`` message arrives so peak
    memory reflects only what the server is holding in flight.
    """
    scope = {
        "type": "http",
        # spec_version 2.4 skips Starlette's disconnect-watcher task group for
        # StreamingResponse, so the driver doesn't need a disconnect channel.
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": url_path,
        "raw_path": url_path.encode(),
        "query_string": urlencode(query).encode(),
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    state = {"status": None, "headers": {}, "bytes": 0}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        t = message["type"]
        if t == "http.response.start":
            state["status"] = message["status"]
            state["headers"] = {
                k.decode().lower(): v.decode() for k, v in message.get("headers", [])
            }
        elif t == "http.response.body":
            state["bytes"] += len(message.get("body", b""))

    await app(scope, receive, send)
    return state["status"], state["headers"], state["bytes"]


async def _asgi_stream_put(
    app: FastAPI,
    url_path: str,
    query: dict,
    total_bytes: int,
    chunk_size: int,
):
    """Invoke an ASGI PUT whose request body is produced one chunk at a time.

    Returns ``(status, response_body_bytes)``.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": url_path,
        "raw_path": url_path.encode(),
        "query_string": urlencode(query).encode(),
        "root_path": "",
        "headers": [
            (b"content-type", b"application/octet-stream"),
            (b"content-length", str(total_bytes).encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    remaining = {"n": total_bytes}
    buf = b"\x00" * chunk_size

    async def receive():
        n = remaining["n"]
        if n <= 0:
            return {"type": "http.request", "body": b"", "more_body": False}
        if n <= chunk_size:
            body = b"\x00" * n
            remaining["n"] = 0
            return {"type": "http.request", "body": body, "more_body": False}
        remaining["n"] = n - chunk_size
        return {"type": "http.request", "body": buf, "more_body": True}

    status_holder = {"code": None}
    response_parts: list[bytes] = []

    async def send(message):
        t = message["type"]
        if t == "http.response.start":
            status_holder["code"] = message["status"]
        elif t == "http.response.body":
            response_parts.append(message.get("body", b""))

    await app(scope, receive, send)
    return status_holder["code"], b"".join(response_parts)


def test_stream_get_and_put_keep_memory_flat_for_2gb(streaming_app):
    """Stream ~2 GiB through both endpoints and verify heap peak stays flat.

    We drive the ASGI app directly because ``httpx.ASGITransport`` buffers the
    full response before surfacing it to the client; the server-side streaming
    contract is what matters here and a direct driver exposes it cleanly.
    """
    app, base_dir = streaming_app

    # --- GET side: read a 2 GiB sparse artifact in 16 MiB Range slices.
    source = base_dir / "artifacts" / "huge_source.bin"
    _make_sparse_file(source, _STREAM_BYTES)

    async def _run_get():
        total = 0
        for offset in range(0, _STREAM_BYTES, _CLIENT_CHUNK):
            end = min(offset + _CLIENT_CHUNK - 1, _STREAM_BYTES - 1)
            status, headers, byte_count = await _asgi_stream_get(
                app,
                "/api/files/stream",
                {"path": "artifacts/huge_source.bin"},
                {"range": f"bytes={offset}-{end}"},
            )
            assert status == 206
            assert headers["content-range"] == (
                f"bytes {offset}-{end}/{_STREAM_BYTES}"
            )
            total += byte_count
        return total

    tracemalloc.start()
    tracemalloc.reset_peak()
    read_total = asyncio.run(_run_get())
    get_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert read_total == _STREAM_BYTES
    assert get_peak < _MEM_BUDGET, (
        f"GET streamed {_STREAM_BYTES} bytes with Python-heap peak "
        f"{get_peak} exceeding budget {_MEM_BUDGET}."
    )

    # --- PUT side: stream 2 GiB of zeros through the chunked writer.
    tracemalloc.start()
    tracemalloc.reset_peak()
    status, response_body = asyncio.run(
        _asgi_stream_put(
            app,
            "/api/files/stream",
            {"path": "artifacts/huge_sink.bin"},
            _STREAM_BYTES,
            _CLIENT_CHUNK,
        )
    )
    put_peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert status == 200, response_body
    import json as _json
    body = _json.loads(response_body.decode("utf-8"))
    assert body["bytes_written"] == _STREAM_BYTES
    assert body["saved"] is True

    written = base_dir / "artifacts" / "huge_sink.bin"
    assert written.stat().st_size == _STREAM_BYTES
    assert put_peak < _MEM_BUDGET, (
        f"PUT streamed {_STREAM_BYTES} bytes with Python-heap peak "
        f"{put_peak} exceeding budget {_MEM_BUDGET}."
    )

    # Drop the 2 GiB sink promptly so subsequent tests do not inherit it.
    try:
        written.unlink()
    except OSError:
        pass
