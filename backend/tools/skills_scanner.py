"""
Scans skill directories, parses YAML frontmatter, and generates
SKILLS_SNAPSHOT.md for the agent's system prompt.

Supports:
- Local skills at backend/skills/ (recursive: skills/**/SKILL.md)
- Extra directories via config skills.extra_dirs
- Project-scoped .agents/skills/ from repo root (if present)
- Per-skill enable/disable via config skills.entries.<name>.enabled
"""
import os
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
VALID_POSTURES = frozenset({"inspection", "execution", "admin"})
VALID_RISK_TIERS = frozenset({"low", "medium", "high"})
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


def _normalize_optional_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0"}:
            return False
    return bool(value)


def _normalize_env_names(value: Any) -> list[str]:
    """Normalize required_env to a list of env-var names only (no values)."""
    names: list[str] = []
    for item in _normalize_list(value):
        name = item.split("=", 1)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


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
    invalid_tools_allowed = sorted(
        {tool for tool in entry.get("tools_allowed", []) if tool not in available_tool_names}
    )
    if invalid_tools_allowed:
        raise ValueError(
            f"Skill '{skill_name}' tools_allowed references unavailable tools: "
            f"{', '.join(invalid_tools_allowed)}"
        )
    min_posture = entry.get("min_posture", "")
    if min_posture and min_posture not in VALID_POSTURES:
        raise ValueError(
            f"Skill '{skill_name}' has invalid min_posture '{min_posture}'; expected one of: "
            f"{', '.join(sorted(VALID_POSTURES))}"
        )
    risk_tier = entry.get("risk_tier", "")
    if risk_tier and risk_tier not in VALID_RISK_TIERS:
        raise ValueError(
            f"Skill '{skill_name}' has invalid risk_tier '{risk_tier}'; expected one of: "
            f"{', '.join(sorted(VALID_RISK_TIERS))}"
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
            "tools_allowed": _normalize_list(frontmatter.get("tools_allowed")),
            "planner_visible": _normalize_optional_bool(
                frontmatter.get("planner_visible"), default=True
            ),
            "verifier_visible": _normalize_optional_bool(
                frontmatter.get("verifier_visible"), default=True
            ),
            "required_env": _normalize_env_names(frontmatter.get("required_env")),
            "min_posture": _normalize_text(frontmatter.get("min_posture", "")).lower(),
            "risk_tier": _normalize_text(frontmatter.get("risk_tier", "")).lower(),
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
        if entry.get("tools_allowed"):
            lines.append(
                f"    <tools_allowed>{_escape(', '.join(entry['tools_allowed']))}</tools_allowed>"
            )
        if entry.get("min_posture"):
            lines.append(f"    <min_posture>{_escape(entry['min_posture'])}</min_posture>")
        if entry.get("risk_tier"):
            lines.append(f"    <risk_tier>{_escape(entry['risk_tier'])}</risk_tier>")
        if entry.get("required_env"):
            lines.append(
                f"    <required_env>{_escape(', '.join(entry['required_env']))}</required_env>"
            )
        if entry.get("planner_visible") is False:
            lines.append("    <planner_visible>false</planner_visible>")
        if entry.get("verifier_visible") is False:
            lines.append("    <verifier_visible>false</verifier_visible>")
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


def _extract_skill_body(content: str) -> str:
    """Return the post-frontmatter body of a SKILL.md document.

    If no frontmatter delimiters are present, the entire content is treated as
    body. Leading whitespace after the closing ``---`` is stripped so callers
    get the usable body directly.
    """
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return content
    return parts[2].lstrip("\n")


class SkillRegistry:
    """Two-phase accessor for SKILL.md metadata and bodies.

    Frontmatter for every discovered skill is parsed eagerly on first access
    (cached keyed by skill name), while the post-frontmatter body is read from
    disk only when ``get_body(name)`` is called. This keeps the default prompt
    frontmatter-only and defers body loads to the moment the model or a user
    slash command actually needs the full instructions.
    """

    def __init__(self, base_dir: Path, *, respect_enabled: bool = True) -> None:
        self.base_dir = base_dir
        self._respect_enabled = respect_enabled
        self._frontmatter: dict[str, dict[str, Any]] | None = None
        self._paths: dict[str, Path] = {}
        self._body_cache: dict[str, str] = {}

    def _ensure_loaded(self) -> None:
        if self._frontmatter is not None:
            return
        frontmatter: dict[str, dict[str, Any]] = {}
        paths: dict[str, Path] = {}
        for entry in collect_skill_entries(
            self.base_dir, respect_enabled=self._respect_enabled
        ):
            name = entry["name"]
            if name in frontmatter:
                continue
            frontmatter[name] = entry
            paths[name] = _resolve_skill_path(self.base_dir, entry)
        self._frontmatter = frontmatter
        self._paths = paths

    def names(self) -> list[str]:
        self._ensure_loaded()
        assert self._frontmatter is not None
        return list(self._frontmatter.keys())

    def get_frontmatter(self, name: str) -> dict[str, Any] | None:
        """Return cached frontmatter metadata for ``name`` or None if unknown."""
        self._ensure_loaded()
        assert self._frontmatter is not None
        return self._frontmatter.get(name)

    def get_body(self, name: str) -> str | None:
        """Return the post-frontmatter body of ``name``'s SKILL.md on demand.

        The body is read from disk the first time it is requested and cached
        for subsequent calls; frontmatter-only consumers never pay this cost.
        Returns None when the skill is unknown or its source file is missing.
        """
        if name in self._body_cache:
            return self._body_cache[name]
        self._ensure_loaded()
        path = self._paths.get(name)
        if path is None or not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        body = _extract_skill_body(content)
        self._body_cache[name] = body
        return body


def _resolve_skill_path(base_dir: Path, entry: dict[str, Any]) -> Path:
    location = entry.get("location", "")
    if isinstance(location, str) and location.startswith("./"):
        return base_dir / location[2:]
    if isinstance(location, str) and location:
        candidate = Path(location)
        if candidate.is_absolute():
            return candidate
        return base_dir / candidate
    return base_dir / "skills" / entry.get("name", "") / "SKILL.md"


def get_frontmatter(
    base_dir: Path, name: str, *, respect_enabled: bool = True
) -> dict[str, Any] | None:
    """Module-level helper returning cached frontmatter for ``name``."""
    return SkillRegistry(base_dir, respect_enabled=respect_enabled).get_frontmatter(name)


def get_body(
    base_dir: Path, name: str, *, respect_enabled: bool = True
) -> str | None:
    """Module-level helper returning the on-demand body for ``name``."""
    return SkillRegistry(base_dir, respect_enabled=respect_enabled).get_body(name)


def skill_required_env_satisfied(
    entry: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    """Return True when every env var in entry['required_env'] is set and non-empty."""
    required = entry.get("required_env") or []
    if not required:
        return True
    source = env if env is not None else os.environ
    return all(bool(source.get(name)) for name in required)


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
