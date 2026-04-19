"""Per-directory retention / quota enforcement for on-disk state.

Configured via the ``retention`` block of the layered runtime config. Each
entry describes a directory under ``backend/`` together with a byte cap
(``max_bytes``), an age cap in days (``max_age_days``), and an eviction
strategy (``fifo`` — oldest ``mtime`` first, or ``lru`` — oldest ``atime``
first). Directories are resolved relative to the runtime root
(``agent_manager.base_dir`` / ``BASE_DIR`` in ``app.py``) and guarded by the
same write whitelist enforced by ``backend/api/files.py`` plus ``sessions/``.

Entry point: :func:`apply_retention`. Typical use is a one-shot startup
invocation; callers can also fire it from a scheduled hook.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

logger = logging.getLogger(__name__)

Strategy = Literal["fifo", "lru"]

# Dirs retention is ever allowed to touch. Mirrors the read/write whitelist
# used by ``backend/api/files.py`` (plus ``sessions/``, which the file API
# does not expose but which the retention runner manages). Anything outside
# this list is skipped with a warning so misconfiguration cannot delete, for
# example, ``backend/`` itself.
ALLOWED_RETENTION_PREFIXES: tuple[str, ...] = (
    "workspace/",
    "memory/",
    "skills/",
    "knowledge/",
    "artifacts/",
    "sessions/",
)

# Filenames retention must never touch even when inside an allowed root. These
# are index sidecars rebuilt by other code paths; deleting them would corrupt
# archive lookup or memory retrieval.
_DEFAULT_PROTECTED_NAMES: frozenset[str] = frozenset(
    {
        "MEMORY.md",
        "archive.index.json",
    }
)

VALID_STRATEGIES: tuple[Strategy, ...] = ("fifo", "lru")


@dataclass(frozen=True)
class RetentionDirConfig:
    """Normalised retention policy for a single directory."""

    key: str
    path: str  # relative to base_dir, normalised with trailing slash stripped
    max_bytes: int | None
    max_age_days: float | None
    strategy: Strategy
    protect: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RetentionAction:
    """One planned or performed deletion."""

    path: Path
    size_bytes: int
    reason: Literal["age", "quota"]
    deleted: bool


@dataclass(frozen=True)
class RetentionDirResult:
    key: str
    path: str
    strategy: Strategy
    dry_run: bool
    scanned_files: int
    scanned_bytes: int
    actions: tuple[RetentionAction, ...]
    skipped_reason: str | None = None

    @property
    def deleted_bytes(self) -> int:
        return sum(a.size_bytes for a in self.actions if a.deleted)

    @property
    def planned_bytes(self) -> int:
        return sum(a.size_bytes for a in self.actions)


@dataclass(frozen=True)
class RetentionRunResult:
    dry_run: bool
    results: tuple[RetentionDirResult, ...]


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def _coerce_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass — treat as invalid
        return None
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _coerce_positive_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _coerce_strategy(value: Any) -> Strategy:
    if isinstance(value, str):
        token = value.strip().lower()
        if token in VALID_STRATEGIES:
            return token  # type: ignore[return-value]
    return "fifo"


def _normalise_path(raw: Any, key: str) -> str | None:
    candidate = raw if isinstance(raw, str) and raw.strip() else key
    clean = str(candidate).strip().lstrip("/").removeprefix("./").rstrip("/")
    if not clean:
        return None
    if ".." in clean.split("/"):
        return None
    return clean


def parse_retention_config(raw: Any) -> tuple[list[RetentionDirConfig], bool]:
    """Normalise the ``retention`` config block.

    Returns ``(dirs, dry_run_default)``. Missing/invalid input yields an
    empty list so the runner is a no-op when nothing is configured.
    """
    if not isinstance(raw, dict):
        return [], False

    dry_run_default = bool(raw.get("dry_run", False))
    paths_raw = raw.get("paths", {})
    if not isinstance(paths_raw, dict):
        return [], dry_run_default

    dirs: list[RetentionDirConfig] = []
    for key, entry in paths_raw.items():
        if not isinstance(entry, dict):
            continue
        normalised = _normalise_path(entry.get("path"), key)
        if normalised is None:
            logger.warning("retention: dropping entry %r — invalid path", key)
            continue
        max_bytes = _coerce_positive_int(entry.get("max_bytes"))
        max_age_days = _coerce_positive_number(entry.get("max_age_days"))
        strategy = _coerce_strategy(entry.get("strategy"))
        if max_bytes is None and max_age_days is None:
            # A dir with neither cap is either noise or a placeholder — skip
            # it rather than walk the filesystem for nothing.
            continue
        protect_raw = entry.get("protect", [])
        if isinstance(protect_raw, (list, tuple)):
            protect = frozenset(str(x) for x in protect_raw if isinstance(x, str))
        else:
            protect = frozenset()
        dirs.append(
            RetentionDirConfig(
                key=str(key),
                path=normalised,
                max_bytes=max_bytes,
                max_age_days=max_age_days,
                strategy=strategy,
                protect=protect,
            )
        )
    return dirs, dry_run_default


# ---------------------------------------------------------------------------
# Whitelist + filesystem scan
# ---------------------------------------------------------------------------


def _target_dir(base_dir: Path, relative: str) -> tuple[Path | None, str | None]:
    """Resolve ``relative`` under ``base_dir``, enforcing the whitelist.

    Returns ``(resolved_path, skip_reason)``. On any whitelist / traversal
    violation, ``resolved_path`` is ``None`` and ``skip_reason`` explains why.
    """
    # Retention is allowed to operate inside the whitelisted prefix roots
    # themselves and anything nested under them. An exact match against the
    # bare prefix (``sessions`` with no trailing slash) is accepted too.
    normalised = relative.rstrip("/")
    candidate_prefixes = tuple(p.rstrip("/") for p in ALLOWED_RETENTION_PREFIXES)
    if not any(
        normalised == p or normalised.startswith(p + "/")
        for p in candidate_prefixes
    ):
        return None, f"path {relative!r} is outside the retention whitelist"

    resolved_base = base_dir.resolve()
    resolved = (base_dir / normalised).resolve()
    try:
        resolved.relative_to(resolved_base)
    except ValueError:
        return None, f"path {relative!r} resolves outside base_dir"
    return resolved, None


def _iter_candidate_files(root: Path) -> Iterable[Path]:
    for child in root.rglob("*"):
        if child.is_symlink():
            continue
        if not child.is_file():
            continue
        yield child


def _is_protected(path: Path, protect: frozenset[str]) -> bool:
    if path.name in _DEFAULT_PROTECTED_NAMES:
        return True
    if path.name in protect:
        return True
    return False


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------


def _apply_for_dir(
    base_dir: Path,
    config: RetentionDirConfig,
    *,
    dry_run: bool,
    now: float,
) -> RetentionDirResult:
    target, skip_reason = _target_dir(base_dir, config.path)
    if target is None:
        return RetentionDirResult(
            key=config.key,
            path=config.path,
            strategy=config.strategy,
            dry_run=dry_run,
            scanned_files=0,
            scanned_bytes=0,
            actions=(),
            skipped_reason=skip_reason,
        )
    if not target.exists() or not target.is_dir():
        return RetentionDirResult(
            key=config.key,
            path=config.path,
            strategy=config.strategy,
            dry_run=dry_run,
            scanned_files=0,
            scanned_bytes=0,
            actions=(),
            skipped_reason=None,
        )

    # Collect (path, size, sort_key) tuples. ``sort_key`` is mtime for FIFO
    # and atime for LRU; both are seconds since epoch.
    entries: list[tuple[Path, int, float, float]] = []  # path, size, mtime, atime
    for path in _iter_candidate_files(target):
        if _is_protected(path, config.protect):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((path, stat.st_size, stat.st_mtime, stat.st_atime))

    scanned_files = len(entries)
    scanned_bytes = sum(size for _, size, _, _ in entries)

    sort_key_fn = (lambda item: item[2]) if config.strategy == "fifo" else (lambda item: item[3])
    entries.sort(key=sort_key_fn)

    actions: list[RetentionAction] = []
    remaining_bytes = scanned_bytes
    kept: list[tuple[Path, int, float, float]] = []

    # Pass 1 — age eviction.
    age_cutoff: float | None = None
    if config.max_age_days is not None:
        age_cutoff = now - (config.max_age_days * 86_400.0)

    for entry in entries:
        path, size, mtime, atime = entry
        if age_cutoff is not None:
            age_ref = mtime if config.strategy == "fifo" else atime
            if age_ref < age_cutoff:
                actions.append(
                    RetentionAction(
                        path=path,
                        size_bytes=size,
                        reason="age",
                        deleted=not dry_run,
                    )
                )
                remaining_bytes -= size
                continue
        kept.append(entry)

    # Pass 2 — byte quota, evicting from the head of the already-sorted list.
    if config.max_bytes is not None:
        idx = 0
        while remaining_bytes > config.max_bytes and idx < len(kept):
            path, size, _, _ = kept[idx]
            actions.append(
                RetentionAction(
                    path=path,
                    size_bytes=size,
                    reason="quota",
                    deleted=not dry_run,
                )
            )
            remaining_bytes -= size
            idx += 1

    if not dry_run:
        for action in actions:
            try:
                action.path.unlink()
            except FileNotFoundError:
                # Another process beat us to it; treat as already-deleted.
                pass
            except OSError as exc:
                logger.warning(
                    "retention: failed to delete %s (%s)", action.path, exc
                )

    return RetentionDirResult(
        key=config.key,
        path=config.path,
        strategy=config.strategy,
        dry_run=dry_run,
        scanned_files=scanned_files,
        scanned_bytes=scanned_bytes,
        actions=tuple(actions),
        skipped_reason=None,
    )


def apply_retention(
    base_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    dry_run: bool | None = None,
    now: float | None = None,
) -> RetentionRunResult:
    """Run retention for every directory configured in the runtime config.

    Parameters
    ----------
    base_dir:
        Runtime root (``backend/``). Retention paths resolve under this root.
    config:
        Explicit retention block. When ``None``, the runner loads the layered
        runtime config via :func:`config.get_retention_settings`. The explicit
        override exists primarily for tests.
    dry_run:
        Force the runner into dry-run mode. When ``None``, the config's
        ``dry_run`` key is used. Dry runs log what would be deleted but leave
        the filesystem untouched.
    now:
        Unix timestamp used as the reference for age cutoffs. Defaults to
        ``time.time()``. Exposed for deterministic tests.
    """
    if config is None:
        # Import lazily so this module can be loaded in tests that patch
        # ``config._CONFIG_FILE`` before ``backend.config`` is imported.
        from config import get_retention_settings

        raw = get_retention_settings()
    else:
        raw = config

    dirs, dry_run_default = parse_retention_config(raw)
    effective_dry_run = dry_run_default if dry_run is None else bool(dry_run)
    reference_time = time.time() if now is None else float(now)

    if not dirs:
        return RetentionRunResult(dry_run=effective_dry_run, results=())

    results: list[RetentionDirResult] = []
    for entry in dirs:
        result = _apply_for_dir(
            base_dir, entry, dry_run=effective_dry_run, now=reference_time
        )
        if result.skipped_reason:
            logger.warning(
                "retention: skipped %s (%s)", result.key, result.skipped_reason
            )
        elif result.actions:
            logger.info(
                "retention: %s %s → %d file(s), %d bytes%s",
                "would delete" if effective_dry_run else "deleted",
                result.key,
                len(result.actions),
                result.planned_bytes if effective_dry_run else result.deleted_bytes,
                " [dry-run]" if effective_dry_run else "",
            )
        results.append(result)

    return RetentionRunResult(dry_run=effective_dry_run, results=tuple(results))


__all__ = [
    "ALLOWED_RETENTION_PREFIXES",
    "RetentionAction",
    "RetentionDirConfig",
    "RetentionDirResult",
    "RetentionRunResult",
    "VALID_STRATEGIES",
    "apply_retention",
    "parse_retention_config",
]
