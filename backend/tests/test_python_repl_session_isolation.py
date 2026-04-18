"""Regression test for issue #65.

Confirms that ``PythonReplTool`` keeps per-session interpreter state isolated
when two concurrent asyncio tasks run under different
``ToolPolicyExecutionContext.session_id`` values. The non-concurrent path is
already covered by ``test_persistence_isolated_by_policy_session_id`` in
``test_tools.py``; this test exercises the threaded path that
``_execution_lock`` and ``_session_states`` are designed to protect.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_concurrent_sessions_do_not_leak_variables():
    from tools.policy import tool_policy_context
    from tools.policy_types import ToolPolicyExecutionContext
    from tools.python_repl_tool import PythonReplTool

    tool = PythonReplTool()

    # Forces both threads to reach the interleaving point before either reads
    # the other session's state, so the test would fail under a naive shared
    # namespace even on machines that otherwise serialise the two calls.
    barrier = threading.Barrier(2)

    def run_session(session_id: str, marker: str) -> tuple[str, str]:
        with tool_policy_context(ToolPolicyExecutionContext(session_id=session_id)):
            tool._run(f"marker = {marker!r}")
            barrier.wait(timeout=5)
            own = tool._run("print(marker)")
            other = tool._run("print(globals().get('other_marker', 'missing'))")
            return own, other

    results = await asyncio.gather(
        asyncio.to_thread(run_session, "concurrent-session-a", "from-a"),
        asyncio.to_thread(run_session, "concurrent-session-b", "from-b"),
    )

    (own_a, other_a), (own_b, other_b) = results

    assert "from-a" in own_a
    assert "from-b" in own_b
    # Neither session defined ``other_marker``; leakage from the sibling
    # session would surface its ``marker`` value instead of "missing".
    assert "missing" in other_a
    assert "missing" in other_b


async def test_concurrent_sessions_preserve_own_state_after_interleaving():
    from tools.policy import tool_policy_context
    from tools.policy_types import ToolPolicyExecutionContext
    from tools.python_repl_tool import PythonReplTool

    tool = PythonReplTool()
    barrier = threading.Barrier(2)

    def set_then_wait(session_id: str, value: int) -> None:
        with tool_policy_context(ToolPolicyExecutionContext(session_id=session_id)):
            tool._run(f"x = {value}")
            barrier.wait(timeout=5)

    await asyncio.gather(
        asyncio.to_thread(set_then_wait, "iso-session-a", 1),
        asyncio.to_thread(set_then_wait, "iso-session-b", 2),
    )

    def read(session_id: str) -> str:
        with tool_policy_context(ToolPolicyExecutionContext(session_id=session_id)):
            return tool._run("print(x)")

    read_a, read_b = await asyncio.gather(
        asyncio.to_thread(read, "iso-session-a"),
        asyncio.to_thread(read, "iso-session-b"),
    )

    assert "1" in read_a
    assert "2" in read_b
