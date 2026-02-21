"""
Scans the skills/ directory for SKILL.md files, parses their YAML frontmatter,
and generates SKILLS_SNAPSHOT.md in XML format for the agent's system prompt.
"""
from pathlib import Path

import yaml


def scan_skills(base_dir: Path) -> None:
    """
    Walk skills/<name>/SKILL.md, extract name + description from YAML frontmatter,
    and write SKILLS_SNAPSHOT.md.
    """
    skills_dir = base_dir / "skills"
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"

    skill_entries: list[dict] = []

    if skills_dir.exists():
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            try:
                content = skill_md.read_text(encoding="utf-8")
                frontmatter = _parse_frontmatter(content)
                name = frontmatter.get("name", skill_md.parent.name)
                description = frontmatter.get("description", "")
                # Use a path relative to base_dir for portability
                relative_location = str(skill_md.relative_to(base_dir))
                skill_entries.append(
                    {
                        "name": name,
                        "description": description,
                        "location": f"./{relative_location}",
                    }
                )
            except Exception:
                continue

    # Build XML block
    lines = ["<available_skills>"]
    for entry in skill_entries:
        lines.append("  <skill>")
        lines.append(f"    <name>{entry['name']}</name>")
        lines.append(f"    <description>{entry['description']}</description>")
        lines.append(f"    <location>{entry['location']}</location>")
        lines.append("  </skill>")
    lines.append("</available_skills>")

    xml_block = "\n".join(lines)
    snapshot_path.write_text(xml_block, encoding="utf-8")


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
