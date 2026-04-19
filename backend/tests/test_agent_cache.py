"""Tests for the per-session agent cache on :class:`AgentManager`.

Guards issue #112: ``_build_agent`` must return the same agent instance on
consecutive turns for the same session and invalidate when any input that
changes the built runnable (llm identity, tool names, assembled system
prompt) changes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools  # noqa: F401  (side-effect import — matches other graph tests)


def _valid_session_id(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def _fresh_manager(tmp_path):
    from graph.agent import AgentManager
    from graph.session_manager import SessionManager

    manager = AgentManager()
    manager.base_dir = tmp_path
    manager.session_manager = SessionManager(base_dir=tmp_path)
    manager.llm = MagicMock(name="primary_llm")
    manager.tools = []
    return manager


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


async def test_build_agent_cache_hits_on_consecutive_calls(tmp_path):
    manager = _fresh_manager(tmp_path)
    session_id = _valid_session_id(1)

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ) as creator, patch(
        "graph.agent.build_system_prompt_blocks",
        return_value=("STABLE", "VOLATILE"),
    ):
        first, _ = await manager._build_agent(session_id=session_id)
        second, _ = await manager._build_agent(session_id=session_id)

    assert first is second, "Cached agent must be reused across turns"
    assert creator.call_count == 1


async def test_build_agent_cache_invalidates_on_prompt_change(tmp_path):
    manager = _fresh_manager(tmp_path)
    session_id = _valid_session_id(2)

    prompts = iter([("STABLE_A", "VOLATILE"), ("STABLE_B", "VOLATILE")])

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ) as creator, patch(
        "graph.agent.build_system_prompt_blocks",
        side_effect=lambda *args, **kwargs: next(prompts),
    ):
        first, _ = await manager._build_agent(session_id=session_id)
        second, _ = await manager._build_agent(session_id=session_id)

    assert first is not second
    assert creator.call_count == 2


async def test_build_agent_cache_invalidates_on_tool_change(tmp_path):
    manager = _fresh_manager(tmp_path)
    manager.tools = [_FakeTool("read_file")]
    session_id = _valid_session_id(3)

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ) as creator, patch(
        "graph.agent.build_system_prompt_blocks",
        return_value=("STABLE", "VOLATILE"),
    ):
        first, _ = await manager._build_agent(session_id=session_id)
        manager.tools = [_FakeTool("read_file"), _FakeTool("run_bash")]
        second, _ = await manager._build_agent(session_id=session_id)

    assert first is not second
    assert creator.call_count == 2


async def test_build_agent_fallback_llm_bypasses_cache(tmp_path):
    manager = _fresh_manager(tmp_path)
    session_id = _valid_session_id(4)
    fallback_llm = MagicMock(name="fallback_llm")

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ) as creator, patch(
        "graph.agent.build_system_prompt_blocks",
        return_value=("STABLE", "VOLATILE"),
    ):
        primary, _ = await manager._build_agent(session_id=session_id)
        await manager._build_agent(
            session_id=session_id,
            llm=fallback_llm,
            use_cache=False,
        )
        primary_again, _ = await manager._build_agent(session_id=session_id)

    assert primary is primary_again, (
        "Fallback build must not evict or overwrite the primary cache entry"
    )
    # create_agent calls: primary miss + fallback bypass = 2; second primary hits cache.
    assert creator.call_count == 2


async def test_clear_session_runtime_drops_cached_agent(tmp_path):
    manager = _fresh_manager(tmp_path)
    session_id = _valid_session_id(5)

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ) as creator, patch(
        "graph.agent.build_system_prompt_blocks",
        return_value=("STABLE", "VOLATILE"),
    ):
        first, _ = await manager._build_agent(session_id=session_id)
        manager.clear_session_runtime(session_id)
        second, _ = await manager._build_agent(session_id=session_id)

    assert first is not second
    assert creator.call_count == 2


async def test_build_agent_without_session_id_does_not_cache(tmp_path):
    manager = _fresh_manager(tmp_path)

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ) as creator, patch(
        "graph.agent.build_system_prompt_blocks",
        return_value=("STABLE", "VOLATILE"),
    ):
        first, _ = await manager._build_agent(session_id=None)
        second, _ = await manager._build_agent(session_id=None)

    assert first is not second
    assert creator.call_count == 2
