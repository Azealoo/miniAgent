"""
File read/write endpoints with path whitelist protection.

GET  /api/files?path=<relative>        — read file content, including artifacts/
GET  /api/files/raw?path=<relative>    — read raw file content for whitelisted files
GET  /api/files/stream?path=<relative> — streamed read with HTTP Range / If-Range
POST /api/files                        — save file (Monaco editor, bounded)
PUT  /api/files/stream?path=<relative> — chunked streamed write for artifacts/
GET  /api/skills                       — list active skills selected from the runtime registry
GET  /api/skills/registry              — list the full runtime skill registry with metadata

Compatibility notes:
- `/api/skills` stays a compact active-skill summary; richer metadata such as
  `paths`, `effort`, and selection state live on `/api/skills/registry`.
- `SKILLS_SNAPSHOT.md` remains a readable derived artifact, not the source of truth.
- Writes anywhere under `memory/` rebuild the memory index, not only `memory/MEMORY.md`.
- New markdown files under `memory/project/`, `memory/user/`, and `memory/agent/`
  may use typed frontmatter (`type`, `name`, `description`) while legacy files stay readable.
"""
import hashlib
import json
import mimetypes
from email.utils import formatdate
from pathlib import Path

from access_control import require_execution_access, require_inspection_access
import config as cfg
from audit.store import append_file_written_event
from artifacts.public_urls import public_raw_file_url
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from graph.memory_types import validate_memory_write
from hardening import is_secret_like_path
from pydantic import BaseModel
from starlette.requests import ClientDisconnect

router = APIRouter()

# Paths the API is allowed to serve (relative to base_dir)
_READ_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/", "artifacts/")
_WRITE_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
# Streamed writes are gated strictly to artifacts/ so the editor POST whitelist
# is not widened for large, tool-produced payloads.
_STREAM_WRITE_ALLOWED_PREFIXES = ("artifacts/",)
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_MAX_SAVE_BYTES = 500_000  # 500 KB limit for writes via the editor API
_STREAM_CHUNK_BYTES = 1 << 20  # 1 MiB per disk read/write, bounds peak memory
_REFERENCE_SCHEMA_PREFIX = "artifacts/reference_schemas/"


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _check_path(relative_path: str, *, write: bool = False) -> tuple[Path, str]:
    """Validate path against whitelist.

    Returns (resolved_absolute_path, normalized_relative_path).
    Raises HTTPException on any violation.
    """
    # Strip leading slash or ./
    clean = relative_path.strip().lstrip("/").removeprefix("./")

    # Traversal guard (before whitelist check)
    if ".." in clean.split("/"):
        raise HTTPException(403, "Path traversal is not allowed.")

    base = _base_dir()
    target = (base / clean).resolve()

    # Use relative_to() instead of startswith() to prevent prefix-name attacks:
    # e.g. /project/backend_evil would falsely pass startswith(/project/backend)
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(403, "Path is outside the project directory.")

    # Whitelist check
    allowed_prefixes = _WRITE_ALLOWED_PREFIXES if write else _READ_ALLOWED_PREFIXES
    allowed = any(clean.startswith(p) for p in allowed_prefixes) or (
        clean in _ALLOWED_ROOT_FILES
    )
    if not allowed:
        mode = "write" if write else "read"
        raise HTTPException(
            403,
            f"Access denied for {mode}. Allowed: {list(allowed_prefixes)} + {list(_ALLOWED_ROOT_FILES)}",
        )

    if is_secret_like_path(clean):
        raise HTTPException(403, "Credential / secret files are not accessible via this API.")

    return target, clean


def _guess_media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "application/json"
    if suffix in {".yaml", ".yml"}:
        return "application/yaml"
    if suffix == ".md":
        return "text/markdown"
    return "text/plain; charset=utf-8"


def _read_raw_content(target: Path, clean_path: str) -> str:
    content = target.read_text(encoding="utf-8")
    if not clean_path.startswith(_REFERENCE_SCHEMA_PREFIX) or target.suffix.lower() != ".json":
        return content

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return content
    if not isinstance(payload, dict):
        return content

    payload["$id"] = public_raw_file_url(clean_path)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# ------------------------------------------------------------------ #
# Read                                                                 #
# ------------------------------------------------------------------ #


@router.get("/files")
def read_file(path: str = Query(..., description="Relative file path"), request: Request = None):
    require_inspection_access(request)
    target, _ = _check_path(path, write=False)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    content = target.read_text(encoding="utf-8")
    return {"path": path, "content": content}


@router.get("/files/raw")
def read_raw_file(path: str = Query(..., description="Relative file path"), request: Request = None):
    require_inspection_access(request)
    target, clean = _check_path(path, write=False)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    media_type = _guess_media_type(target)

    if clean.startswith(_REFERENCE_SCHEMA_PREFIX) and target.suffix.lower() == ".json":
        return Response(
            content=_read_raw_content(target, clean).encode("utf-8"),
            media_type=media_type,
        )

    return Response(content=target.read_bytes(), media_type=media_type)


# ------------------------------------------------------------------ #
# Streamed Range read                                                  #
# ------------------------------------------------------------------ #


class _RangeNotSatisfiable(Exception):
    pass


def _etag_for(stat_result) -> str:
    # Weak validator: size + mtime_ns uniquely identifies the backing bytes for
    # sequential writers without hashing the file.
    raw = f"{stat_result.st_size}-{stat_result.st_mtime_ns}".encode("utf-8")
    return 'W/"' + hashlib.sha256(raw).hexdigest()[:32] + '"'


def _parse_range_header(value: str, file_size: int) -> tuple[int, int]:
    """Parse a single `bytes=start-end` range spec. Suffix (-N) supported.

    Returns an inclusive (start, end) tuple. Raises _RangeNotSatisfiable when
    the spec is malformed or falls outside the file.
    """
    header = value.strip().lower()
    if not header.startswith("bytes="):
        raise _RangeNotSatisfiable
    spec = header[len("bytes="):]
    # Multi-range requests are uncommon for artifacts; we honor the first range
    # only and let clients fall back to full download if they need more.
    first = spec.split(",", 1)[0].strip()
    if "-" not in first:
        raise _RangeNotSatisfiable
    start_s, end_s = first.split("-", 1)
    start_s, end_s = start_s.strip(), end_s.strip()

    if file_size == 0:
        raise _RangeNotSatisfiable

    if not start_s and end_s:
        # Suffix form: last N bytes.
        try:
            suffix = int(end_s)
        except ValueError:
            raise _RangeNotSatisfiable
        if suffix <= 0:
            raise _RangeNotSatisfiable
        start = max(0, file_size - suffix)
        end = file_size - 1
    else:
        try:
            start = int(start_s)
        except ValueError:
            raise _RangeNotSatisfiable
        end = file_size - 1 if not end_s else int(end_s)
        if start < 0 or end < start or start >= file_size:
            raise _RangeNotSatisfiable
        end = min(end, file_size - 1)
    return start, end


def _iter_file_range(target: Path, start: int, length: int, chunk_size: int):
    remaining = length
    if remaining <= 0:
        return
    with open(target, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/files/stream")
def stream_file(
    path: str = Query(..., description="Relative file path"),
    request: Request = None,
):
    """Stream a whitelisted file, honoring HTTP Range / If-Range semantics."""
    require_inspection_access(request)
    target, _ = _check_path(path, write=False)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    stat = target.stat()
    file_size = stat.st_size
    etag = _etag_for(stat)
    last_modified = formatdate(stat.st_mtime, usegmt=True)
    media_type = _guess_media_type(target)

    range_header = request.headers.get("range") if request is not None else None
    if_range = request.headers.get("if-range") if request is not None else None

    start, end = 0, (file_size - 1 if file_size > 0 else 0)
    is_partial = False

    if range_header:
        # If-Range: when present, only honor Range if the validator matches
        # the current representation; otherwise fall back to a full 200.
        validator_ok = True
        if if_range:
            validator_ok = if_range.strip() in {etag, last_modified}
        if validator_ok:
            try:
                start, end = _parse_range_header(range_header, file_size)
            except _RangeNotSatisfiable:
                raise HTTPException(
                    status_code=416,
                    detail="Requested range not satisfiable.",
                    headers={
                        "Content-Range": f"bytes */{file_size}",
                        "Accept-Ranges": "bytes",
                    },
                )
            is_partial = True

    length = max(0, end - start + 1) if file_size > 0 else 0

    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Last-Modified": last_modified,
        "Content-Length": str(length),
    }
    if is_partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"

    return StreamingResponse(
        _iter_file_range(target, start, length, _STREAM_CHUNK_BYTES),
        status_code=206 if is_partial else 200,
        media_type=media_type,
        headers=headers,
    )


# ------------------------------------------------------------------ #
# Write                                                                #
# ------------------------------------------------------------------ #


class SaveRequest(BaseModel):
    path: str
    content: str


@router.post("/files")
def save_file(body: SaveRequest, request: Request = None):
    require_execution_access(request)
    base_dir = _base_dir()
    byte_count = len(body.content.encode("utf-8"))
    policy = cfg.get_production_hardening_policy()
    if not policy.api.files_write_enabled:
        append_file_written_event(
            base_dir,
            path=body.path,
            source="api.files",
            outcome="blocked",
            byte_count=byte_count,
            reason="File editor writes disabled by production hardening policy.",
        )
        raise HTTPException(403, "File editor writes are disabled by production hardening policy.")

    if byte_count > _MAX_SAVE_BYTES:
        append_file_written_event(
            base_dir,
            path=body.path,
            source="api.files",
            outcome="invalid_input",
            byte_count=byte_count,
            reason=f"Content too large: max {_MAX_SAVE_BYTES // 1000} KB.",
        )
        raise HTTPException(
            400, f"Content too large: max {_MAX_SAVE_BYTES // 1000} KB."
        )

    try:
        target, clean = _check_path(body.path, write=True)
    except HTTPException as exc:
        append_file_written_event(
            base_dir,
            path=body.path,
            source="api.files",
            outcome="blocked" if exc.status_code == 403 else "invalid_input",
            byte_count=byte_count,
            reason=str(exc.detail),
        )
        raise

    memory_validation_errors = validate_memory_write(clean, body.content)
    if memory_validation_errors:
        reason = " ".join(memory_validation_errors)
        append_file_written_event(
            base_dir,
            path=clean,
            source="api.files",
            outcome="invalid_input",
            byte_count=byte_count,
            reason=reason,
        )
        raise HTTPException(400, reason)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.content, encoding="utf-8")
    except Exception as exc:
        append_file_written_event(
            base_dir,
            path=clean,
            source="api.files",
            outcome="execution_failure",
            byte_count=byte_count,
            reason=str(exc),
        )
        raise

    # Rebuild memory index after any memory/ write so multi-file memory stays fresh.
    if clean.startswith("memory/"):
        try:
            from graph.agent import agent_manager

            if agent_manager.memory_indexer:
                agent_manager.memory_indexer.rebuild_index()
        except Exception:
            pass

    append_file_written_event(
        base_dir,
        path=clean,
        source="api.files",
        outcome="written",
        byte_count=byte_count,
    )
    return {"path": body.path, "saved": True}


# ------------------------------------------------------------------ #
# Streamed chunked write                                               #
# ------------------------------------------------------------------ #


def _check_stream_write_path(relative_path: str) -> tuple[Path, str]:
    """Path check for the streaming PUT. Strictly restricted to artifacts/.

    Mirrors the safety checks in `_check_path` but uses a tighter whitelist so
    the editor POST surface is not widened by large streamed uploads.
    """
    clean = relative_path.strip().lstrip("/").removeprefix("./")
    if ".." in clean.split("/"):
        raise HTTPException(403, "Path traversal is not allowed.")

    base = _base_dir()
    target = (base / clean).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(403, "Path is outside the project directory.")

    if not any(clean.startswith(p) for p in _STREAM_WRITE_ALLOWED_PREFIXES):
        raise HTTPException(
            403,
            f"Streamed writes are restricted to {list(_STREAM_WRITE_ALLOWED_PREFIXES)}.",
        )

    if is_secret_like_path(clean):
        raise HTTPException(403, "Credential / secret files are not accessible via this API.")

    return target, clean


@router.put("/files/stream")
async def stream_write_file(
    path: str = Query(..., description="Relative file path (must start with artifacts/)"),
    request: Request = None,
):
    """Incrementally write a request body under `artifacts/` without buffering.

    Request bytes are consumed from `request.stream()` and flushed to disk in
    fixed-size chunks so memory stays flat regardless of payload size. Partial
    writes (client disconnect / I/O failure mid-stream) are audited with the
    number of bytes already persisted.
    """
    require_execution_access(request)
    base_dir = _base_dir()
    policy = cfg.get_production_hardening_policy()

    if not policy.api.files_write_enabled:
        append_file_written_event(
            base_dir,
            path=path,
            source="api.files.stream",
            outcome="blocked",
            byte_count=0,
            reason="Streamed writes disabled by production hardening policy.",
        )
        raise HTTPException(403, "Streamed writes are disabled by production hardening policy.")

    try:
        target, clean = _check_stream_write_path(path)
    except HTTPException as exc:
        append_file_written_event(
            base_dir,
            path=path,
            source="api.files.stream",
            outcome="blocked" if exc.status_code == 403 else "invalid_input",
            byte_count=0,
            reason=str(exc.detail),
        )
        raise

    target.parent.mkdir(parents=True, exist_ok=True)

    byte_count = 0
    outcome = "written"
    reason: str | None = None

    try:
        # Open in truncating binary mode; each request overwrites the artifact.
        with open(target, "wb") as fh:
            async for chunk in request.stream():
                if not chunk:
                    continue
                fh.write(chunk)
                byte_count += len(chunk)
    except ClientDisconnect as exc:
        outcome = "partial"
        reason = f"Client disconnected after {byte_count} bytes: {exc}"
    except Exception as exc:  # noqa: BLE001 — audit every write failure path
        outcome = "execution_failure"
        reason = f"Write failed after {byte_count} bytes: {exc}"

    append_file_written_event(
        base_dir,
        path=clean,
        source="api.files.stream",
        outcome=outcome,
        byte_count=byte_count,
        reason=reason,
    )

    if outcome != "written":
        raise HTTPException(500, reason or f"Streamed write failed after {byte_count} bytes.")

    return {"path": clean, "bytes_written": byte_count, "saved": True}


# ------------------------------------------------------------------ #
# Skills list                                                          #
# ------------------------------------------------------------------ #


@router.get("/skills")
def list_skills(request: Request = None):
    """Return the active runtime-selected skill summary used by compatibility clients."""
    require_inspection_access(request)
    base = _base_dir()
    from tools.skills_scanner import collect_skill_entries

    skills = []
    for entry in collect_skill_entries(base, respect_enabled=True):
        # Keep the compatibility surface intentionally narrow; richer routing
        # and selection metadata belongs on /api/skills/registry.
        skills.append(
            {
                "name": entry["name"],
                "path": entry["location"].removeprefix("./"),
                "category": entry.get("category", ""),
                "stage": entry.get("stage", ""),
            }
        )
    return skills


@router.get("/skills/registry")
def list_skills_registry(request: Request = None):
    """Return the full runtime registry, including disabled entries and optional hint metadata."""
    require_inspection_access(request)
    base = _base_dir()
    from tools.skills_scanner import describe_skill_registry

    registry = []
    for entry in describe_skill_registry(base):
        registry.append(
            {
                **entry,
                "location": entry["location"].removeprefix("./"),
            }
        )
    return registry
