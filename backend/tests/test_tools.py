"""
Tests for all 5 core tools.
No LLM or embedding API keys required.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ──────────────────────────────────────────────────────────────────────────────
# TerminalTool
# ──────────────────────────────────────────────────────────────────────────────

class TestTerminalTool:
    def setup_method(self, tmp_path):
        from tools.terminal_tool import TerminalTool
        self.base = Path(__file__).parent.parent
        self.tool = TerminalTool(base_dir=str(self.base))

    def test_basic_echo(self):
        out = self.tool._run("echo hello_world")
        assert "hello_world" in out

    def test_multiline_output(self):
        out = self.tool._run("echo line1 && echo line2")
        assert "line1" in out
        assert "line2" in out

    def test_pwd_is_project_root(self):
        out = self.tool._run("pwd")
        assert str(self.base) in out

    def test_stderr_captured(self):
        out = self.tool._run("ls /nonexistent_path_xyz_123 2>&1 || true")
        assert out  # some output from the shell

    def test_empty_output_message(self):
        out = self.tool._run("true")
        assert out == "(no output)"

    def test_blacklist_fork_bomb(self):
        out = self.tool._run(":(){ :|:& };:")
        assert "[BLOCKED]" in out

    def test_blacklist_rm_rf(self):
        out = self.tool._run("rm -rf /")
        assert "[BLOCKED]" in out

    def test_blacklist_mkfs(self):
        out = self.tool._run("mkfs /dev/sda1")
        assert "[BLOCKED]" in out

    def test_output_cap(self):
        # Generate output > 5000 chars
        out = self.tool._run("python3 -c \"print('x' * 10000)\"")
        assert len(out) <= 5001 + len("\n...[output truncated]")
        assert "[output truncated]" in out

    def test_nonexistent_command(self):
        out = self.tool._run("nonexistent_binary_xyz_abc_123 2>&1 || true")
        assert out  # shell error message

    def test_env_variable(self):
        out = self.tool._run("echo $HOME")
        assert out  # HOME is set in any normal environment


# ──────────────────────────────────────────────────────────────────────────────
# PythonReplTool
# ──────────────────────────────────────────────────────────────────────────────

class TestPythonReplTool:
    def setup_method(self, method):
        from tools.python_repl_tool import PythonReplTool
        self.tool = PythonReplTool()

    def test_basic_arithmetic(self):
        out = self.tool._run("print(2 + 2)")
        assert "4" in out

    def test_string_output(self):
        out = self.tool._run("print('hello from repl')")
        assert "hello from repl" in out

    def test_import_stdlib(self):
        out = self.tool._run("import math; print(math.pi)")
        assert "3.14" in out

    def test_persistence_variable(self):
        """Variable defined in call 1 must be accessible in call 2."""
        self.tool._run("x = 42")
        out = self.tool._run("print(x)")
        assert "42" in out

    def test_persistence_import(self):
        """Import in call 1 must still work in call 2."""
        self.tool._run("import json")
        out = self.tool._run("print(json.dumps({'key': 'val'}))")
        assert "key" in out

    def test_syntax_error_handled(self):
        out = self.tool._run("def broken(:")
        assert "[ERROR]" in out or "SyntaxError" in out

    def test_runtime_error_handled(self):
        out = self.tool._run("1/0")
        assert "ZeroDivisionError" in out or "[ERROR]" in out

    def test_output_cap(self):
        out = self.tool._run("print('a' * 10000)")
        assert "[output truncated]" in out

    def test_multiline_code(self):
        code = "total = 0\nfor i in range(10):\n    total += i\nprint(total)"
        out = self.tool._run(code)
        assert "45" in out

    def test_single_instance_reused(self):
        """_repl should be the same object across calls (true persistence)."""
        self.tool._run("sentinel = 'unique_test_value_abc'")
        out = self.tool._run("print(sentinel)")
        assert "unique_test_value_abc" in out

    def test_repl_starts_as_none(self):
        from tools.python_repl_tool import PythonReplTool
        fresh = PythonReplTool()
        assert fresh._repl is None

    def test_repl_initialised_after_first_call(self):
        from tools.python_repl_tool import PythonReplTool
        fresh = PythonReplTool()
        fresh._run("x = 1")
        assert fresh._repl is not None


# ──────────────────────────────────────────────────────────────────────────────
# ReadFileTool
# ──────────────────────────────────────────────────────────────────────────────

class TestReadFileTool:
    def setup_method(self, method, tmp_path=None):
        from tools.read_file_tool import ReadFileTool
        self.root = Path(__file__).parent.parent
        self.tool = ReadFileTool(root_dir=str(self.root))

    def test_read_existing_file(self):
        out = self.tool._run("memory/MEMORY.md")
        assert "[ERROR]" not in out

    def test_read_skill_file(self):
        out = self.tool._run("skills/get_weather/SKILL.md")
        assert "weather" in out.lower()

    def test_file_not_found(self):
        out = self.tool._run("nonexistent/file.txt")
        assert "[ERROR]" in out and "not found" in out.lower()

    def test_path_traversal_blocked(self):
        out = self.tool._run("../../../etc/passwd")
        assert "[BLOCKED]" in out

    def test_path_traversal_double_dot(self):
        out = self.tool._run("memory/../../etc/passwd")
        assert "[BLOCKED]" in out

    def test_output_cap(self, tmp_path):
        # Write a large file inside root_dir
        from tools.read_file_tool import ReadFileTool, _MAX_OUTPUT
        big_file = self.root / "memory" / "_test_large.tmp"
        try:
            big_file.write_text("x" * (_MAX_OUTPUT + 1000), encoding="utf-8")
            tool = ReadFileTool(root_dir=str(self.root))
            out = tool._run("memory/_test_large.tmp")
            assert "[output truncated]" in out
            assert len(out) <= _MAX_OUTPUT + len("\n...[output truncated]") + 10
        finally:
            if big_file.exists():
                big_file.unlink()

    def test_directory_not_a_file(self):
        out = self.tool._run("memory")
        assert "[ERROR]" in out and "not a file" in out.lower()


# ──────────────────────────────────────────────────────────────────────────────
# FetchURLTool
# ──────────────────────────────────────────────────────────────────────────────

class TestFetchURLTool:
    def setup_method(self, method):
        from tools.fetch_url_tool import FetchURLTool
        self.tool = FetchURLTool()

    def test_fetch_json_endpoint(self):
        """httpbin.org/get returns JSON with our User-Agent."""
        out = self.tool._run("https://httpbin.org/get")
        assert "[ERROR]" not in out
        assert "miniOpenClaw" in out or "user-agent" in out.lower()

    def test_fetch_html_converted_to_markdown(self):
        """HTML content should be converted to plain Markdown text."""
        html = "<html><head><title>Test Page</title></head><body><h1>Hello World</h1><p>Some text.</p></body></html>"
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        with patch("tools.fetch_url_tool.httpx.Client") as MockClient:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(return_value=mock_resp)
            MockClient.return_value = ctx

            out = self.tool._run("https://fake.url/page")
            assert "[ERROR]" not in out
            assert "Hello World" in out

    def test_fetch_invalid_url_scheme(self):
        out = self.tool._run("ftp://invalid.scheme")
        assert "[ERROR]" in out

    def test_fetch_connection_refused(self):
        out = self.tool._run("http://127.0.0.1:19999/nonexistent")
        assert "[ERROR]" in out

    def test_output_cap(self):
        """A large page should be truncated."""
        big_text = "y" * 10000
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/plain"}
        mock_resp.text = big_text
        mock_resp.raise_for_status = MagicMock()

        with patch("tools.fetch_url_tool.httpx.Client") as MockClient:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(return_value=mock_resp)
            MockClient.return_value = ctx

            out = self.tool._run("https://fake.url/big")
            assert "[output truncated]" in out

    def test_404_returns_error(self):
        import httpx
        with patch("tools.fetch_url_tool.httpx.Client") as MockClient:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            error = httpx.HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock(
                    status_code=404, reason_phrase="Not Found"
                )
            )
            ctx.get = MagicMock(side_effect=error)
            MockClient.return_value = ctx

            out = self.tool._run("https://fake.url/missing")
            assert "[ERROR]" in out and "404" in out

    def test_timeout_returns_error(self):
        import httpx
        with patch("tools.fetch_url_tool.httpx.Client") as MockClient:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(side_effect=httpx.TimeoutException("timeout"))
            MockClient.return_value = ctx

            out = self.tool._run("https://fake.url/slow")
            assert "[ERROR]" in out and "timed out" in out.lower()


# ──────────────────────────────────────────────────────────────────────────────
# SearchKnowledgeBaseTool
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchKnowledgeBaseTool:
    def test_empty_knowledge_dir(self, tmp_path):
        from tools.search_knowledge_tool import SearchKnowledgeBaseTool
        tool = SearchKnowledgeBaseTool(
            knowledge_dir=str(tmp_path / "knowledge"),
            storage_dir=str(tmp_path / "storage"),
        )
        out = tool._run("anything")
        assert "empty" in out.lower() or "could not be loaded" in out.lower()

    def test_nonexistent_knowledge_dir(self, tmp_path):
        from tools.search_knowledge_tool import SearchKnowledgeBaseTool
        tool = SearchKnowledgeBaseTool(
            knowledge_dir=str(tmp_path / "no_such_dir"),
            storage_dir=str(tmp_path / "storage"),
        )
        out = tool._run("query")
        assert "empty" in out.lower() or "could not be loaded" in out.lower()

    def test_built_flag_set_after_first_call(self, tmp_path):
        from tools.search_knowledge_tool import SearchKnowledgeBaseTool
        tool = SearchKnowledgeBaseTool(
            knowledge_dir=str(tmp_path / "knowledge"),
            storage_dir=str(tmp_path / "storage"),
        )
        assert tool._built is False
        tool._run("test query")
        assert tool._built is True

    def test_tool_name_and_description(self):
        from tools.search_knowledge_tool import SearchKnowledgeBaseTool
        tool = SearchKnowledgeBaseTool(knowledge_dir="", storage_dir="")
        assert tool.name == "search_knowledge_base"
        assert "knowledge" in tool.description.lower()
