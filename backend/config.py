import json
from pathlib import Path

_CONFIG_FILE = Path(__file__).parent / "config.json"
_DEFAULT: dict = {"rag_mode": False}


def _load() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text())
        except Exception:
            pass
    return dict(_DEFAULT)


def _save(cfg: dict) -> None:
    _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def get_rag_mode() -> bool:
    return _load().get("rag_mode", False)


def set_rag_mode(enabled: bool) -> None:
    cfg = _load()
    cfg["rag_mode"] = enabled
    _save(cfg)
