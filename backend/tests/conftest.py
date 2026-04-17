from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_tool_trace_dir(monkeypatch, tmp_path):
    """Redirect tool-trace JSONL writes to a per-test tmp directory.

    The production default writes under ``backend/storage/tool-traces/``; tests
    should not touch that location.
    """
    monkeypatch.setenv("BIOAPEX_TOOL_TRACE_DIR", str(tmp_path / "tool-traces"))
    yield
