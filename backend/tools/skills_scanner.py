"""
Scans skill directories, parses YAML frontmatter, and generates
SKILLS_SNAPSHOT.md for the agent's system prompt.

Supports:
- Local skills at backend/skills/ (recursive: skills/**/SKILL.md)
- Extra directories via config skills.extra_dirs
- Project-scoped .agents/skills/ from repo root (if present)
- Per-skill enable/disable via config skills.entries.<name>.enabled
"""
from pathlib import Path
from typing import Any, Optional

import yaml


def _get_config():
    import config as cfg

    return cfg


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def iter_skill_files(base_dir: Path) -> list[tuple[Path, Path]]:
    """Return all candidate (root_dir, SKILL.md) pairs in precedence order."""
    config = _get_config()
    candidates: list[tuple[Path, Path]] = []

    skills_dir = base_dir / "skills"
    if skills_dir.exists():
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            candidates.append((skills_dir, skill_md))

    for extra_dir in config.get_skills_extra_dirs(base_dir):
        if extra_dir.exists():
            for skill_md in sorted(extra_dir.rglob("SKILL.md")):
                candidates.append((extra_dir, skill_md))

    repo_root = base_dir.parent
    agents_skills = repo_root / ".agents" / "skills"
    if agents_skills.exists():
        for skill_md in sorted(agents_skills.rglob("SKILL.md")):
            candidates.append((agents_skills, skill_md))

    return candidates


def parse_skill_entry(base_dir: Path, root_dir: Path, skill_md: Path) -> Optional[dict[str, Any]]:
    """Parse a single SKILL.md into normalized metadata."""
    try:
        content = skill_md.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(content)
        name = frontmatter.get("name", skill_md.parent.name)

        try:
            relative_location = skill_md.relative_to(base_dir)
            location = f"./{relative_location}"
        except ValueError:
            location = str(skill_md)

        try:
            relative_source = skill_md.relative_to(root_dir)
            source_path = str(relative_source)
        except ValueError:
            source_path = str(skill_md)

        return {
            "name": name,
            "description": _normalize_text(frontmatter.get("description", "")),
            "location": location,
            "source_path": source_path,
            "category": _normalize_text(frontmatter.get("category", "")),
            "version": _normalize_text(frontmatter.get("version", "")),
            "tags": _normalize_list(frontmatter.get("tags")),
            "aliases": _normalize_list(frontmatter.get("aliases")),
            "requires_tools": _normalize_list(frontmatter.get("requires_tools")),
            "requires_network": bool(frontmatter.get("requires_network", False)),
            "user_invocable": bool(frontmatter.get("user_invocable", True)),
            "species": _normalize_text(frontmatter.get("species", "")),
            "modality": _normalize_text(frontmatter.get("modality", "")),
            "stage": _normalize_text(frontmatter.get("stage", "")),
            "stability": _normalize_text(frontmatter.get("stability", "")),
            "safety_level": _normalize_text(frontmatter.get("safety_level", "")),
        }
    except Exception:
        return None


def collect_skill_entries(base_dir: Path, respect_enabled: bool = True) -> list[dict[str, Any]]:
    """Collect normalized skill metadata from all configured sources."""
    config = _get_config()
    seen_names: set[str] = set()
    skill_entries: list[dict[str, Any]] = []

    for root_dir, skill_md in iter_skill_files(base_dir):
        entry = parse_skill_entry(base_dir, root_dir, skill_md)
        if not entry:
            continue

        name = entry["name"]
        if name in seen_names:
            continue
        if respect_enabled and not config.get_skill_enabled(name):
            continue

        seen_names.add(name)
        skill_entries.append(entry)

    skill_entries.sort(key=lambda e: (e.get("category", ""), e["name"]))
    return skill_entries


def scan_skills(base_dir: Path) -> None:
    """
    Collect SKILL.md from all configured directories, apply enable/disable,
    and write SKILLS_SNAPSHOT.md with extended metadata.
    """
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"
    skill_entries = collect_skill_entries(base_dir, respect_enabled=True)

    lines = ["<available_skills>"]
    for entry in skill_entries:
        lines.append("  <skill>")
        lines.append(f"    <name>{_escape(entry['name'])}</name>")
        lines.append(f"    <description>{_escape(entry['description'])}</description>")
        lines.append(f"    <location>{_escape(entry['location'])}</location>")
        if entry.get("category"):
            lines.append(f"    <category>{_escape(entry['category'])}</category>")
        if entry.get("stage"):
            lines.append(f"    <stage>{_escape(entry['stage'])}</stage>")
        if entry.get("species"):
            lines.append(f"    <species>{_escape(entry['species'])}</species>")
        if entry.get("modality"):
            lines.append(f"    <modality>{_escape(entry['modality'])}</modality>")
        if entry.get("aliases"):
            lines.append(f"    <aliases>{_escape(', '.join(entry['aliases']))}</aliases>")
        if entry.get("tags"):
            lines.append(f"    <tags>{_escape(', '.join(entry['tags']))}</tags>")
        if entry.get("requires_tools"):
            lines.append(
                f"    <requires_tools>{_escape(', '.join(entry['requires_tools']))}</requires_tools>"
            )
        if entry.get("requires_network"):
            lines.append("    <requires_network>true</requires_network>")
        if entry.get("stability"):
            lines.append(f"    <stability>{_escape(entry['stability'])}</stability>")
        if entry.get("safety_level"):
            lines.append(f"    <safety_level>{_escape(entry['safety_level'])}</safety_level>")
        if entry.get("user_invocable") is False:
            lines.append("    <user_invocable>false</user_invocable>")
        lines.append("  </skill>")
    lines.append("</available_skills>")

    snapshot_path.write_text("\n".join(lines), encoding="utf-8")


def _escape(s: str) -> str:
    if not s:
        return ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter between --- delimiters."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
