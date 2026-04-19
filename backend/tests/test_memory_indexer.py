"""
Tests for MemoryIndexer.
Index build/retrieve tests that need OpenAI embeddings are skipped unless
the OPENAI_API_KEY env var is set. All other logic (path discovery, hashing,
and empty-state handling) runs without any API calls.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_indexer import MemoryIndexer
from graph.memory_types import (
    TYPED_MEMORY_KIND_VALUES,
    TYPED_MEMORY_SCOPE_VALUES,
    TYPED_MEMORY_TYPE_VALUES,
    infer_kind_from_source,
    parse_memory_document,
    validate_memory_write,
)

NEEDS_OPENAI = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set - skipping embedding tests",
)


@pytest.fixture
def indexer(tmp_path):
    (tmp_path / "memory").mkdir()
    (tmp_path / "storage").mkdir()
    return MemoryIndexer(base_dir=tmp_path)


def _write_memory_file(base_dir: Path, relative_path: str, content: str) -> Path:
    target = base_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


class TestInitialState:
    def test_index_starts_as_none(self, indexer):
        assert indexer._index is None

    def test_nodes_start_empty(self, indexer):
        assert indexer._nodes == []

    def test_last_md5_starts_empty(self, indexer):
        assert indexer._last_md5 == ""

    def test_storage_path_under_storage_dir(self, tmp_path):
        idx = MemoryIndexer(base_dir=tmp_path)
        assert idx._storage_path == tmp_path / "storage" / "memory_index"


class TestMemoryFileDiscovery:
    def test_memory_files_include_nested_markdown_and_text(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(tmp_path, "memory/project/notes.md", "# Project\n")
        _write_memory_file(tmp_path, "memory/user/profile.txt", "Prefers concise notes.\n")

        files = [path.relative_to(tmp_path).as_posix() for path in indexer._memory_files()]

        assert files == [
            "memory/MEMORY.md",
            "memory/project/notes.md",
            "memory/user/profile.txt",
        ]

    def test_memory_files_skip_hidden_and_non_text_files(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(tmp_path, "memory/test-note.md", "Temporary root note.\n")
        _write_memory_file(tmp_path, "memory/project/.gitkeep", "")
        binary_file = tmp_path / "memory" / "user" / "plot.png"
        binary_file.parent.mkdir(parents=True, exist_ok=True)
        binary_file.write_bytes(b"png")

        files = [path.relative_to(tmp_path).as_posix() for path in indexer._memory_files()]

        assert files == ["memory/MEMORY.md"]

    def test_memory_documents_use_relative_source_paths(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/runbook.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: Artifact runbook\n"
                "description: Keeps the artifact storage rule in one scoped note.\n"
                "---\n"
                "Keep outputs under artifacts/.\n"
            ),
        )
        _write_memory_file(tmp_path, "memory/user/empty.md", "")

        assert indexer._memory_documents() == [
            ("memory/MEMORY.md", "# Index"),
            ("memory/project/runbook.md", "Keep outputs under artifacts/."),
        ]

    def test_memory_sections_use_heading_anchors_for_markdown(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/project/runbook.md",
            "# Overview\nUse the miniAgent env.\n\n## QC Checklist\nRun Scanpy QC first.\n",
        )

        assert [(section.source, section.text) for section in indexer._memory_sections()] == [
            ("memory/project/runbook.md#overview", "# Overview\nUse the miniAgent env."),
            (
                "memory/project/runbook.md#qc-checklist",
                "## QC Checklist\nRun Scanpy QC first.",
            ),
        ]

    def test_parsed_memory_documents_capture_typed_frontmatter(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/user/preferences.md",
            (
                "---\n"
                "type: user preference\n"
                "name: Working style\n"
                "description: Stable collaboration preferences for the user.\n"
                "---\n"
                "# Style\nPrefer concise plans.\n"
            ),
        )

        documents = indexer._parsed_memory_documents()

        assert len(documents) == 1
        assert documents[0].metadata is not None
        assert documents[0].metadata.memory_type == "user_preference"
        assert documents[0].metadata.name == "Working style"
        assert documents[0].body == "# Style\nPrefer concise plans."


class TestTypedMemoryContract:
    def test_parse_memory_document_keeps_body_readable_when_type_is_invalid(self):
        parsed = parse_memory_document(
            "memory/project/note.md",
            (
                "---\n"
                "type: unsupported type\n"
                "name: Broken note\n"
                "description: Invalid type should be rejected.\n"
                "---\n"
                "# Body\nStill readable.\n"
            ),
        )

        assert parsed.metadata is None
        assert parsed.errors == (
            "Typed memory frontmatter type must be one of: "
            + ", ".join(TYPED_MEMORY_TYPE_VALUES)
            + ".",
        )
        assert parsed.body == "# Body\nStill readable."

    def test_validate_memory_write_ignores_legacy_memory_files(self):
        assert validate_memory_write("memory/project/legacy.md", "# Legacy note\n") == ()

    def test_validate_memory_write_requires_required_fields_when_frontmatter_is_present(self):
        errors = validate_memory_write(
            "memory/project/incomplete.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: \n"
                "---\n"
                "# Body\nIncomplete note.\n"
            ),
        )

        assert errors == (
            "Typed memory frontmatter requires non-empty fields: name, description.",
        )


class TestTypedMemorySchemaExtensions:
    """Schema coverage for kind / scope / tags / pinned / updated_at."""

    def _base_frontmatter(self, **extra: str) -> str:
        fields = {
            "type": "project_fact",
            "name": "Artifact runbook",
            "description": "Keeps the artifact storage rule in one scoped note.",
        }
        fields.update(extra)
        lines = ["---"]
        for key, value in fields.items():
            lines.append(f"{key}: {value}")
        lines.extend(["---", "Keep outputs under artifacts/."])
        return "\n".join(lines) + "\n"

    def test_kind_inferred_from_project_directory(self):
        parsed = parse_memory_document(
            "memory/project/runbook.md", self._base_frontmatter()
        )
        assert parsed.metadata is not None
        assert parsed.metadata.kind == "project"
        # Scope defaults track kind.
        assert parsed.metadata.scope == "project"

    def test_kind_inferred_from_user_directory_defaults_scope_user(self):
        parsed = parse_memory_document(
            "memory/user/preferences.md",
            self._base_frontmatter(type="user_preference"),
        )
        assert parsed.metadata is not None
        assert parsed.metadata.kind == "user"
        assert parsed.metadata.scope == "user"

    def test_kind_inferred_from_agent_directory_defaults_scope_global(self):
        parsed = parse_memory_document(
            "memory/agent/policy.md",
            self._base_frontmatter(type="workflow_heuristic"),
        )
        assert parsed.metadata is not None
        assert parsed.metadata.kind == "agent"
        assert parsed.metadata.scope == "global"

    def test_explicit_scope_overrides_default(self):
        parsed = parse_memory_document(
            "memory/project/note.md", self._base_frontmatter(scope="session")
        )
        assert parsed.metadata is not None
        assert parsed.metadata.scope == "session"

    def test_explicit_kind_overrides_inferred_path(self):
        parsed = parse_memory_document(
            "memory/project/note.md", self._base_frontmatter(kind="user")
        )
        assert parsed.metadata is not None
        assert parsed.metadata.kind == "user"

    def test_invalid_kind_produces_validation_error(self):
        errors = validate_memory_write(
            "memory/project/note.md", self._base_frontmatter(kind="weird")
        )
        assert errors == (
            "Typed memory frontmatter `kind` must be one of: "
            + ", ".join(TYPED_MEMORY_KIND_VALUES)
            + ".",
        )

    def test_invalid_scope_produces_validation_error(self):
        errors = validate_memory_write(
            "memory/project/note.md", self._base_frontmatter(scope="forever")
        )
        assert errors == (
            "Typed memory frontmatter `scope` must be one of: "
            + ", ".join(TYPED_MEMORY_SCOPE_VALUES)
            + ".",
        )

    def test_tags_normalize_to_lowercase_deduplicated_tuple(self):
        content = (
            "---\n"
            "type: project_fact\n"
            "name: Tagged fact\n"
            "description: Something tagged.\n"
            "tags: [RNAseq, rnaseq, QC]\n"
            "---\n"
            "Body\n"
        )
        parsed = parse_memory_document("memory/project/tagged.md", content)
        assert parsed.metadata is not None
        assert parsed.metadata.tags == ("rnaseq", "qc")

    def test_tags_must_be_a_list_not_a_string(self):
        errors = validate_memory_write(
            "memory/project/note.md", self._base_frontmatter(tags="rnaseq")
        )
        assert errors == (
            "Typed memory frontmatter `tags` must be a list of strings, not a string.",
        )

    def test_pinned_must_be_boolean(self):
        errors = validate_memory_write(
            "memory/project/note.md", self._base_frontmatter(pinned="\"maybe\"")
        )
        assert errors == (
            "Typed memory frontmatter `pinned` must be a boolean.",
        )

    def test_updated_at_must_be_iso_8601(self):
        errors = validate_memory_write(
            "memory/project/note.md", self._base_frontmatter(updated_at="last tuesday")
        )
        assert errors == (
            "Typed memory frontmatter `updated_at` must be an ISO-8601 string.",
        )

    def test_updated_at_accepts_iso_timestamp(self):
        parsed = parse_memory_document(
            "memory/project/note.md",
            self._base_frontmatter(updated_at="2026-04-17T00:00:00Z"),
        )
        assert parsed.metadata is not None
        # PyYAML decodes ISO timestamps to datetime; we preserve the isoformat string.
        assert parsed.metadata.updated_at == "2026-04-17T00:00:00+00:00"

    def test_infer_kind_from_source_returns_none_outside_memory_tree(self):
        assert infer_kind_from_source("workspace/SOUL.md") is None
        assert infer_kind_from_source("memory/MEMORY.md") is None
        assert infer_kind_from_source("memory/project/x.md") == "project"
        assert infer_kind_from_source("memory/user/x.md") == "user"
        assert infer_kind_from_source("memory/agent/x.md") == "agent"


class TestMemoryStateMd5:
    def test_md5_missing_files_returns_empty(self, indexer):
        assert indexer._memory_state_md5() == ""

    def test_md5_changes_after_memory_file_edit(self, indexer, tmp_path):
        mem = _write_memory_file(tmp_path, "memory/MEMORY.md", "version 1")
        md5_v1 = indexer._memory_state_md5()
        mem.write_text("version 2", encoding="utf-8")
        md5_v2 = indexer._memory_state_md5()
        assert md5_v1 != md5_v2

    def test_md5_changes_after_nested_file_is_added(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        md5_v1 = indexer._memory_state_md5()
        _write_memory_file(tmp_path, "memory/project/protocol.md", "Use the miniAgent env.\n")
        md5_v2 = indexer._memory_state_md5()
        assert md5_v1 != md5_v2


class TestRebuildIndexEdgeCases:
    def test_rebuild_missing_files_leaves_index_none(self, indexer):
        indexer.rebuild_index()
        assert indexer._index is None
        assert indexer._nodes == []

    def test_rebuild_empty_files_leaves_index_none(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "")
        _write_memory_file(tmp_path, "memory/project/notes.md", "   \n")

        indexer.rebuild_index()

        assert indexer._index is None
        assert indexer._nodes == []

    def test_rebuild_updates_last_md5_for_nested_memory_files(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(tmp_path, "memory/project/notes.md", "Project details.\n")
        expected_md5 = indexer._memory_state_md5()

        try:
            indexer.rebuild_index()
        except Exception:
            pass

        assert indexer._last_md5 == expected_md5


class TestStartupMalformedLogging:
    def test_rebuild_index_logs_malformed_typed_memory_files(
        self, indexer, tmp_path, caplog
    ):
        _write_memory_file(
            tmp_path,
            "memory/project/broken.md",
            (
                "---\n"
                "type: unsupported type\n"
                "name: Broken\n"
                "description: Wrong type value.\n"
                "---\n"
                "Body\n"
            ),
        )
        _write_memory_file(
            tmp_path,
            "memory/project/ok.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: OK note\n"
                "description: Healthy frontmatter.\n"
                "---\n"
                "Body\n"
            ),
        )

        with caplog.at_level("WARNING", logger="graph.memory_indexer"):
            indexer.rebuild_index()

        warnings = [
            record.getMessage()
            for record in caplog.records
            if record.levelname == "WARNING"
        ]
        assert any("memory/project/broken.md" in message for message in warnings)
        assert not any("memory/project/ok.md" in message for message in warnings)


class TestMaybeRebuild:
    def test_no_rebuild_when_md5_unchanged(self, indexer, tmp_path, monkeypatch):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "stable content")
        indexer._last_md5 = indexer._memory_state_md5()

        rebuild_called = []
        monkeypatch.setattr(
            indexer,
            "rebuild_index",
            lambda *args, **kwargs: rebuild_called.append(1),
        )
        indexer._maybe_rebuild()

        assert rebuild_called == []

    def test_rebuild_when_md5_differs(self, indexer, tmp_path, monkeypatch):
        _write_memory_file(tmp_path, "memory/project/notes.md", "changed content")
        indexer._last_md5 = "stale_md5"

        rebuild_called = []
        monkeypatch.setattr(
            indexer,
            "rebuild_index",
            lambda *args, **kwargs: rebuild_called.append(1),
        )
        indexer._maybe_rebuild()

        assert rebuild_called == [1]

    def test_initial_empty_md5_triggers_rebuild(self, indexer, tmp_path, monkeypatch):
        _write_memory_file(tmp_path, "memory/user/profile.md", "User likes practical solutions.")

        rebuild_called = []
        monkeypatch.setattr(
            indexer,
            "rebuild_index",
            lambda *args, **kwargs: rebuild_called.append(1),
        )
        indexer._maybe_rebuild()

        assert rebuild_called == [1]


class TestRetrieve:
    def test_retrieve_no_files_returns_empty(self, indexer):
        results = indexer.retrieve("anything")
        assert results == []

    def test_retrieve_empty_files_returns_empty(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "")
        _write_memory_file(tmp_path, "memory/project/notes.md", " ")

        results = indexer.retrieve("anything")

        assert results == []

    def test_retrieve_uses_lexical_fallback_with_section_sources(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/brca1.md",
            "# Follow Up\nBRCA1 differential expression follow-up lives in artifacts/evidence/.\n",
        )
        _write_memory_file(
            tmp_path,
            "memory/user/preferences.md",
            "# Style\nPrefer practical round-number plans over abstract summaries.\n",
        )

        results = indexer.retrieve("Where is the BRCA1 differential expression follow-up?", top_k=2)

        assert results
        assert results[0]["source"] == "memory/project/brca1.md#follow-up"
        assert "BRCA1 differential expression follow-up" in results[0]["text"]

    def test_retrieve_can_match_typed_memory_metadata(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/buffer-heuristic.md",
            (
                "---\n"
                "type: workflow_heuristic\n"
                "name: Glycine-limited running buffer\n"
                "description: Practical rule for western blot buffer scaling when glycine is limited.\n"
                "---\n"
                "# Heuristic\nPrefer round-number batches that preserve the original ratios.\n"
            ),
        )

        results = indexer.retrieve("What is the glycine running buffer heuristic?", top_k=2)

        assert results
        assert results[0]["source"] == "memory/project/buffer-heuristic.md#heuristic"
        assert results[0]["memory_type"] == "workflow_heuristic"
        assert results[0]["memory_type_label"] == "workflow heuristic"
        assert results[0]["memory_name"] == "Glycine-limited running buffer"
        assert (
            results[0]["memory_description"]
            == "Practical rule for western blot buffer scaling when glycine is limited."
        )

    def test_retrieve_carries_kind_scope_and_tags_in_result(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/project/tagged.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: Tagged project fact\n"
                "description: Scoped example with tags.\n"
                "tags: [rnaseq, de]\n"
                "---\n"
                "# Fact\nDifferential expression runs live under artifacts/de/.\n"
            ),
        )

        results = indexer.retrieve("differential expression", top_k=2)

        assert results
        top = results[0]
        assert top["memory_kind"] == "project"
        assert top["memory_scope"] == "project"
        assert top["memory_tags"] == ["rnaseq", "de"]

    def _seed_kind_scope_corpus(self, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/project-fact.md",
            (
                "---\n"
                "type: project_fact\n"
                "name: Project fact\n"
                "description: BRCA1 outputs live under artifacts/evidence.\n"
                "tags: [brca1, evidence]\n"
                "---\n"
                "BRCA1 differential expression follow-up lives in artifacts/evidence/.\n"
            ),
        )
        _write_memory_file(
            tmp_path,
            "memory/user/user-preference.md",
            (
                "---\n"
                "type: user_preference\n"
                "name: Johnny preferences\n"
                "description: Prefers concise plans for BRCA1 work.\n"
                "tags: [preferences]\n"
                "---\n"
                "Prefer practical BRCA1 plans over abstract summaries.\n"
            ),
        )
        _write_memory_file(
            tmp_path,
            "memory/agent/agent-policy.md",
            (
                "---\n"
                "type: workflow_heuristic\n"
                "name: Agent BRCA1 policy\n"
                "description: Agent-wide guidance for BRCA1 follow-up notes.\n"
                "---\n"
                "Agent BRCA1 heuristic: always verify artifacts before quoting.\n"
            ),
        )

    def test_retrieve_filters_by_single_kind(self, indexer, tmp_path):
        self._seed_kind_scope_corpus(tmp_path)

        results = indexer.retrieve("BRCA1", top_k=5, kind="project")

        assert results
        assert all(result["memory_kind"] == "project" for result in results)
        assert all("memory/project/" in result["source"] for result in results)

    def test_retrieve_filters_by_multiple_kinds(self, indexer, tmp_path):
        self._seed_kind_scope_corpus(tmp_path)

        results = indexer.retrieve("BRCA1", top_k=5, kind=["project", "user"])
        sources = {result["source"] for result in results}

        assert any("memory/project/" in source for source in sources)
        assert any("memory/user/" in source for source in sources)
        assert not any("memory/agent/" in source for source in sources)

    def test_retrieve_filters_by_scope_global_only_returns_agent_kind(self, indexer, tmp_path):
        self._seed_kind_scope_corpus(tmp_path)

        results = indexer.retrieve("BRCA1", top_k=5, scope="global")

        assert results
        assert all(result["memory_scope"] == "global" for result in results)
        assert all(result["memory_kind"] == "agent" for result in results)

    def test_retrieve_filters_by_tag_intersection(self, indexer, tmp_path):
        self._seed_kind_scope_corpus(tmp_path)

        results = indexer.retrieve("BRCA1", top_k=5, tags="brca1")

        assert results
        assert all("brca1" in (result.get("memory_tags") or []) for result in results)

    def test_retrieve_scope_defaults_match_kind_for_legacy_files(self, indexer, tmp_path):
        """Legacy files (no frontmatter) should still match scope filters that
        correspond to their directory-inferred kind. Otherwise typed and legacy
        files would behave inconsistently under the same scope filter."""
        _write_memory_file(
            tmp_path,
            "memory/project/legacy-note.md",
            "# Legacy\nBRCA1 legacy note content.\n",
        )
        _write_memory_file(
            tmp_path,
            "memory/user/legacy-pref.md",
            "# Legacy\nBRCA1 legacy user preference content.\n",
        )

        project_results = indexer.retrieve("BRCA1 legacy", top_k=5, scope="project")
        user_results = indexer.retrieve("BRCA1 legacy", top_k=5, scope="user")

        assert any(
            r["source"].startswith("memory/project/legacy-note.md")
            for r in project_results
        )
        assert any(
            r["source"].startswith("memory/user/legacy-pref.md")
            for r in user_results
        )

    def test_retrieve_returns_empty_when_filter_excludes_all(self, indexer, tmp_path):
        self._seed_kind_scope_corpus(tmp_path)

        results = indexer.retrieve("BRCA1", top_k=5, scope="session")

        assert results == []

    def test_retrieve_respects_top_k_when_lexical_fallback_matches_many_sections(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        for index in range(5):
            _write_memory_file(
                tmp_path,
                f"memory/project/note-{index}.md",
                f"# Topic {index}\nScanpy topic {index} guidance.\n",
            )

        results = indexer.retrieve("Scanpy guidance", top_k=2)

        assert len(results) == 2

    @NEEDS_OPENAI
    def test_retrieve_with_content_returns_dicts(self, indexer, tmp_path):
        _write_memory_file(
            tmp_path,
            "memory/MEMORY.md",
            "User likes Python. User is a software engineer.",
        )

        results = indexer.retrieve("Python")

        assert isinstance(results, list)
        for result in results:
            assert "text" in result
            assert "score" in result
            assert "source" in result

    @NEEDS_OPENAI
    def test_retrieve_can_return_nested_memory_sources(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path,
            "memory/project/analysis.md",
            "The Scanpy QC pipeline lives under backend/tools/.\n",
        )

        results = indexer.retrieve("Scanpy", top_k=2)

        assert any(result["source"] == "memory/project/analysis.md" for result in results)

    @NEEDS_OPENAI
    def test_retrieve_top_k_respected(self, indexer, tmp_path):
        content = "\n".join(
            f"Fact number {index}: something about topic {index}."
            for index in range(20)
        )
        _write_memory_file(tmp_path, "memory/MEMORY.md", content)

        results = indexer.retrieve("topic", top_k=2)

        assert len(results) <= 2


class TestIncrementalRebuild:
    """Per-file invalidation: only the files that changed should be re-parsed."""

    def test_diff_state_maps_identifies_added_modified_removed(self, indexer):
        old = {
            "memory/a.md": (1.0, 10, "hash_a"),
            "memory/b.md": (1.0, 20, "hash_b"),
            "memory/c.md": (1.0, 30, "hash_c"),
        }
        new = {
            "memory/a.md": (1.0, 10, "hash_a"),         # unchanged
            "memory/b.md": (2.0, 25, "hash_b_edited"),  # modified
            "memory/d.md": (2.0, 40, "hash_d"),         # added
        }

        added, modified, removed = indexer._diff_state_maps(old, new)

        assert added == {"memory/d.md"}
        assert modified == {"memory/b.md"}
        assert removed == {"memory/c.md"}

    def test_single_file_edit_only_reparses_that_file(
        self, indexer, tmp_path, monkeypatch
    ):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path, "memory/project/alpha.md", "# Alpha\nAlpha body content.\n"
        )
        _write_memory_file(
            tmp_path, "memory/project/beta.md", "# Beta\nBeta body content.\n"
        )
        _write_memory_file(
            tmp_path, "memory/user/profile.md", "# Profile\nUser profile content.\n"
        )
        indexer._maybe_rebuild()
        assert indexer._file_states  # initial state seeded

        import graph.memory_indexer as memory_indexer_module

        parse_calls: list[str] = []
        original_parse = memory_indexer_module.parse_memory_document

        def tracking_parse(source, content):
            parse_calls.append(source)
            return original_parse(source, content)

        monkeypatch.setattr(
            memory_indexer_module, "parse_memory_document", tracking_parse
        )

        # Touch exactly one file with new content.
        (tmp_path / "memory" / "project" / "beta.md").write_text(
            "# Beta\nBeta body content — updated.\n", encoding="utf-8"
        )

        indexer._maybe_rebuild()

        assert parse_calls == ["memory/project/beta.md"]
        assert any(
            section.text.endswith("updated.")
            for section in indexer._file_sections["memory/project/beta.md"]
        )
        # Other files' sections are untouched references from the initial build.
        assert "memory/project/alpha.md" in indexer._file_sections
        assert "memory/user/profile.md" in indexer._file_sections

    def test_removing_a_file_drops_its_sections(self, indexer, tmp_path):
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path, "memory/project/keep.md", "# Keep\nKept content.\n"
        )
        target = _write_memory_file(
            tmp_path, "memory/project/drop.md", "# Drop\nDropped content.\n"
        )
        indexer._maybe_rebuild()
        assert "memory/project/drop.md" in indexer._file_sections

        target.unlink()
        indexer._maybe_rebuild()

        assert "memory/project/drop.md" not in indexer._file_sections
        assert "memory/project/keep.md" in indexer._file_sections
        assert not any(
            section.source.startswith("memory/project/drop.md")
            for section in indexer._sections
        )

    def test_benchmark_10k_file_tree_single_edit_under_one_second(
        self, indexer, tmp_path, monkeypatch
    ):
        """A single-file edit in a 10k-file corpus updates in < 1s.

        The embedder is never invoked: rebuild_index bails out before touching
        LlamaIndex (no embedding backend is configured in the test env), and
        the incremental path only re-parses the one changed file.
        """
        total_files = 10_000
        files_per_dir = 100
        for index in range(total_files):
            subdir = f"memory/project/bucket_{index // files_per_dir:03d}"
            _write_memory_file(
                tmp_path,
                f"{subdir}/note_{index:05d}.md",
                f"# Note {index}\nBody for note {index}.\n",
            )

        # Seed state with an initial scan (not timed).
        indexer._maybe_rebuild()
        assert len(indexer._file_states) == total_files

        import graph.memory_indexer as memory_indexer_module

        parse_calls: list[str] = []
        original_parse = memory_indexer_module.parse_memory_document

        def tracking_parse(source, content):
            parse_calls.append(source)
            return original_parse(source, content)

        monkeypatch.setattr(
            memory_indexer_module, "parse_memory_document", tracking_parse
        )

        # Edit exactly one file.
        target = tmp_path / "memory/project/bucket_042/note_04237.md"
        target.write_text("# Note 4237\nBody for note 4237 — revised.\n", encoding="utf-8")

        import time

        start = time.perf_counter()
        indexer._maybe_rebuild()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, (
            f"Single-file edit in {total_files}-file tree took {elapsed:.3f}s"
        )
        assert parse_calls == ["memory/project/bucket_042/note_04237.md"]


class TestLLMProbeRetrieval:
    """Exercise the LLM-probe retrieval helpers that support rag_mode=llm_probe."""

    def _write_typed_file(self, tmp_path, relative, name, description, body="Body."):
        content = (
            "---\n"
            "type: project_fact\n"
            f"name: {name}\n"
            f"description: {description}\n"
            "---\n"
            f"{body}\n"
        )
        _write_memory_file(tmp_path, relative, content)

    def test_build_probe_index_lists_sources_with_name_and_description(
        self, indexer, tmp_path
    ):
        self._write_typed_file(
            tmp_path,
            "memory/project/a.md",
            "Alpha",
            "A description.",
        )
        self._write_typed_file(
            tmp_path,
            "memory/user/b.md",
            "Beta",
            "B description.",
        )

        rendered, valid_sources = indexer.build_probe_index(max_chars=10_000)

        assert "memory/project/a.md" in rendered
        assert "Alpha" in rendered
        assert "A description" in rendered
        assert "memory/user/b.md" in rendered
        assert set(valid_sources) == {"memory/project/a.md", "memory/user/b.md"}

    def test_build_probe_index_respects_char_budget(self, indexer, tmp_path):
        for i in range(20):
            self._write_typed_file(
                tmp_path,
                f"memory/project/note_{i:02d}.md",
                f"Note {i}",
                "Some descriptive text for the probe index listing.",
            )

        rendered, valid_sources = indexer.build_probe_index(max_chars=200)

        assert len(rendered) <= 200 + 50  # a bit of slack for the final entry
        assert 0 < len(valid_sources) < 20

    def test_parse_probe_selection_extracts_json_array(self, indexer):
        valid = ["memory/project/a.md", "memory/user/b.md", "memory/agent/c.md"]
        response = (
            "Here are the relevant files:\n"
            '["memory/user/b.md", "memory/project/a.md"]\n'
        )

        picked = indexer.parse_probe_selection(response, valid)

        assert picked == ["memory/user/b.md", "memory/project/a.md"]

    def test_parse_probe_selection_filters_unknown_paths(self, indexer):
        valid = ["memory/project/a.md"]
        response = '["memory/project/hallucinated.md", "memory/project/a.md"]'

        picked = indexer.parse_probe_selection(response, valid)

        assert picked == ["memory/project/a.md"]

    def test_parse_probe_selection_falls_back_to_line_based_parse(self, indexer):
        valid = ["memory/project/a.md", "memory/user/b.md"]
        response = "- memory/project/a.md\n- memory/user/b.md\n"

        picked = indexer.parse_probe_selection(response, valid)

        assert picked == ["memory/project/a.md", "memory/user/b.md"]

    def test_parse_probe_selection_caps_to_top_k(self, indexer):
        valid = [f"memory/project/f{i}.md" for i in range(10)]
        response = json.dumps(valid)

        picked = indexer.parse_probe_selection(response, valid, top_k=3)

        assert picked == valid[:3]

    def test_parse_probe_selection_empty_response(self, indexer):
        assert indexer.parse_probe_selection("", ["memory/a.md"]) == []
        assert indexer.parse_probe_selection("[]", ["memory/a.md"]) == []

    def test_build_probe_results_shape_matches_retrieval_contract(
        self, indexer, tmp_path
    ):
        self._write_typed_file(
            tmp_path,
            "memory/project/a.md",
            "Alpha",
            "A description.",
            body="Alpha details body.",
        )
        indexer.build_probe_index(max_chars=10_000)  # triggers rebuild

        results = indexer.build_probe_results(["memory/project/a.md"])

        assert len(results) == 1
        result = results[0]
        assert set(result.keys()) >= {"text", "score", "source"}
        assert result["source"].startswith("memory/project/a.md")
        assert result["memory_name"] == "Alpha"
        assert 0 < result["score"] <= 1.0

    def test_probe_cache_invalidates_on_corpus_change(self, indexer, tmp_path):
        self._write_typed_file(
            tmp_path, "memory/project/a.md", "Alpha", "A description."
        )
        indexer.build_probe_index(max_chars=10_000)
        digest_before = indexer.memory_corpus_digest()

        indexer.cache_probe_selection(
            "session-1", digest_before, ["memory/project/a.md"]
        )
        assert indexer.get_cached_probe_selection("session-1", digest_before) == [
            "memory/project/a.md"
        ]

        self._write_typed_file(
            tmp_path, "memory/project/b.md", "Beta", "B description."
        )
        indexer.build_probe_index(max_chars=10_000)
        digest_after = indexer.memory_corpus_digest()

        assert digest_after != digest_before
        assert indexer.get_cached_probe_selection("session-1", digest_after) is None

    def test_memory_file_count_reflects_eligible_files(self, indexer, tmp_path):
        assert indexer.memory_file_count() == 0
        _write_memory_file(tmp_path, "memory/MEMORY.md", "# Index\n")
        _write_memory_file(
            tmp_path, "memory/project/one.md", "# One\nBody.\n"
        )
        assert indexer.memory_file_count() == 2
