"""
Skills registry API: list, enable/disable, and get details of skills.

GET  /api/skills/registry         — list all skills with metadata + enabled status
PUT  /api/skills/registry/{name}  — enable or disable a skill by name
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _base_dir() -> Path:
    from graph.agent import agent_manager
    assert agent_manager.base_dir is not None
    return agent_manager.base_dir


def _load_config() -> dict:
    import config as cfg
    return cfg._load()


def _save_config(data: dict) -> None:
    import config as cfg
    cfg._save(data)


def _scan_skills_meta(base_dir: Path) -> list[dict]:
    """Collect all skill frontmatter from skills directory."""
    import yaml

    skills: list[dict] = []
    skills_dir = base_dir / "skills"
    if not skills_dir.exists():
        return skills

    for skill_md in sorted(skills_dir.rglob("SKILL.md")):
        try:
            content = skill_md.read_text(encoding="utf-8")
            parts = content.split("---", 2)
            fm = {}
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1]) or {}
                except Exception:
                    pass
            name = fm.get("name", skill_md.parent.name)
            skills.append({
                "name": name,
                "description": fm.get("description", ""),
                "category": fm.get("category", ""),
                "version": fm.get("version", ""),
                "requires_tools": fm.get("requires_tools", []),
                "requires_network": fm.get("requires_network", False),
                "user_invocable": fm.get("user_invocable", True),
                "location": str(skill_md.relative_to(base_dir)),
            })
        except Exception:
            continue
    return skills


@router.get("/skills/registry")
def list_registry():
    base = _base_dir()
    import config as cfg
    skills_meta = _scan_skills_meta(base)
    cfg_data = _load_config()
    entries = cfg_data.get("skills", {}).get("entries", {})
    result = []
    for s in skills_meta:
        name = s["name"]
        enabled = bool(entries.get(name, {}).get("enabled", True)) if name in entries else True
        result.append({**s, "enabled": enabled})
    return result


class SkillEntryUpdate(BaseModel):
    enabled: bool


@router.put("/skills/registry/{skill_name}")
def update_skill_entry(skill_name: str, body: SkillEntryUpdate):
    import config as cfg
    with cfg._config_lock:
        data = cfg._load()
        if "skills" not in data:
            data["skills"] = {"extra_dirs": [], "entries": {}}
        if "entries" not in data["skills"]:
            data["skills"]["entries"] = {}
        data["skills"]["entries"][skill_name] = {"enabled": body.enabled}
        cfg._save(data)
    # Rescan so SKILLS_SNAPSHOT.md reflects the change
    from tools.skills_scanner import scan_skills
    scan_skills(_base_dir())
    return {"name": skill_name, "enabled": body.enabled}
