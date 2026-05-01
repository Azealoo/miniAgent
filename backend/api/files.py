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
from graph.memory_writer import MemoryFrontmatterError, write_memory_file
from hardening import is_secret_like_path
from pydantic import BaseModel
from rate_limit import check_rate_limit
from starlette.requests import ClientDisconnect

router = APIRouter()

# Paths the API is allowed to serve (relative to base_dir).
# ``storage/tool-outputs/`` is included so the chat UI can fetch the full-text
# spill file linked from a ``tool_output_overflow`` ToolArtifactRef (issue #129).
_READ_ALLOWED_PREFIXES = (
    "workspace/",
    "memory/",
    "skills/",
    "knowledge/",
    "artifacts/",
    "storage/tool-outputs/",
)
_WRITE_ALLOWED_PREFIXES = ("workspace/", "memory/", "skills/", "knowledge/")
# Streamed writes are gated strictly to artifacts/ so the editor POST whitelist
# is not widened for large, tool-produced payloads.
_STREAM_WRITE_ALLOWED_PREFIXES = ("artifacts/",)
_ALLOWED_ROOT_FILES = {"SKILLS_SNAPSHOT.md"}
_MAX_SAVE_BYTES = 500_000  # 500 KB limit for writes via the editor API
_STREAM_CHUNK_BYTES = 1 << 20  # 1 MiB per disk read/write, bounds peak memory
_REFERENCE_SCHEMA_PREFIX = "artifacts/reference_schemas/"

# Runtime config surfaces that are frozen once a turn starts. Live edits via
# the file API would otherwise let an in-flight turn pick up a different tool
# policy, hardening posture, or hook configuration than the one captured at
# turn entry. ``.env`` files are additionally covered by ``is_secret_like_path``
# but are listed here so the rejection message is explicit.
_FROZEN_CONFIG_FILES = frozenset(
    {
        "config.json",
        "config.local.json",
        "runtime/hooks.py",
    }
)
_FROZEN_CONFIG_SUFFIXES = (".env",)
_FROZEN_CONFIG_MESSAGE = (
    "Runtime config files are frozen once a turn starts and cannot be "
    "rewritten through the file API. Set BIOAPEX_ALLOW_CONFIG_RELOAD=1 in "
    "the backend environment to opt back into live edits during development."
)


def _is_frozen_config_path(clean: str) -> bool:
    """Return True for paths that should be treated as frozen runtime config."""
    if clean in _FROZEN_CONFIG_FILES:
        return True
    name = clean.rsplit("/", 1)[-1]
    if name.startswith(".env") or any(name.endswith(s) for s in _FROZEN_CONFIG_SUFFIXES):
        return True
    return False


def _base_dir() -> Path:
    from graph.agent import agent_manager

    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _check_path(relative_path: str, *, write: bool = False) -> tuple[Path, str]:
    """Validate path against whitelist.

    Returns (resolved_absolute_path, normalized_relative_path).
    Raises HTTPException on any violation.

    Ordering contract: strip -> reject '..' -> resolve -> confirm under base
    via relative_to() -> derive the normalized relative path from the resolved
    target -> run frozen-config / whitelist / secret checks against that
    derived path. Applying the whitelist to raw input is fragile (prefix-name
    tricks, symlink traversal); deriving from the resolved target fixes that.
    """
    # Strip leading slash or ./
    clean = relative_path.strip().lstrip("/").removeprefix("./")

    # Traversal guard — reject '..' before any disk access.
    if ".." in clean.split("/"):
        raise HTTPException(403, "Path traversal is not allowed.")

    base = _base_dir().resolve()
    target = (base / clean).resolve()

    # Confirm target lives under base. This is what defeats prefix-name and
    # symlink escapes; the whitelist below is then applied to the *resolved*
    # relative path rather than the raw user input.
    try:
        resolved_relative = target.relative_to(base)
    except ValueError:
        raise HTTPException(403, "Path is outside the project directory.")

    # Platform-independent relative path for whitelist / audit comparisons.
    clean = resolved_relative.as_posix()

    # Runtime config files are frozen during a turn. Reject writes with a
    # clear, specific message (instead of the generic whitelist error) unless
    # the dev override env var is set. Read is unaffected.
    if write and _is_frozen_config_path(clean) and not cfg.config_reload_allowed():
        raise HTTPException(403, _FROZEN_CONFIG_MESSAGE)

    # Whitelist check — against the resolved relative path.
    allowed_prefixes = _WRITE_ALLOWED_PREFIXES if write else _READ_ALLOWED_PREFIXES
    allowed = any(clean.startswith(p) for p in allowed_prefixes) or (
        clean in _ALLOWED_ROOT_FILES
    )
    if write and cfg.config_reload_allowed() and _is_frozen_config_path(clean):
        allowed = True

    if not allowed:
        mode = "write" if write else "read"
        raise HTTPException(
            403,
            f"Access denied for {mode}. Allowed: {list(allowed_prefixes)} + {list(_ALLOWED_ROOT_FILES)}",
        )

    # The secret-like check still applies to read paths and to non-frozen
    # writes. When the dev override explicitly permits a config/.env rewrite
    # we let it through so the reload gate actually works.
    if is_secret_like_path(clean):
        if not (write and cfg.config_reload_allowed() and _is_frozen_config_path(clean)):
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
    check_rate_limit(request, "files_read")
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
    check_rate_limit(request, "files_read")
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


@router.head("/files/stream")
def head_stream_file(
    path: str = Query(..., description="Relative file path"),
    request: Request = None,
):
    """Return size + content-type metadata for a streamable file without a body.

    Lets clients sniff `Content-Length`, `Content-Type`, and the `Accept-Ranges`
    advertisement before deciding whether to issue Range requests. The handler
    only `stat()`s the file — no read I/O — so a HEAD against a multi-GiB
    artifact stays cheap.
    """
    require_inspection_access(request)
    target, _ = _check_path(path, write=False)
    if not target.exists():
        raise HTTPException(404, f"File not found: {path}")
    if not target.is_file():
        raise HTTPException(400, f"Not a file: {path}")

    stat = target.stat()
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": _etag_for(stat),
        "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
        "Content-Length": str(stat.st_size),
    }
    return Response(status_code=200, media_type=_guess_media_type(target), headers=headers)


@router.get("/files/stream")
def stream_file(
    path: str = Query(..., description="Relative file path"),
    request: Request = None,
):
    """Stream a whitelisted file, honoring HTTP Range / If-Range semantics."""
    require_inspection_access(request)
    check_rate_limit(request, "files_read")
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
    check_rate_limit(request, "files_write")
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

    try:
        write_memory_file(target, clean, body.content)
    except MemoryFrontmatterError as exc:
        reason = str(exc)
        append_file_written_event(
            base_dir,
            path=clean,
            source="api.files",
            outcome="invalid_input",
            byte_count=byte_count,
            reason=reason,
        )
        raise HTTPException(400, reason)
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

    Mirrors the resolve-first ordering in `_check_path` but with a tighter
    whitelist so the editor POST surface is not widened by large streamed
    uploads.
    """
    clean = relative_path.strip().lstrip("/").removeprefix("./")
    if ".." in clean.split("/"):
        raise HTTPException(403, "Path traversal is not allowed.")

    base = _base_dir().resolve()
    target = (base / clean).resolve()
    try:
        resolved_relative = target.relative_to(base)
    except ValueError:
        raise HTTPException(403, "Path is outside the project directory.")

    clean = resolved_relative.as_posix()

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
    check_rate_limit(request, "files_write")
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
    check_rate_limit(request, "files_read")
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
    check_rate_limit(request, "files_read")
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
