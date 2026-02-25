"""
Scans skills directories for SKILL.md files, parses YAML frontmatter,
and generates SKILLS_SNAPSHOT.md in XML format for the agent's system prompt.

Supports:
- Local skills at backend/skills/ (recursive: skills/**/SKILL.md)
- Extra directories via config skills.extra_dirs
- Project-scoped .agents/skills/ from repo root (if present)
- Per-skill enable/disable via config skills.entries.<name>.enabled
"""
from pathlib import Path

import yaml

# Import after path is set
def _get_config():
    import config as cfg
    return cfg


def scan_skills(base_dir: Path) -> None:
    """
    Collect SKILL.md from all configured directories, apply enable/disable,
    and write SKILLS_SNAPSHOT.md with extended metadata.
    """
    config = _get_config()
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"

    # Collect all candidate skill paths (dir, path) for dedup by canonical name
    candidates: list[tuple[Path, Path]] = []

    # 1. Local skills (recursive: skills/**/SKILL.md)
    skills_dir = base_dir / "skills"
    if skills_dir.exists():
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            candidates.append((skills_dir, skill_md))

    # 2. Extra directories from config
    for extra_dir in config.get_skills_extra_dirs(base_dir):
        if extra_dir.exists():
            for skill_md in sorted(extra_dir.rglob("SKILL.md")):
                candidates.append((extra_dir, skill_md))

    # 3. Project-scoped .agents/skills (repo root = parent of backend)
    repo_root = base_dir.parent
    agents_skills = repo_root / ".agents" / "skills"
    if agents_skills.exists():
        for skill_md in sorted(agents_skills.rglob("SKILL.md")):
            candidates.append((agents_skills, skill_md))

    skill_entries: list[dict] = []
    seen_names: set[str] = set()

    for _root, skill_md in candidates:
        try:
            content = skill_md.read_text(encoding="utf-8")
            frontmatter = _parse_frontmatter(content)
            name = frontmatter.get("name", skill_md.parent.name)
            if name in seen_names:
                continue
            if not config.get_skill_enabled(name):
                continue
            seen_names.add(name)

            description = frontmatter.get("description", "")
            category = frontmatter.get("category", "")
            requires_tools = frontmatter.get("requires_tools", [])
            if isinstance(requires_tools, str):
                requires_tools = [requires_tools] if requires_tools else []
            requires_network = frontmatter.get("requires_network", False)
            user_invocable = frontmatter.get("user_invocable", True)

            try:
                relative_location = skill_md.relative_to(base_dir)
                location = f"./{relative_location}"
            except ValueError:
                location = str(skill_md)

            skill_entries.append({
                "name": name,
                "description": description,
                "location": location,
                "category": category,
                "requires_tools": requires_tools,
                "requires_network": requires_network,
                "user_invocable": user_invocable,
            })
        except Exception:
            continue

    # Sort by category then name for stable snapshot
    skill_entries.sort(key=lambda e: (e.get("category", ""), e["name"]))

    lines = ["<available_skills>"]
    for entry in skill_entries:
        lines.append("  <skill>")
        lines.append(f"    <name>{_escape(entry['name'])}</name>")
        lines.append(f"    <description>{_escape(entry['description'])}</description>")
        lines.append(f"    <location>{_escape(entry['location'])}</location>")
        if entry.get("category"):
            lines.append(f"    <category>{_escape(entry['category'])}</category>")
        if entry.get("requires_tools"):
            lines.append(f"    <requires_tools>{', '.join(entry['requires_tools'])}</requires_tools>")
        if entry.get("requires_network"):
            lines.append("    <requires_network>true</requires_network>")
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
