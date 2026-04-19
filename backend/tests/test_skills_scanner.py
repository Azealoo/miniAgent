"""
Tests for skills_scanner — scans SKILL.md files and writes SKILLS_SNAPSHOT.md.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import skills_scanner
from tools.skills_scanner import (
    SkillRegistry,
    _parse_frontmatter,
    collect_skill_entries,
    describe_skill_registry,
    get_body,
    get_frontmatter,
    scan_skills,
    skill_required_env_satisfied,
)


P6_SLICE6_STABLE_CANDIDATES = {
    "gene_symbol_normalizer": {"ensembl_api", "uniprot_api", "python_repl"},
    "protocol_from_knowledge": {"search_knowledge_base", "read_file"},
    "paper_triage": {"ncbi_eutils", "evidence_retrieval", "evidence_review", "python_repl"},
    "guide_risk_precheck": {
        "search_knowledge_base",
        "evidence_review",
        "ensembl_api",
        "ncbi_eutils",
        "python_repl",
    },
    "scRNA_qc_checklist": {"search_knowledge_base", "python_repl"},
    "differential_expression_helper": {"read_file", "search_knowledge_base", "python_repl"},
    "marker_gene_validator": {"search_knowledge_base", "ncbi_eutils", "uniprot_api", "python_repl"},
    "literature_consensus_map": {
        "search_knowledge_base",
        "evidence_retrieval",
        "evidence_review",
        "python_repl",
    },
}
P6_STABLE_OUTPUT_LABELS = (
    "**Biological context or assumptions**",
    "**Evidence or source basis**",
    "**Caveats or ambiguity**",
    "**Recommended next step**",
)


def _read_repo_skill(name: str) -> tuple[dict[str, object], str]:
    skill_path = Path(__file__).resolve().parent.parent / "skills" / name / "SKILL.md"
    content = skill_path.read_text(encoding="utf-8")
    frontmatter = _parse_frontmatter(content)
    parts = re.split(r"^---\s*$", content, maxsplit=2, flags=re.MULTILINE)
    body = parts[2] if len(parts) == 3 else content
    return frontmatter, body


# ──────────────────────────────────────────────────────────────────────────────
# _parse_frontmatter
# ──────────────────────────────────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\nname: my_skill\ndescription: Does stuff\n---\n# Body"
        result = _parse_frontmatter(content)
        assert result["name"] == "my_skill"
        assert result["description"] == "Does stuff"

    def test_no_frontmatter_returns_empty(self):
        result = _parse_frontmatter("# Just a heading\nNo frontmatter")
        assert result == {}

    def test_empty_frontmatter_returns_empty(self):
        result = _parse_frontmatter("---\n---\n# body")
        assert result == {}

    def test_invalid_yaml_returns_empty(self):
        result = _parse_frontmatter("---\n: invalid: : yaml\n---")
        assert result == {}

    def test_partial_delimiter_returns_empty(self):
        result = _parse_frontmatter("---\nname: thing")  # no closing ---
        assert result == {}

    def test_extra_fields_preserved(self):
        content = "---\nname: test\ndescription: desc\nversion: 2.1\nauthor: Bob\n---"
        result = _parse_frontmatter(content)
        assert result["version"] == 2.1
        assert result["author"] == "Bob"


# ──────────────────────────────────────────────────────────────────────────────
# scan_skills
# ──────────────────────────────────────────────────────────────────────────────

class TestScanSkills:
    def _make_skill(self, base: Path, name: str, description: str, nested: str = "") -> None:
        skill_dir = base / "skills" / nested / name if nested else base / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            (
                f"---\nname: {name}\ndescription: {description}\ncategory: bio/literature\n"
                "tags: [alpha, beta]\naliases: [alias_one]\n"
                "requires_tools: [read_file]\nrequires_network: false\nuser_invocable: true\n"
                "species: any\nmodality: literature\nstage: analysis\n"
                "stability: experimental\nsafety_level: low\n"
                "---\n## Steps\n1. Do stuff"
            ),
            encoding="utf-8",
        )

    def _write_skill(self, base: Path, name: str, frontmatter: str) -> None:
        skill_dir = base / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\n{frontmatter}\n---\n# Body\n",
            encoding="utf-8",
        )

    def _make_repo_workspace(self, tmp_path: Path) -> Path:
        base = tmp_path / "backend"
        base.mkdir(parents=True, exist_ok=True)
        return base

    def _write_skill_under_root(
        self,
        root: Path,
        name: str,
        *,
        description: str = "Registry test skill",
    ) -> None:
        skill_dir = root / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            (
                f"---\nname: {name}\ndescription: {description}\ncategory: bio/literature\n"
                "requires_tools: [read_file]\nrequires_network: false\nuser_invocable: true\n"
                "species: any\nmodality: literature\nstage: analysis\n"
                "stability: experimental\nsafety_level: low\n"
                "---\n# Body\n"
            ),
            encoding="utf-8",
        )

    def test_scan_creates_snapshot_file(self, tmp_path):
        self._make_skill(tmp_path, "alpha", "Alpha skill")
        scan_skills(tmp_path)
        assert (tmp_path / "SKILLS_SNAPSHOT.md").exists()

    def test_snapshot_contains_skill_name(self, tmp_path):
        self._make_skill(tmp_path, "alpha", "Alpha skill")
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "alpha" in content

    def test_snapshot_contains_description(self, tmp_path):
        self._make_skill(tmp_path, "beta", "Beta does things")
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "Beta does things" in content

    def test_snapshot_contains_location(self, tmp_path):
        self._make_skill(tmp_path, "gamma", "Gamma skill")
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "skills/gamma/SKILL.md" in content

    def test_snapshot_contains_extended_metadata(self, tmp_path):
        self._make_skill(tmp_path, "meta", "Metadata skill")
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "<category>bio/literature</category>" in content
        assert "<stage>analysis</stage>" in content
        assert "<tags>alpha, beta</tags>" in content
        assert "<aliases>alias_one</aliases>" in content

    def test_snapshot_contains_optional_paths_and_effort_hints(self, tmp_path):
        self._write_skill(
            tmp_path,
            "hinted_skill",
            "\n".join(
                [
                    "name: hinted_skill",
                    "description: path-aware skill",
                    "category: bio/compute",
                    "paths:",
                    "  - ./backend/runtime/",
                    "  - memory/project/**",
                    "effort: medium",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: compute",
                    "stage: utilities",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()

        assert "<paths>backend/runtime/, memory/project/**</paths>" in content
        assert "<effort>medium</effort>" in content

    def test_snapshot_is_xml_format(self, tmp_path):
        self._make_skill(tmp_path, "delta", "Delta")
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "<available_skills>" in content
        assert "</available_skills>" in content
        assert "<skill>" in content
        assert "<name>" in content
        assert "<description>" in content
        assert "<location>" in content

    def test_multiple_skills_all_included(self, tmp_path):
        for name, desc in [("s1", "Skill One"), ("s2", "Skill Two"), ("s3", "Skill Three")]:
            self._make_skill(tmp_path, name, desc)
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert content.count("<skill>") == 3

    def test_no_skills_dir_produces_empty_snapshot(self, tmp_path):
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "<available_skills>" in content
        assert "<skill>" not in content

    def test_skill_without_frontmatter_uses_dir_name(self, tmp_path):
        skill_dir = tmp_path / "skills" / "unnamed"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# No frontmatter here", encoding="utf-8")
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "unnamed" in content

    def test_collect_skill_entries_supports_nested_directories(self, tmp_path):
        self._make_skill(tmp_path, "nested_skill", "Nested skill", nested="bio/scRNA")
        entries = collect_skill_entries(tmp_path, respect_enabled=False)
        assert len(entries) == 1
        assert entries[0]["name"] == "nested_skill"
        assert entries[0]["location"].endswith("skills/bio/scRNA/nested_skill/SKILL.md")

    def test_collect_skill_entries_rejects_invalid_biology_category(self, tmp_path):
        self._write_skill(
            tmp_path,
            "invalid_category",
            "\n".join(
                [
                    "name: invalid_category",
                    "description: bad category",
                    "category: bio/scRNA",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: single_cell_rna",
                    "stage: qc",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        with pytest.raises(ValueError, match="invalid category"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_collect_skill_entries_rejects_missing_biology_metadata(self, tmp_path):
        self._write_skill(
            tmp_path,
            "missing_metadata",
            "\n".join(
                [
                    "name: missing_metadata",
                    "description: missing fields",
                    "category: bio/literature",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                ]
            ),
        )

        with pytest.raises(ValueError, match="missing required metadata"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_collect_skill_entries_rejects_unavailable_tool_dependency(self, tmp_path):
        self._write_skill(
            tmp_path,
            "bad_tool",
            "\n".join(
                [
                    "name: bad_tool",
                    "description: stale tool",
                    "category: bio/compute",
                    "requires_tools: [slurm_tool]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: compute",
                    "stage: utilities",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        with pytest.raises(ValueError, match="declares unavailable tools"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_collect_skill_entries_preserve_optional_paths_and_effort(self, tmp_path):
        self._write_skill(
            tmp_path,
            "hinted_skill",
            "\n".join(
                [
                    "name: hinted_skill",
                    "description: path-aware skill",
                    "category: bio/compute",
                    "paths:",
                    "  - ./backend/runtime/",
                    "  - memory/project/**",
                    "effort: high",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: compute",
                    "stage: utilities",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        entries = collect_skill_entries(tmp_path, respect_enabled=False)

        assert entries[0]["paths"] == ["backend/runtime/", "memory/project/**"]
        assert entries[0]["effort"] == "high"

    def test_collect_skill_entries_rejects_invalid_effort(self, tmp_path):
        self._write_skill(
            tmp_path,
            "bad_effort",
            "\n".join(
                [
                    "name: bad_effort",
                    "description: unsupported effort",
                    "category: bio/compute",
                    "effort: maximum",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: compute",
                    "stage: utilities",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        with pytest.raises(ValueError, match="invalid effort"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_collect_skill_entries_rejects_invalid_paths_metadata(self, tmp_path):
        self._write_skill(
            tmp_path,
            "bad_paths",
            "\n".join(
                [
                    "name: bad_paths",
                    "description: unsupported path hints",
                    "category: bio/compute",
                    "paths:",
                    "  - ../outside",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: compute",
                    "stage: utilities",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        with pytest.raises(ValueError, match="invalid paths metadata"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_collect_skill_entries_accepts_supported_growth_domain_modalities(self, tmp_path):
        self._write_skill(
            tmp_path,
            "spatial_skill",
            "\n".join(
                [
                    "name: spatial_skill",
                    "description: spatial analysis helper",
                    "category: bio/spatial",
                    "requires_tools: [read_file]",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: spatial",
                    "stage: analysis",
                    "stability: experimental",
                    "safety_level: low",
                ]
            ),
        )

        entries = collect_skill_entries(tmp_path, respect_enabled=False)

        assert len(entries) == 1
        assert entries[0]["category"] == "bio/spatial"
        assert entries[0]["modality"] == "spatial"

    def test_collect_skill_entries_rejects_stable_skill_without_tools(self, tmp_path):
        self._write_skill(
            tmp_path,
            "stable_without_tools",
            "\n".join(
                [
                    "name: stable_without_tools",
                    "description: falsely stable",
                    "category: bio/literature",
                    "requires_tools: []",
                    "requires_network: false",
                    "user_invocable: true",
                    "species: any",
                    "modality: literature",
                    "stage: interpretation",
                    "stability: stable",
                    "safety_level: low",
                ]
            ),
        )

        with pytest.raises(ValueError, match="must declare at least one runtime tool"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_registry_marks_shadowed_sources_and_precedence(self, tmp_path):
        base = self._make_repo_workspace(tmp_path)
        extra_dir = tmp_path / "extra-skills"
        repo_skills = tmp_path / ".agents" / "skills"

        self._write_skill_under_root(base / "skills", "shared_skill", description="local")
        self._write_skill_under_root(extra_dir, "shared_skill", description="extra")
        self._write_skill_under_root(repo_skills, "repo_only", description="repo")

        cfg_file = tmp_path / "backend-config.json"
        cfg_file.write_text(
            json.dumps({"skills": {"extra_dirs": [str(extra_dir)]}}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            registry = describe_skill_registry(base)

        shared_entries = [entry for entry in registry if entry["name"] == "shared_skill"]
        local_entry = next(entry for entry in shared_entries if entry["source_kind"] == "local")
        extra_entry = next(
            entry for entry in shared_entries if entry["source_kind"] == "config_extra"
        )
        repo_entry = next(entry for entry in registry if entry["name"] == "repo_only")

        assert local_entry["selected"] is True
        assert local_entry["selection_reason"] == "selected"
        assert extra_entry["selected"] is False
        assert extra_entry["selection_reason"] == "shadowed_by_higher_precedence"
        assert local_entry["precedence"] < extra_entry["precedence"]
        assert repo_entry["source_kind"] == "repo_agents"
        assert repo_entry["selected"] is True

    def test_registry_marks_disabled_skills_explicitly(self, tmp_path):
        base = self._make_repo_workspace(tmp_path)
        self._write_skill_under_root(base / "skills", "disabled_skill")

        cfg_file = tmp_path / "backend-config.json"
        cfg_file.write_text(
            json.dumps({"skills": {"entries": {"disabled_skill": {"enabled": False}}}}),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            registry = describe_skill_registry(base)
            active_entries = collect_skill_entries(base, respect_enabled=True)
            unfiltered_entries = collect_skill_entries(base, respect_enabled=False)

        disabled_entry = next(entry for entry in registry if entry["name"] == "disabled_skill")
        assert disabled_entry["enabled"] is False
        assert disabled_entry["selected"] is False
        assert disabled_entry["selection_reason"] == "disabled_by_config"
        assert not active_entries
        assert [entry["name"] for entry in unfiltered_entries] == ["disabled_skill"]

    def test_real_skills_directory(self):
        """Smoke-test against the real skills/ directory."""
        real_base = Path(__file__).parent.parent
        scan_skills(real_base)
        entries = collect_skill_entries(real_base, respect_enabled=False)
        snapshot = real_base / "SKILLS_SNAPSHOT.md"
        assert snapshot.exists()
        content = snapshot.read_text()
        assert "<available_skills>" in content
        assert "get_weather" in content
        assert "count_lines" in content
        assert not any(
            entry["category"] in {"bio/scRNA", "bio/perturbation", "bio/calculations", "bio/hpc"}
            for entry in entries
        )

    def test_p6_slice6_candidates_are_stable_in_repo_registry(self):
        real_base = Path(__file__).parent.parent
        entries = {entry["name"]: entry for entry in collect_skill_entries(real_base, respect_enabled=False)}

        for name, expected_tools in P6_SLICE6_STABLE_CANDIDATES.items():
            assert name in entries
            entry = entries[name]
            assert entry["stability"] == "stable"
            assert expected_tools.issubset(set(entry["requires_tools"]))

    def test_p6_slice6_candidates_keep_named_tool_backing_and_output_contract(self):
        for name, expected_tools in P6_SLICE6_STABLE_CANDIDATES.items():
            frontmatter, body = _read_repo_skill(name)

            assert frontmatter["stability"] == "stable"
            assert "## Steps" in body
            assert "## Output format" in body
            assert "## Failure modes" in body
            for label in P6_STABLE_OUTPUT_LABELS:
                assert label in body
            for tool_name in expected_tools:
                assert f"`{tool_name}`" in body


# ──────────────────────────────────────────────────────────────────────────────
# Extended skill contract: tools_allowed, exposure, required_env, posture/risk
# ──────────────────────────────────────────────────────────────────────────────


def _write_extended_skill(base: Path, name: str, extra_lines: list[str]) -> None:
    skill_dir = base / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"name: {name}",
        "description: extended contract skill",
        "category: bio/compute",
        "requires_tools: [read_file]",
        "requires_network: false",
        "user_invocable: true",
        "species: any",
        "modality: compute",
        "stage: utilities",
        "stability: experimental",
        "safety_level: low",
        *extra_lines,
    ]
    (skill_dir / "SKILL.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n# Body\n",
        encoding="utf-8",
    )


class TestExtendedSkillContract:
    def test_parses_tools_allowed_and_exposure_defaults(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "extended_defaults",
            ["tools_allowed: [read_file, search_knowledge_base]"],
        )
        entries = collect_skill_entries(tmp_path, respect_enabled=False)
        entry = entries[0]
        assert entry["tools_allowed"] == ["read_file", "search_knowledge_base"]
        assert entry["planner_visible"] is True
        assert entry["verifier_visible"] is True
        assert entry["required_env"] == []
        assert entry["min_posture"] == ""
        assert entry["risk_tier"] == ""

    def test_parses_exposure_flags_when_explicit(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "exposure_off",
            [
                "planner_visible: false",
                "verifier_visible: false",
                "risk_tier: medium",
                "min_posture: execution",
            ],
        )
        entry = collect_skill_entries(tmp_path, respect_enabled=False)[0]
        assert entry["planner_visible"] is False
        assert entry["verifier_visible"] is False
        assert entry["risk_tier"] == "medium"
        assert entry["min_posture"] == "execution"

    def test_snapshot_surfaces_tools_allowed_and_exposure(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "snapshot_skill",
            [
                "tools_allowed: [read_file]",
                "planner_visible: false",
                "verifier_visible: false",
                "required_env: [BIOAPEX_DEMO_TOKEN]",
                "min_posture: inspection",
                "risk_tier: low",
            ],
        )
        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "<tools_allowed>read_file</tools_allowed>" in content
        assert "<planner_visible>false</planner_visible>" in content
        assert "<verifier_visible>false</verifier_visible>" in content
        assert "<required_env>BIOAPEX_DEMO_TOKEN</required_env>" in content
        assert "<min_posture>inspection</min_posture>" in content
        assert "<risk_tier>low</risk_tier>" in content

    def test_rejects_tools_allowed_referencing_unavailable_tool(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "bad_allowlist",
            ["tools_allowed: [does_not_exist_tool]"],
        )
        with pytest.raises(
            ValueError, match="tools_allowed references unavailable tools"
        ):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_rejects_invalid_min_posture(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "bad_posture",
            ["min_posture: ultra_admin"],
        )
        with pytest.raises(ValueError, match="invalid min_posture"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_rejects_invalid_risk_tier(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "bad_risk",
            ["risk_tier: catastrophic"],
        )
        with pytest.raises(ValueError, match="invalid risk_tier"):
            collect_skill_entries(tmp_path, respect_enabled=False)

    def test_required_env_satisfied_checks_environment(self, tmp_path):
        entry = {"required_env": ["BIOAPEX_DEMO_TOKEN"]}
        assert skill_required_env_satisfied(entry, env={}) is False
        assert (
            skill_required_env_satisfied(entry, env={"BIOAPEX_DEMO_TOKEN": ""})
            is False
        )
        assert (
            skill_required_env_satisfied(entry, env={"BIOAPEX_DEMO_TOKEN": "1"})
            is True
        )
        assert skill_required_env_satisfied({"required_env": []}) is True
        assert skill_required_env_satisfied({}) is True

    def test_required_env_normalizes_name_only_entries(self, tmp_path):
        _write_extended_skill(
            tmp_path,
            "env_only_names",
            ["required_env: [FOO_TOKEN, 'BAR_TOKEN=should_be_dropped']"],
        )
        entry = collect_skill_entries(tmp_path, respect_enabled=False)[0]
        assert entry["required_env"] == ["FOO_TOKEN", "BAR_TOKEN"]


# ──────────────────────────────────────────────────────────────────────────────
# SkillRegistry — two-phase frontmatter / body access
# ──────────────────────────────────────────────────────────────────────────────


_BODY_MARKER = "UNIQUE_BODY_MARKER_8f3a1c"


def _write_skill_with_body(
    base: Path, name: str, *, body: str, description: str = "Two-phase skill"
) -> Path:
    skill_dir = base / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        (
            f"---\nname: {name}\ndescription: {description}\ncategory: bio/literature\n"
            "requires_tools: [read_file]\nrequires_network: false\nuser_invocable: true\n"
            "species: any\nmodality: literature\nstage: analysis\n"
            "stability: experimental\nsafety_level: low\n"
            f"---\n{body}"
        ),
        encoding="utf-8",
    )
    return skill_path


class TestSkillRegistryTwoPhase:
    def test_snapshot_contains_frontmatter_only_no_body_text(self, tmp_path):
        _write_skill_with_body(
            tmp_path,
            "two_phase_skill",
            body=f"# Steps\n{_BODY_MARKER}\nLots of private body instructions.\n",
        )

        scan_skills(tmp_path)
        content = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()

        assert "two_phase_skill" in content  # frontmatter name is present
        assert _BODY_MARKER not in content
        assert "private body instructions" not in content
        assert "# Steps" not in content

    def test_get_body_loads_post_frontmatter_content_on_demand(self, tmp_path):
        body_text = f"# Steps\n{_BODY_MARKER}\n1. Do the thing.\n"
        skill_path = _write_skill_with_body(
            tmp_path, "on_demand_skill", body=body_text
        )

        registry = SkillRegistry(tmp_path, respect_enabled=False)

        frontmatter = registry.get_frontmatter("on_demand_skill")
        assert frontmatter is not None
        assert frontmatter["name"] == "on_demand_skill"
        assert _BODY_MARKER not in repr(frontmatter)

        loaded_body = registry.get_body("on_demand_skill")
        assert loaded_body is not None
        assert loaded_body.startswith("# Steps")
        assert _BODY_MARKER in loaded_body
        # Closing frontmatter delimiter must not leak into the body.
        assert not loaded_body.lstrip().startswith("---")
        assert "category: bio/literature" not in loaded_body

        # Body must match what's on disk after the frontmatter block.
        raw = skill_path.read_text(encoding="utf-8")
        assert loaded_body == raw.split("---", 2)[2].lstrip("\n")

    def test_get_body_returns_none_for_unknown_skill(self, tmp_path):
        _write_skill_with_body(tmp_path, "known_skill", body="# hi\n")
        registry = SkillRegistry(tmp_path, respect_enabled=False)
        assert registry.get_body("does_not_exist") is None
        assert registry.get_frontmatter("does_not_exist") is None

    def test_get_body_is_lazy_then_cached(self, tmp_path):
        skill_path = _write_skill_with_body(
            tmp_path, "lazy_skill", body=f"original\n{_BODY_MARKER}\n"
        )
        registry = SkillRegistry(tmp_path, respect_enabled=False)

        # Constructing the registry and inspecting frontmatter must not
        # pre-load the body — the first get_body() call picks up the
        # current on-disk body.
        assert registry.get_frontmatter("lazy_skill") is not None

        header = skill_path.read_text(encoding="utf-8").split("---", 2)
        skill_path.write_text(
            f"---{header[1]}---\nupdated\n{_BODY_MARKER}\n", encoding="utf-8"
        )

        first_body = registry.get_body("lazy_skill")
        assert first_body is not None
        assert first_body.startswith("updated")

        # After the first read the body is cached; later on-disk edits are
        # intentionally not re-read.
        skill_path.write_text(
            skill_path.read_text(encoding="utf-8").replace("updated", "changed_again"),
            encoding="utf-8",
        )
        assert registry.get_body("lazy_skill") == first_body

    def test_module_level_helpers_expose_same_two_phase_api(self, tmp_path):
        _write_skill_with_body(
            tmp_path,
            "helper_skill",
            body=f"body-line\n{_BODY_MARKER}\n",
        )
        frontmatter = get_frontmatter(tmp_path, "helper_skill", respect_enabled=False)
        body = get_body(tmp_path, "helper_skill", respect_enabled=False)

        assert frontmatter is not None
        assert frontmatter["name"] == "helper_skill"
        assert body is not None
        assert _BODY_MARKER in body
        assert "helper_skill" not in body  # name lived in frontmatter only


# ──────────────────────────────────────────────────────────────────────────────
# Registry cache — issue #128
# ──────────────────────────────────────────────────────────────────────────────


def _write_cache_skill(base: Path, name: str) -> Path:
    skill_dir = base / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        (
            f"---\nname: {name}\ndescription: cache test skill {name}\n"
            "category: bio/literature\n"
            "requires_tools: [read_file]\nrequires_network: false\nuser_invocable: true\n"
            "species: any\nmodality: literature\nstage: analysis\n"
            "stability: experimental\nsafety_level: low\n"
            "---\n# Body\n"
        ),
        encoding="utf-8",
    )
    return skill_path


class TestRegistryCache:
    def setup_method(self):
        skills_scanner._clear_registry_cache()

    def teardown_method(self):
        skills_scanner._clear_registry_cache()

    def test_repeated_calls_within_ttl_skip_parsing(self, tmp_path):
        _write_cache_skill(tmp_path, "cache_alpha")
        _write_cache_skill(tmp_path, "cache_beta")

        with patch(
            "tools.skills_scanner.parse_skill_entry",
            wraps=skills_scanner.parse_skill_entry,
        ) as parse_mock:
            first = collect_skill_entries(tmp_path, respect_enabled=False)
            cold_parses = parse_mock.call_count
            second = collect_skill_entries(tmp_path, respect_enabled=False)
            warm_parses = parse_mock.call_count

        assert cold_parses == 2
        assert warm_parses == cold_parses  # no re-parsing on cache hit
        assert first == second

    def test_touching_skill_file_invalidates_cache(self, tmp_path):
        skill_path = _write_cache_skill(tmp_path, "invalidated_skill")

        with patch(
            "tools.skills_scanner.parse_skill_entry",
            wraps=skills_scanner.parse_skill_entry,
        ) as parse_mock:
            collect_skill_entries(tmp_path, respect_enabled=False)
            first_parses = parse_mock.call_count

            # Bump mtime to simulate an edit (use +1s so even coarse-grained
            # filesystems register a change).
            stat_result = skill_path.stat()
            os.utime(
                skill_path,
                (stat_result.st_atime, stat_result.st_mtime + 1),
            )

            collect_skill_entries(tmp_path, respect_enabled=False)
            second_parses = parse_mock.call_count

        assert second_parses > first_parses

    def test_ttl_expiry_invalidates_cache(self, tmp_path, monkeypatch):
        _write_cache_skill(tmp_path, "ttl_skill")
        monkeypatch.setattr(skills_scanner, "_CACHE_TTL_SECONDS", 0.01)

        with patch(
            "tools.skills_scanner.parse_skill_entry",
            wraps=skills_scanner.parse_skill_entry,
        ) as parse_mock:
            collect_skill_entries(tmp_path, respect_enabled=False)
            first_parses = parse_mock.call_count

            time.sleep(0.05)

            collect_skill_entries(tmp_path, respect_enabled=False)
            second_parses = parse_mock.call_count

        assert second_parses > first_parses

    def test_respect_enabled_uses_separate_cache_slots(self, tmp_path):
        _write_cache_skill(tmp_path, "flagged_skill")
        cfg_file = tmp_path / "backend-config.json"
        cfg_file.write_text(
            json.dumps(
                {"skills": {"entries": {"flagged_skill": {"enabled": False}}}}
            ),
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            active_first = collect_skill_entries(tmp_path, respect_enabled=True)
            unfiltered_first = collect_skill_entries(tmp_path, respect_enabled=False)
            active_cached = collect_skill_entries(tmp_path, respect_enabled=True)
            unfiltered_cached = collect_skill_entries(tmp_path, respect_enabled=False)

        assert active_first == []
        assert [entry["name"] for entry in unfiltered_first] == ["flagged_skill"]
        # Both slots must remain consistent across repeated cached reads.
        assert active_first == active_cached
        assert unfiltered_first == unfiltered_cached

    def test_scan_skills_write_busts_cache_via_mtime(self, tmp_path):
        skill_path = _write_cache_skill(tmp_path, "snapshot_skill")

        scan_skills(tmp_path)
        first_snapshot = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "<name>snapshot_skill</name>" in first_snapshot

        # Simulate a SKILL.md edit that renames the skill; scan_skills should
        # pick it up because the mtime changes the cache fingerprint.
        skill_path.write_text(
            skill_path.read_text(encoding="utf-8").replace(
                "name: snapshot_skill", "name: renamed_skill"
            ),
            encoding="utf-8",
        )
        stat_result = skill_path.stat()
        os.utime(skill_path, (stat_result.st_atime, stat_result.st_mtime + 1))

        scan_skills(tmp_path)
        second_snapshot = (tmp_path / "SKILLS_SNAPSHOT.md").read_text()
        assert "<name>renamed_skill</name>" in second_snapshot
        assert "<name>snapshot_skill</name>" not in second_snapshot

    def test_cached_calls_are_substantially_faster(self, tmp_path):
        for index in range(20):
            _write_cache_skill(tmp_path, f"bench_skill_{index:02d}")

        skills_scanner._clear_registry_cache()
        cold_start = time.perf_counter()
        collect_skill_entries(tmp_path, respect_enabled=False)
        cold_elapsed = time.perf_counter() - cold_start

        warm_runs = 20
        warm_start = time.perf_counter()
        for _ in range(warm_runs):
            collect_skill_entries(tmp_path, respect_enabled=False)
        warm_elapsed = (time.perf_counter() - warm_start) / warm_runs

        assert warm_elapsed * 3 < cold_elapsed, (
            f"Registry cache did not speed up collection: "
            f"cold={cold_elapsed:.4f}s, warm_avg={warm_elapsed:.4f}s"
        )
