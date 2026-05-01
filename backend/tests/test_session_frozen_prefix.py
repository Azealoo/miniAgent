"""Tests for session-scoped frozen prompt prefix reuse across sub-agents.

These tests guard the prompt-cache plumbing added for issue #81:
the parent session freezes its stable prefix on the first turn, and every
sub-agent run (plan / verification) prepends that frozen prefix verbatim so
DeepSeek / OpenAI / Anthropic prefix caches match the parent's leading bytes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the tools package first so the tools <-> runtime.subagent module
# graph is fully initialized before test functions pull modules in. Matches
# the pattern the in-tree helper / planner tests rely on; without this,
# importing runtime.subagent before tools/__init__.py has finished triggers
# a partial-module ImportError at collection time.
import tools  # noqa: F401  (side-effect import)


def _valid_session_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


# ──────────────────────────────────────────────────────────────────────────────
# SessionManager: freeze + drift detection
# ──────────────────────────────────────────────────────────────────────────────


class TestFrozenSessionPrefix:
    def test_freeze_returns_same_snapshot_on_repeat_calls(self, tmp_path):
        from graph.session_manager import SessionManager

        session_id = _valid_session_id(1)
        sm = SessionManager(base_dir=tmp_path)
        sm.create_session()  # Seed a session file so delete works later.
        frozen_a = sm.freeze_session_prefix(
            session_id,
            stable_prefix="<!-- Skills Snapshot -->\nx",
            tool_names=("read_file", "run_bash"),
        )
        frozen_b = sm.freeze_session_prefix(
            session_id,
            stable_prefix="<!-- different -->\nz",
            tool_names=("read_file",),
        )
        assert frozen_a is frozen_b, (
            "The first snapshot must be sticky — subsequent calls return it verbatim"
        )
        assert sm.get_frozen_session_prefix(session_id) is frozen_a

    def test_drift_logs_warning_every_time(self, tmp_path, caplog):
        from graph.session_manager import SessionManager

        session_id = _valid_session_id(2)
        sm = SessionManager(base_dir=tmp_path)

        sm.freeze_session_prefix(
            session_id,
            stable_prefix="stable",
            tool_names=("a",),
        )

        with caplog.at_level("WARNING", logger="graph.session.session_store"):
            sm.freeze_session_prefix(
                session_id,
                stable_prefix="stable-edited",
                tool_names=("a",),
            )
            sm.freeze_session_prefix(
                session_id,
                stable_prefix="stable-edited-again",
                tool_names=("a",),
            )
            # A call whose fingerprint matches the frozen snapshot must not log.
            sm.freeze_session_prefix(
                session_id,
                stable_prefix="stable",
                tool_names=("a",),
            )

        drift_logs = [r for r in caplog.records if "session_prefix_drift" in r.message]
        assert len(drift_logs) == 2, (
            "Drift warning must fire on every drifting call so repeated "
            "degradation stays visible; matching calls must not log."
        )

    def test_delete_session_clears_frozen_prefix(self, tmp_path):
        from graph.session_manager import SessionManager

        sm = SessionManager(base_dir=tmp_path)
        session_id = sm.create_session()
        sm.freeze_session_prefix(
            session_id,
            stable_prefix="stable",
            tool_names=("a",),
        )
        assert sm.get_frozen_session_prefix(session_id) is not None

        sm.delete_session(session_id)
        assert sm.get_frozen_session_prefix(session_id) is None

    def test_mid_session_skill_addition_triggers_prefix_drift(self, tmp_path, caplog):
        """A new skill registered mid-session must change the assembled
        stable prefix so ``freeze_session_prefix`` detects drift and logs
        ``session_prefix_drift`` — otherwise the cache silently misses."""
        from graph.prompt_builder import build_system_prompt_blocks
        from graph.session_manager import SessionManager

        # Minimal workspace so build_system_prompt_blocks has something to
        # assemble. We only need the skills tree to be writable.
        (tmp_path / "workspace").mkdir()
        (tmp_path / "workspace" / "SOUL.md").write_text("soul", encoding="utf-8")
        (tmp_path / "skills").mkdir()

        session_id = _valid_session_id(42)
        sm = SessionManager(base_dir=tmp_path)
        sm.create_session()

        turn1_stable, _ = build_system_prompt_blocks(tmp_path, rag_mode=False)
        sm.freeze_session_prefix(
            session_id,
            stable_prefix=turn1_stable,
            tool_names=("read_file",),
        )

        # Mid-session: register a new skill. This is the exact mutation the
        # issue flags — the stable prefix changes shape but nothing else in
        # the runtime notices.
        skill_dir = tmp_path / "skills" / "new_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            (
                "---\nname: new_skill\ndescription: A new skill added mid-session.\n"
                "category: bio/literature\n"
                "requires_tools: [read_file]\nrequires_network: false\n"
                "user_invocable: true\nspecies: any\nmodality: literature\n"
                "stage: analysis\nstability: experimental\nsafety_level: low\n"
                "---\n# Body\n"
            ),
            encoding="utf-8",
        )

        turn2_stable, _ = build_system_prompt_blocks(tmp_path, rag_mode=False)
        assert turn1_stable != turn2_stable, (
            "adding a skill mid-session must change the assembled stable "
            "prefix — otherwise the drift hook has nothing to detect"
        )

        with caplog.at_level("WARNING", logger="graph.session.session_store"):
            sm.freeze_session_prefix(
                session_id,
                stable_prefix=turn2_stable,
                tool_names=("read_file",),
            )

        drift_logs = [r for r in caplog.records if "session_prefix_drift" in r.message]
        assert len(drift_logs) == 1, (
            "freeze_session_prefix must log session_prefix_drift when the "
            "re-assembled prefix no longer matches the first-turn fingerprint"
        )


# ──────────────────────────────────────────────────────────────────────────────
# SubAgentContract: compose stable prefix into the final system prompt
# ──────────────────────────────────────────────────────────────────────────────


class TestSubAgentContractPromptComposition:
    def test_stable_prefix_is_prepended_verbatim(self):
        from runtime.subagent import SubAgentContract

        contract = SubAgentContract(
            name="plan_agent",
            system_prompt="You are the planner. Return only JSON.",
            tools_allowed=(type("T", (), {"name": "read_file"})(),),
            max_steps=10,
            token_budget=0,
            stable_prefix="<!-- Skills Snapshot -->\nFROZEN",
        )
        composed = contract.composed_system_prompt()
        assert composed.startswith("<!-- Skills Snapshot -->\nFROZEN")
        assert composed.endswith("You are the planner. Return only JSON.")

    def test_empty_stable_prefix_returns_helper_prompt_unchanged(self):
        from runtime.subagent import SubAgentContract

        contract = SubAgentContract(
            name="plan_agent",
            system_prompt="You are the planner.",
            tools_allowed=(type("T", (), {"name": "read_file"})(),),
            max_steps=10,
            token_budget=0,
        )
        assert contract.composed_system_prompt() == "You are the planner."


# ──────────────────────────────────────────────────────────────────────────────
# run_subagent: hands composed prompt to create_agent and records cache stats
# ──────────────────────────────────────────────────────────────────────────────


class _FakeChunk:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeUsageOutput:
    def __init__(self, usage_metadata: dict[str, Any]) -> None:
        self.usage_metadata = usage_metadata


class _FakeAgent:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    async def astream_events(
        self,
        payload,
        version: str = "v2",
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        for event in self._events:
            yield event


@pytest.mark.asyncio
async def test_run_subagent_prepends_stable_prefix_to_create_agent(tmp_path):
    from runtime.subagent import SubAgentContract, run_subagent

    captured: dict[str, Any] = {}

    def _fake_create_agent(llm, tools, system_prompt):
        captured["system_prompt"] = system_prompt
        return _FakeAgent([{"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("done")}}])

    contract = SubAgentContract(
        name="plan_agent",
        system_prompt="You are the planner.",
        tools_allowed=(type("T", (), {"name": "read_file"})(),),
        max_steps=10,
        token_budget=0,
        stable_prefix="<!-- Frozen -->\nFROZEN_BLOB",
    )

    with patch("runtime.subagent.create_agent", side_effect=_fake_create_agent):
        artifact = await run_subagent(
            contract,
            llm=object(),
            user_prompt="Plan a task.",
            base_dir=tmp_path,
        )

    assert artifact.status == "ok"
    assert captured["system_prompt"].startswith("<!-- Frozen -->\nFROZEN_BLOB")
    assert "You are the planner." in captured["system_prompt"]


@pytest.mark.asyncio
async def test_run_subagent_captures_prompt_cache_hit_rate(tmp_path):
    from runtime.subagent import SubAgentContract, run_subagent

    # Simulate two LLM turns: the first primes the cache, the second is a
    # near-complete cache hit. cache_hit_rate should reflect the blended ratio.
    events = [
        {
            "event": "on_chat_model_end",
            "data": {
                "output": _FakeUsageOutput(
                    {
                        "input_tokens": 1000,
                        "input_token_details": {
                            "cache_read": 0,
                            "cache_creation": 900,
                        },
                    }
                )
            },
        },
        {"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("intermediate")}},
        {
            "event": "on_chat_model_end",
            "data": {
                "output": _FakeUsageOutput(
                    {
                        "input_tokens": 1000,
                        "input_token_details": {
                            "cache_read": 950,
                            "cache_creation": 0,
                        },
                    }
                )
            },
        },
    ]

    contract = SubAgentContract(
        name="plan_agent",
        system_prompt="You are the planner.",
        tools_allowed=(type("T", (), {"name": "read_file"})(),),
        max_steps=10,
        token_budget=0,
        stable_prefix="prefix",
    )

    with patch("runtime.subagent.create_agent", return_value=_FakeAgent(events)):
        artifact = await run_subagent(
            contract,
            llm=object(),
            user_prompt="Plan.",
            base_dir=tmp_path,
        )

    assert artifact.cache_stats is not None
    stats = artifact.cache_stats
    assert stats["llm_calls"] == 2
    assert stats["cache_read_tokens"] == 950
    assert stats["cache_creation_tokens"] == 900
    # 950 cache-read / (950 read + 900 create + 150 uncached) ≈ 0.475
    assert 0.45 < stats["cache_hit_rate"] < 0.50
    payload_stats = artifact.payload["cache_stats"]
    assert payload_stats["cache_read_tokens"] == 950


@pytest.mark.asyncio
async def test_run_subagent_without_usage_metadata_omits_cache_stats(tmp_path):
    from runtime.subagent import SubAgentContract, run_subagent

    events = [{"event": "on_chat_model_stream", "data": {"chunk": _FakeChunk("done")}}]
    contract = SubAgentContract(
        name="plan_agent",
        system_prompt="You are the planner.",
        tools_allowed=(type("T", (), {"name": "read_file"})(),),
        max_steps=10,
        token_budget=0,
    )

    with patch("runtime.subagent.create_agent", return_value=_FakeAgent(events)):
        artifact = await run_subagent(
            contract,
            llm=object(),
            user_prompt="Plan.",
            base_dir=tmp_path,
        )

    assert artifact.cache_stats is None
    assert "cache_stats" not in artifact.payload


# ──────────────────────────────────────────────────────────────────────────────
# resolve_session_stable_prefix: wired via the tool policy context + manager
# ──────────────────────────────────────────────────────────────────────────────


def test_resolve_session_stable_prefix_returns_frozen_when_set(tmp_path):
    from graph.agent import agent_manager
    from graph.session_manager import SessionManager
    from runtime.subagent import resolve_session_stable_prefix
    from tools.policy import tool_policy_context
    from tools.policy_types import ToolPolicyExecutionContext

    session_id = _valid_session_id(99)
    sm = SessionManager(base_dir=tmp_path)
    sm.freeze_session_prefix(
        session_id,
        stable_prefix="FROZEN_PREFIX_XYZ",
        tool_names=("read_file",),
    )

    previous = agent_manager.session_manager
    agent_manager.session_manager = sm
    try:
        with tool_policy_context(ToolPolicyExecutionContext(session_id=session_id)):
            assert resolve_session_stable_prefix() == "FROZEN_PREFIX_XYZ"
    finally:
        agent_manager.session_manager = previous


def test_resolve_session_stable_prefix_empty_without_context():
    from runtime.subagent import resolve_session_stable_prefix

    # No policy context installed → empty prefix (sub-agent falls back cleanly)
    assert resolve_session_stable_prefix() == ""
