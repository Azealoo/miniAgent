"""
Scans skill directories, parses YAML frontmatter, and generates
SKILLS_SNAPSHOT.md for the agent's system prompt.

Supports:
- Local skills at backend/skills/ (recursive: skills/**/SKILL.md)
- Extra directories via config skills.extra_dirs
- Project-scoped .agents/skills/ from repo root (if present)
- Per-skill enable/disable via config skills.entries.<name>.enabled
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml

VALID_BIOLOGY_CATEGORIES = frozenset(
    {
        "bio/literature",
        "bio/single_cell_rna",
        "bio/perturb_seq",
        "bio/crispr_screen",
        "bio/multiomics",
        "bio/spatial",
        "bio/molecular_lab",
        "bio/compute",
    }
)
VALID_MODALITIES = frozenset(
    {
        "crispr_screen",
        "multiomics",
        "spatial",
        "single_cell_rna",
        "perturb_seq",
        "wet_lab",
        "literature",
        "compute",
    }
)
VALID_STAGES = frozenset(
    {
        "design",
        "qc",
        "preprocess",
        "analysis",
        "annotation",
        "interpretation",
        "prioritization",
        "validation",
        "reporting",
        "utilities",
    }
)
VALID_STABILITIES = frozenset({"stable", "evolving", "experimental"})
VALID_SAFETY_LEVELS = frozenset({"low", "medium", "high"})
VALID_EFFORT_LEVELS = frozenset({"low", "medium", "high"})
REQUIRED_BIOLOGY_METADATA_FIELDS = (
    "species",
    "modality",
    "stage",
    "stability",
    "safety_level",
)


@dataclass(frozen=True)
class SkillSource:
    kind: str
    root_dir: Path
    precedence: int


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


def _normalize_effort(value: Any) -> str:
    return _normalize_text(value).lower()


def _normalize_path_hints(value: Any) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_path in _normalize_list(value):
        path_hint = raw_path
        while path_hint.startswith("./"):
            path_hint = path_hint[2:]
        if not path_hint or path_hint in seen:
            continue
        seen.add(path_hint)
        normalized.append(path_hint)
    return normalized


def _is_valid_path_hint(path_hint: str) -> bool:
    if not path_hint or path_hint in {".", "./"}:
        return False
    if path_hint.startswith(("/", "~")):
        return False
    if "\\" in path_hint:
        return False
    if len(path_hint) >= 2 and path_hint[0].isalpha() and path_hint[1] == ":":
        return False

    return not any(segment in {".", ".."} for segment in path_hint.split("/"))


def _runtime_tool_names(base_dir: Path) -> set[str]:
    from tools import get_all_tools

    return {tool.name for tool in get_all_tools(base_dir)}


def _validate_skill_entry(entry: dict[str, Any], *, available_tool_names: set[str]) -> None:
    category = entry.get("category", "")
    skill_name = entry.get("name", "<unnamed>")
    effort = entry.get("effort", "")

    invalid_tools = sorted({tool for tool in entry.get("requires_tools", []) if tool not in available_tool_names})
    if invalid_tools:
        raise ValueError(
            f"Skill '{skill_name}' declares unavailable tools: {', '.join(invalid_tools)}"
        )
    if effort and effort not in VALID_EFFORT_LEVELS:
        raise ValueError(
            f"Skill '{skill_name}' has invalid effort '{effort}'; expected one of: "
            f"{', '.join(sorted(VALID_EFFORT_LEVELS))}"
        )

    invalid_paths = sorted(
        path_hint for path_hint in entry.get("paths", []) if not _is_valid_path_hint(path_hint)
    )
    if invalid_paths:
        raise ValueError(
            f"Skill '{skill_name}' has invalid paths metadata: {', '.join(invalid_paths)}"
        )

    if not category.startswith("bio/") or entry.get("user_invocable") is False:
        return

    missing = [
        field
        for field in REQUIRED_BIOLOGY_METADATA_FIELDS
        if not _normalize_text(entry.get(field))
    ]
    if missing:
        raise ValueError(
            f"Biology skill '{skill_name}' is missing required metadata: {', '.join(missing)}"
        )

    modality = entry["modality"]
    stage = entry["stage"]
    stability = entry["stability"]
    safety_level = entry["safety_level"]

    if category not in VALID_BIOLOGY_CATEGORIES:
        raise ValueError(f"Biology skill '{skill_name}' has invalid category '{category}'")
    if modality not in VALID_MODALITIES:
        raise ValueError(f"Biology skill '{skill_name}' has invalid modality '{modality}'")
    if stage not in VALID_STAGES:
        raise ValueError(f"Biology skill '{skill_name}' has invalid stage '{stage}'")
    if stability not in VALID_STABILITIES:
        raise ValueError(f"Biology skill '{skill_name}' has invalid stability '{stability}'")
    if safety_level not in VALID_SAFETY_LEVELS:
        raise ValueError(f"Biology skill '{skill_name}' has invalid safety_level '{safety_level}'")
    if stability == "stable" and not entry.get("requires_tools"):
        raise ValueError(f"Stable biology skill '{skill_name}' must declare at least one runtime tool")


def iter_skill_sources(base_dir: Path) -> list[SkillSource]:
    """Return skill source roots in runtime precedence order."""
    config = _get_config()
    sources: list[SkillSource] = []
    precedence = 0

    skills_dir = base_dir / "skills"
    if skills_dir.exists():
        sources.append(SkillSource(kind="local", root_dir=skills_dir, precedence=precedence))
        precedence += 1

    for extra_dir in config.get_skills_extra_dirs(base_dir):
        if extra_dir.exists():
            sources.append(
                SkillSource(kind="config_extra", root_dir=extra_dir, precedence=precedence)
            )
            precedence += 1

    repo_root = base_dir.parent
    agents_skills = repo_root / ".agents" / "skills"
    if agents_skills.exists():
        sources.append(
            SkillSource(kind="repo_agents", root_dir=agents_skills, precedence=precedence)
        )

    return sources


def iter_skill_files(base_dir: Path) -> list[tuple[SkillSource, Path]]:
    """Return all candidate (source, SKILL.md) pairs in precedence order."""
    candidates: list[tuple[SkillSource, Path]] = []
    for source in iter_skill_sources(base_dir):
        for skill_md in sorted(source.root_dir.rglob("SKILL.md")):
            candidates.append((source, skill_md))
    return candidates


def parse_skill_entry(base_dir: Path, source: SkillSource, skill_md: Path) -> Optional[dict[str, Any]]:
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
            relative_source = skill_md.relative_to(source.root_dir)
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
            "paths": _normalize_path_hints(frontmatter.get("paths")),
            "effort": _normalize_effort(frontmatter.get("effort")),
            "requires_tools": _normalize_list(frontmatter.get("requires_tools")),
            "requires_network": bool(frontmatter.get("requires_network", False)),
            "user_invocable": bool(frontmatter.get("user_invocable", True)),
            "species": _normalize_text(frontmatter.get("species", "")),
            "modality": _normalize_text(frontmatter.get("modality", "")),
            "stage": _normalize_text(frontmatter.get("stage", "")),
            "stability": _normalize_text(frontmatter.get("stability", "")),
            "safety_level": _normalize_text(frontmatter.get("safety_level", "")),
            "source_kind": source.kind,
            "source_root": str(source.root_dir),
            "precedence": source.precedence,
        }
    except Exception:
        return None


def _build_registry_entries(
    base_dir: Path,
    *,
    respect_enabled_for_selection: bool,
) -> list[dict[str, Any]]:
    config = _get_config()
    available_tool_names = _runtime_tool_names(base_dir)
    selected_names: set[str] = set()
    registry_entries: list[dict[str, Any]] = []

    for source, skill_md in iter_skill_files(base_dir):
        entry = parse_skill_entry(base_dir, source, skill_md)
        if not entry:
            continue

        name = entry["name"]
        enabled = config.get_skill_enabled(name)
        entry["enabled"] = enabled
        entry["selected"] = False
        entry["selection_reason"] = ""

        if respect_enabled_for_selection and not enabled:
            entry["selection_reason"] = "disabled_by_config"
        elif name in selected_names:
            entry["selection_reason"] = "shadowed_by_higher_precedence"
        else:
            _validate_skill_entry(entry, available_tool_names=available_tool_names)
            entry["selected"] = True
            entry["selection_reason"] = "selected"
            selected_names.add(name)

        registry_entries.append(entry)

    registry_entries.sort(
        key=lambda entry: (
            entry["name"],
            entry["precedence"],
            entry["source_path"],
        )
    )
    return registry_entries


def describe_skill_registry(base_dir: Path) -> list[dict[str, Any]]:
    """Return the runtime skill registry with source, enablement, and selection metadata."""
    return _build_registry_entries(base_dir, respect_enabled_for_selection=True)


def collect_skill_entries(base_dir: Path, respect_enabled: bool = True) -> list[dict[str, Any]]:
    """Collect normalized skill metadata from all configured sources."""
    skill_entries = [
        entry
        for entry in _build_registry_entries(
            base_dir,
            respect_enabled_for_selection=respect_enabled,
        )
        if entry["selected"]
    ]
    skill_entries.sort(key=lambda e: (e.get("category", ""), e["name"]))
    return skill_entries


def render_skills_snapshot(skill_entries: list[dict[str, Any]]) -> str:
    """Render a prompt-compatible XML snapshot from selected registry entries."""
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
        if entry.get("paths"):
            lines.append(f"    <paths>{_escape(', '.join(entry['paths']))}</paths>")
        if entry.get("effort"):
            lines.append(f"    <effort>{_escape(entry['effort'])}</effort>")
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
    return "\n".join(lines)


def scan_skills(base_dir: Path) -> None:
    """
    Collect SKILL.md from all configured directories, apply enable/disable,
    and write SKILLS_SNAPSHOT.md with extended metadata.
    """
    snapshot_path = base_dir / "SKILLS_SNAPSHOT.md"
    skill_entries = collect_skill_entries(base_dir, respect_enabled=True)
    snapshot_path.write_text(render_skills_snapshot(skill_entries), encoding="utf-8")


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
