from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_tool_trace_dir(monkeypatch, tmp_path):
    """Redirect tool-trace and tool-output-overflow writes into tmp.

    The production defaults write under ``backend/storage/tool-traces/`` and
    ``backend/storage/tool-outputs/``. Tests should not touch those locations.
    """
    monkeypatch.setenv("BIOAPEX_TOOL_TRACE_DIR", str(tmp_path / "tool-traces"))
    monkeypatch.setenv("BIOAPEX_TOOL_OUTPUT_DIR", str(tmp_path / "tool-outputs"))
    yield
