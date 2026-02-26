import json
import os
import tempfile
import threading
from pathlib import Path

_CONFIG_FILE = Path(__file__).parent / "config.json"
# Protects all read-modify-write operations so concurrent API calls can't
# overwrite each other's changes.
_config_lock = threading.Lock()
_DEFAULT: dict = {
    "rag_mode": False,
    "skills": {
        "extra_dirs": [],
        "entries": {},
    },
    "read_file_extra_roots": [],
}


def _load() -> dict:
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text())
            # Merge with defaults so new keys exist
            merged = dict(_DEFAULT)
            merged.update(data)
            if "skills" in data and isinstance(data["skills"], dict):
                merged.setdefault("skills", {}).setdefault("extra_dirs", [])
                merged.setdefault("skills", {}).setdefault("entries", {})
                merged["skills"].update(data["skills"])
            return merged
        except Exception:
            pass
    return dict(_DEFAULT)


def _save(cfg: dict) -> None:
    """Write config atomically: write to a temp file then rename.

    os.replace() is atomic on POSIX (Linux/macOS) — readers either see the
    old file or the new file, never a partial write.  This prevents corruption
    when the process is killed mid-write.
    """
    content = json.dumps(cfg, indent=2)
    dir_path = _CONFIG_FILE.parent
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, str(_CONFIG_FILE))  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def get_rag_mode() -> bool:
    return _load().get("rag_mode", False)


def set_rag_mode(enabled: bool) -> None:
    with _config_lock:
        cfg = _load()
        cfg["rag_mode"] = enabled
        _save(cfg)


def get_skills_extra_dirs(base_dir: Path) -> list[Path]:
    """Return list of extra skill directories (absolute paths)."""
    cfg = _load()
    extra = cfg.get("skills", {}).get("extra_dirs", [])
    result = []
    for p in extra:
        path = Path(p).expanduser()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if path.exists():
            result.append(path)
    return result


def get_skill_enabled(skill_name: str) -> bool:
    """Return True if skill is enabled. Missing entry means enabled."""
    cfg = _load()
    entries = cfg.get("skills", {}).get("entries", {})
    if skill_name not in entries:
        return True
    return bool(entries[skill_name].get("enabled", True))


def get_read_file_extra_roots(base_dir: Path) -> list[Path]:
    """Return list of additional allowed roots for read_file (absolute paths)."""
    cfg = _load()
    raw = cfg.get("read_file_extra_roots", [])
    result = []
    for p in raw:
        path = Path(p).expanduser().resolve()
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if path.exists():
            result.append(path)
    # Allow repo root .agents/skills by default
    repo_root = base_dir.parent
    agents_skills = repo_root / ".agents" / "skills"
    if agents_skills.exists() and repo_root not in result:
        result.append(repo_root)
    return result
