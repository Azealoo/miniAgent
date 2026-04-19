"""Concurrency guards for ``AgentManager._agent_cache``.

Guards issue #221: two sessions racing a ``_build_agent`` call must not
corrupt each other's cache entries. The asyncio.Lock around the cache and
the ``(session_id, role_config_hash)`` key together ensure that concurrent
builds for distinct sessions both survive.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools  # noqa: F401


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


async def test_concurrent_build_agent_across_sessions_preserves_both_entries(
    tmp_path,
):
    """Two sessions racing ``_build_agent`` must each end up with a cache entry."""
    manager = _fresh_manager(tmp_path)
    session_a = _valid_session_id(1)
    session_b = _valid_session_id(2)

    call_count = {"n": 0}

    def fake_create_agent(llm, tools_, system_prompt):
        call_count["n"] += 1
        return object()

    with patch(
        "graph.agent.create_agent", side_effect=fake_create_agent
    ), patch(
        "graph.agent.build_system_prompt_blocks",
        return_value=("STABLE", "VOLATILE"),
    ):
        task_a = asyncio.create_task(manager._build_agent(session_id=session_a))
        task_b = asyncio.create_task(manager._build_agent(session_id=session_b))
        agent_a, agent_b = await asyncio.gather(task_a, task_b)

    # Both session entries survive — neither clobbered the other.
    keys = list(manager._agent_cache.keys())
    assert len(keys) == 2
    session_ids_cached = {key[0] for key in keys}
    assert session_ids_cached == {session_a, session_b}

    # The cached objects match what _build_agent returned.
    (entry_a,) = [v for k, v in manager._agent_cache.items() if k[0] == session_a]
    (entry_b,) = [v for k, v in manager._agent_cache.items() if k[0] == session_b]
    assert entry_a is agent_a
    assert entry_b is agent_b
    assert agent_a is not agent_b
    assert call_count["n"] == 2


async def test_second_hash_for_same_session_replaces_prior_entry(tmp_path):
    """Cap-at-one invariant: a new role_config_hash evicts the previous entry."""
    manager = _fresh_manager(tmp_path)
    session_id = _valid_session_id(3)

    prompts = iter([
        ("STABLE_A", "VOLATILE"),
        ("STABLE_B", "VOLATILE"),
    ])

    with patch(
        "graph.agent.create_agent",
        side_effect=lambda llm, tools_, system_prompt: object(),
    ), patch(
        "graph.agent.build_system_prompt_blocks",
        side_effect=lambda *args, **kwargs: next(prompts),
    ):
        await manager._build_agent(session_id=session_id)
        await manager._build_agent(session_id=session_id)

    keys = [k for k in manager._agent_cache if k[0] == session_id]
    assert len(keys) == 1, (
        "Cap-at-one-per-session: the new hash must evict the previous entry"
    )
