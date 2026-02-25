"""
Tests for skills_scanner — scans SKILL.md files and writes SKILLS_SNAPSHOT.md.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.skills_scanner import scan_skills, _parse_frontmatter


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
    def _make_skill(self, base: Path, name: str, description: str) -> None:
        skill_dir = base / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n## Steps\n1. Do stuff",
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

    def test_real_skills_directory(self):
        """Smoke-test against the real skills/ directory."""
        real_base = Path(__file__).parent.parent
        scan_skills(real_base)
        snapshot = real_base / "SKILLS_SNAPSHOT.md"
        assert snapshot.exists()
        content = snapshot.read_text()
        assert "<available_skills>" in content
        assert "get_weather" in content
        assert "count_lines" in content
