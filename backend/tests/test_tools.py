"""
Tests for all 5 core tools.
No LLM or embedding API keys required.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _tool_summary(result):
    return result[0] if isinstance(result, tuple) else result


def _tool_contract(result):
    return result[1] if isinstance(result, tuple) else None


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
        out = self.tool._run("yes x | head -c 10000")
        assert len(out) <= 5001 + len("\n...[output truncated]")
        assert "[output truncated]" in out

    def test_nonexistent_command(self):
        out = self.tool._run("nonexistent_binary_xyz_abc_123 2>&1 || true")
        assert out  # shell error message

    def test_env_variable(self):
        out = self.tool._run("echo $HOME")
        assert out  # HOME is set in any normal environment

    def test_private_key_read_blocked(self):
        out = self.tool._run("cat id_rsa")
        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        (tmp_path / "memory" / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("cat memory/.env.local")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_python_subprocess(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        (tmp_path / "memory" / ".env.term-probe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("python3 -c \"print(open('memory/.env.term-probe').read())\"")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_glob_expansion(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.globprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("cat .en[v].globprobe")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_shell_local_variable(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.varprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("secret=.env.varprobe; cat $secret")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_command_substitution(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.cmdsubsplit").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("cat $(printf '%s%s' .en v.cmdsubsplit)")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_command_substitution_with_shell_vars(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.cmdsubsplit2").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("a=.en; b=v.cmdsubsplit2; cat $(printf '%s%s' \"$a\" \"$b\")")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_xargs_pipeline(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.xargsprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("printf '%s%s' .en v.xargsprobe | xargs cat")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_while_read_pipeline(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.readloop").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("printf '%s%s\\n' .en v.readloop | while read p; do cat \"$p\"; done")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_process_substitution(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.procsub").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("sh <(printf '%s%s%s' 'cat ' .en v.procsub)")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_positional_parameters(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.positional").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("set -- .en v.positional; cat \"$1$2\"")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_for_loop_variables(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.loopprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("for a in .en; do for b in v.loopprobe; do cat \"$a$b\"; done; done")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_declare_assignment(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.declareprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("declare a=.en b=v.declareprobe; cat \"$a$b\"")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_printf_v_assignment(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.printfprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("printf -v p '%s%s' .en v.printfprobe; cat \"$p\"")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_array_assignment(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.arrayprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("parts=(.en v.arrayprobe); cat \"${parts[0]}${parts[1]}\"")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_sourcing(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".envsourceprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(". ./.envsourceprobe; echo \"$SECRET\"")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_env_fed_child_shell(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.envchild").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("env a=.en b=v.envchild sh -c 'cat \"$a$b\"'")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_inline_child_shell(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.inlinechild").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("sh -c 'a=.en; b=v.inlinechild; cat \"$a$b\"'")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_python_nested_child_shell(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.pychild").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(
            "python3 -c 'import os,subprocess; "
            "os.environ[\"A\"]=\".en\"; "
            "os.environ[\"B\"]=\"v.pychild\"; "
            "print(subprocess.check_output([\"/bin/sh\",\"-lc\",\"cat \\\"$A$B\\\"\"]).decode())'"
        )

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_variable_hidden_child_shell(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.varshell").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run('s=sh; a=.en; b=v.varshell; "$s" -c "cat \\"$a$b\\""')

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_env_shell_variable_child_shell(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.shellenv").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run('SHELL=/bin/sh; a=.en; b=v.shellenv; "$SHELL" -c "cat \\"$a$b\\""')

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_python_variable_hidden_child_shell(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.pyvarsh").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(
            'python3 -c "s=\'sh\'; import os; a=\'.en\'; b=\'v.pyvarsh\'; '
            'os.system(f\'{s} -c \\"cat \\\\\\"{a}{b}\\\\\\"\\"\')"'
        )

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_python_heredoc_subprocess(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.heredocsub").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(
            "python3 <<'PYCODE'\n"
            "import subprocess\n"
            "s='sh'\n"
            "a='.en'\n"
            "b='v.heredocsub'\n"
            "print(subprocess.check_output([s,'-lc',f'cat \\\"{a}{b}\\\"']).decode())\n"
            "PYCODE"
        )

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_python_script_file(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.filescript").write_text("SECRET=1\n", encoding="utf-8")
        (tmp_path / "reader.py").write_text(
            "import subprocess\n"
            "s='sh'\n"
            "a='.en'\n"
            "b='v.filescript'\n"
            "print(subprocess.check_output([s, '-lc', f'cat \\\"{a}{b}\\\"']).decode())\n",
            encoding="utf-8",
        )
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("python3 reader.py")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_nested_shell_script_file(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.shellscript").write_text("SECRET=1\n", encoding="utf-8")
        (tmp_path / "reader.sh").write_text("cat .env.shellscript\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("sh reader.sh")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_perl_interpreter(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.perlprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(
            "perl -e 'my $p = \".en\" . \"v.perlprobe\"; "
            "open my $fh, \"<\", $p or exit 1; my $line = <$fh>; print $line'"
        )

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_awk_interpreter(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.awkprobe").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(
            "awk 'BEGIN { p=\".en\" \"v.awkprobe\"; getline line < p; print line }'"
        )

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_make_recipe_launcher(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.makeprobe").write_text("SECRET=1\n", encoding="utf-8")
        (tmp_path / "Makefile").write_text("leak:\n\tcat .env.makeprobe\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("make -f Makefile leak")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_npm_run_wrapper(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.npmprobe").write_text("SECRET=1\n", encoding="utf-8")
        (tmp_path / "package.json").write_text(
            '{"name":"probe","scripts":{"leak":"cat .env.npmprobe"}}\n',
            encoding="utf-8",
        )
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run("npm run leak")

        assert "[BLOCKED]" in out

    def test_env_variant_read_blocked_via_find_exec_nested_launcher(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        (tmp_path / ".env.findexec").write_text("SECRET=1\n", encoding="utf-8")
        tool = TerminalTool(base_dir=str(tmp_path))

        out = tool._run(
            "find . -maxdepth 0 -exec perl -e "
            "\"my $p = '.en' . 'v.findexec'; open my $fh, '<', $p or exit 1; my $line = <$fh>; print $line\" \\;"
        )

        assert "[BLOCKED]" in out

    def test_policy_can_disable_terminal(self, tmp_path):
        from tools.terminal_tool import TerminalTool

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            '{"production_hardening": {"tools": {"terminal_enabled": false}}}',
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            tool = TerminalTool(base_dir=str(self.base))
            out = tool._run("echo hello_world")

        assert "[BLOCKED]" in out


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

    def test_persistence_isolated_by_policy_session_id(self):
        from tools.policy import tool_policy_context
        from tools.policy_types import ToolPolicyExecutionContext

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-a")):
            self.tool._run("x = 42")

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-b")):
            out_other = self.tool._run("print(globals().get('x', 'missing'))")

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-a")):
            out_same = self.tool._run("print(x)")

        assert "missing" in out_other
        assert "42" in out_same

    def test_clear_session_state_resets_only_target_session(self):
        from tools.policy import tool_policy_context
        from tools.policy_types import ToolPolicyExecutionContext

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-a")):
            self.tool._run("marker = 'session-a'")

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-b")):
            self.tool._run("marker = 'session-b'")

        self.tool.clear_session_state("session-a")

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-a")):
            out_cleared = self.tool._run("print(globals().get('marker', 'missing'))")

        with tool_policy_context(ToolPolicyExecutionContext(session_id="session-b")):
            out_preserved = self.tool._run("print(marker)")

        assert "missing" in out_cleared
        assert "session-b" in out_preserved

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

    def test_open_private_key_file_blocked(self):
        out = self.tool._run("open('/tmp/id_rsa').read()")
        assert "[BLOCKED]" in out

    def test_open_env_variant_file_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.local"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(f"print(open({str(env_path)!r}).read())")

        assert "[BLOCKED]" in out

    def test_pathlib_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.review-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "from pathlib import Path\n"
            f"print(Path({str(env_path)!r}).read_text())"
        )

        assert "[BLOCKED]" in out

    def test_pathlib_variable_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.variable-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "from pathlib import Path\n"
            f"secret_path = Path({str(env_path)!r})\n"
            "print(secret_path.read_text())"
        )

        assert "[BLOCKED]" in out

    def test_pathlib_persistent_variable_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.persistent-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        tool._run(
            "from pathlib import Path\n"
            f"secret_path = Path({str(env_path)!r})"
        )
        out = tool._run("print(secret_path.read_text())")

        assert "[BLOCKED]" in out

    def test_os_open_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.os-open-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import os\n"
            f"fd = os.open({str(env_path)!r}, os.O_RDONLY)\n"
            "print(os.read(fd, 32).decode())"
        )

        assert "[BLOCKED]" in out

    def test_importlib_os_open_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.importlib-os-open-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import importlib\n"
            "os_module = importlib.import_module('os')\n"
            f"fd = os_module.open({str(env_path)!r}, os_module.O_RDONLY)\n"
            "print(os_module.read(fd, 32).decode())"
        )

        assert "[BLOCKED]" in out

    def test_imported_builtins_open_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.builtins-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import builtins\n"
            f"print(builtins.open({str(env_path)!r}).read())"
        )

        assert "[BLOCKED]" in out

    def test_sys_modules_os_open_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.sysmodules-os-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import sys\n"
            "import os\n"
            f"fd = sys.modules['os'].open({str(env_path)!r}, os.O_RDONLY)\n"
            "print(sys.modules['os'].read(fd, 32).decode())"
        )

        assert "[BLOCKED]" in out

    def test_sys_modules_builtins_open_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.sysmodules-builtins-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import sys\n"
            f"print(sys.modules['builtins'].open({str(env_path)!r}).read())"
        )

        assert "[BLOCKED]" in out

    def test_posix_open_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.posix-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import posix\n"
            f"fd = posix.open({str(env_path)!r}, posix.O_RDONLY)\n"
            "print(posix.read(fd, 32).decode())"
        )

        assert "[BLOCKED]" in out

    def test__io_fileio_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.raw-io-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import _io\n"
            f"print(_io.FileIO({str(env_path)!r}, 'r').read().decode())"
        )

        assert "[BLOCKED]" in out

    def test_ctypes_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.ctypes-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import ctypes\n"
            "libc = ctypes.CDLL(None)\n"
            f"fd = libc.open({str(env_path)!r}.encode(), 0)\n"
            "buf = ctypes.create_string_buffer(32)\n"
            "libc.read(fd, buf, 32)\n"
            "print(buf.value.decode())"
        )

        assert "[BLOCKED]" in out

    def test_subprocess_secret_read_blocked_via_importlib_alias(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.subprocess-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import importlib\n"
            "sp = importlib.import_module('subprocess')\n"
            f"print(sp.check_output(['cat', {str(env_path)!r}]).decode())"
        )

        assert "[BLOCKED]" in out

    def test_posix_spawn_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.posix-spawn-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import os\n"
            f"pid = os.posix_spawn('/bin/sh', ['sh', '-lc', 'cat {str(env_path)}'], os.environ.copy())\n"
            "print(pid)"
        )

        assert "[BLOCKED]" in out

    def test_asyncio_subprocess_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.asyncio-subprocess-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import asyncio\n"
            "from asyncio.subprocess import PIPE, create_subprocess_exec\n"
            "async def main():\n"
            f"    proc = await create_subprocess_exec('cat', {str(env_path)!r}, stdout=PIPE)\n"
            "    stdout, _ = await proc.communicate()\n"
            "    print(stdout.decode())\n"
            "asyncio.run(main())"
        )

        assert "[BLOCKED]" in out

    def test_pty_spawn_secret_read_blocked(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        env_path = tmp_path / ".env.pty-probe"
        env_path.write_text("SECRET=1\n", encoding="utf-8")
        tool = PythonReplTool()

        out = tool._run(
            "import pty\n"
            f"pty.spawn(['cat', {str(env_path)!r}])"
        )

        assert "[BLOCKED]" in out

    def test_policy_can_disable_python_repl(self, tmp_path):
        from tools.python_repl_tool import PythonReplTool

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            '{"production_hardening": {"tools": {"python_repl_enabled": false}}}',
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            tool = PythonReplTool(base_dir=str(tmp_path))
            out = tool._run("print(2 + 2)")

        assert "[BLOCKED]" in out


class TestToolRegistry:
    def test_tool_manifest_entries_are_typed_and_unique(self, tmp_path):
        from tools import get_all_tools, get_tool_manifest_entries

        (tmp_path / "knowledge").mkdir()
        (tmp_path / "storage").mkdir()

        tools = get_all_tools(tmp_path)
        manifests = get_tool_manifest_entries(tmp_path)

        assert len(manifests) == len(tools)
        assert len({manifest.name for manifest in manifests}) == len(manifests)

    def test_tool_manifest_exposes_policy_and_contract_metadata(self, tmp_path):
        from tools import get_tool_manifest_entries

        (tmp_path / "knowledge").mkdir()
        (tmp_path / "storage").mkdir()

        manifests = {manifest.name: manifest for manifest in get_tool_manifest_entries(tmp_path)}

        assert manifests["read_file"].access_scope == "inspection"
        assert manifests["terminal"].access_scope == "execution"
        assert manifests["evidence_review"].evidence_requirement == "required"
        assert manifests["plan_agent"].access_scope == "inspection"
        assert manifests["verification_agent"].access_scope == "inspection"
        assert "slurm_tool" not in manifests
        assert manifests["read_file"].args_schema is not None
        assert manifests["read_file"].read_only is True
        assert manifests["read_file"].planner_exposed is True
        assert manifests["read_file"].verifier_exposed is True
        assert manifests["read_file"].interrupt_behavior == "restartable"
        assert manifests["read_file"].tool_validates_input is True
        assert manifests["read_file"].activity_summary_hint is not None
        assert manifests["read_file"].result_summary_hint is not None
        assert manifests["write_file"].destructive is True
        assert manifests["write_file"].interrupt_behavior == "avoid_interrupting"

    def test_runtime_helper_agent_tool_exposure_uses_policy_wrapped_manifests(self, tmp_path):
        from runtime.helper_agent_runner import build_tool_catalog, filter_tools_by_exposure
        from tools import get_runtime_tools

        (tmp_path / "knowledge").mkdir()
        (tmp_path / "storage").mkdir()

        runtime_tools = get_runtime_tools(tmp_path)
        planner_tools = {tool.name for tool in filter_tools_by_exposure(runtime_tools, "planner")}
        verifier_tools = {tool.name for tool in filter_tools_by_exposure(runtime_tools, "verifier")}
        planner_catalog = {
            entry["name"]: entry for entry in build_tool_catalog(filter_tools_by_exposure(runtime_tools, "planner"))
        }

        assert "read_file" in planner_tools
        assert "fetch_url" in planner_tools
        assert "terminal" not in planner_tools
        assert "write_file" not in planner_tools
        assert "plan_agent" not in planner_tools
        assert "verification_agent" not in planner_tools

        assert "read_file" in verifier_tools
        assert "evidence_review" in verifier_tools
        assert "terminal" not in verifier_tools
        assert "write_file" not in verifier_tools
        assert planner_catalog["read_file"]["interrupt_behavior"] == "restartable"
        assert planner_catalog["read_file"]["tool_validates_input"] is True
        assert planner_catalog["read_file"]["activity_summary_hint"]
        assert planner_catalog["read_file"]["result_summary_hint"]
        assert planner_catalog["read_file"]["planner_exposed"] is True
        assert planner_catalog["read_file"]["verifier_exposed"] is True


class TestHelperAgentTools:
    @pytest.mark.asyncio
    async def test_plan_agent_returns_structured_contract(self, tmp_path):
        from graph.agent import agent_manager
        from runtime.subagent import SubAgentArtifact
        from tools.plan_agent_tool import PlanAgentTool

        original_planner_llm = agent_manager.planner_llm
        original_tools = agent_manager.tools
        original_base_dir = agent_manager.base_dir
        agent_manager.planner_llm = object()
        agent_manager.tools = [type("DummyTool", (), {"name": "read_file"})()]
        agent_manager.base_dir = tmp_path

        try:
            tool = PlanAgentTool()
            fake_artifact = SubAgentArtifact(
                run_id="run-20260101T000000Z-deadbeef",
                name="plan_agent",
                status="ok",
                response_text=(
                    '{"goal":"Investigate BRCA1 expression","assumptions":[],"constraints":[],'
                    '"steps":[{"step_id":"step-1","intent":"Read the relevant file","allowed_tools":["read_file"],'
                    '"preferred_tool_order":["read_file"],"exit_criteria":"Understand the current implementation"}],'
                    '"success_criteria":["The implementation path is understood"],'
                    '"verification_checks":["Confirm the selected file contains the entry point"]}'
                ),
                tool_trace=({"tool": "read_file", "input": "backend/api/chat.py"},),
                verdict=None,
                tokens_used=42,
                steps_used=1,
                relative_path="artifacts/subagent/2026-01-01/run-20260101T000000Z-deadbeef/subagent_run.json",
                absolute_path=str(tmp_path / "subagent_run.json"),
                payload={},
            )
            with patch(
                "tools.plan_agent_tool.role_model_is_configured",
                return_value=True,
            ), patch(
                "tools.plan_agent_tool.run_subagent",
                new=AsyncMock(return_value=fake_artifact),
            ):
                summary, contract = await tool._arun("Investigate BRCA1 expression handling")
        finally:
            agent_manager.planner_llm = original_planner_llm
            agent_manager.tools = original_tools
            agent_manager.base_dir = original_base_dir

        assert "Planner produced 1 step" in summary
        assert contract["tool_name"] == "plan_agent"
        assert contract["status"] == "success"
        assert contract["structured_payload"]["plan"]["steps"][0]["preferred_tool_order"] == ["read_file"]
        assert contract["structured_payload"]["tool_trace"][0]["tool"] == "read_file"
        assert contract["structured_payload"]["subagent_run"]["run_id"].startswith("run-")
        assert contract["metadata"]["subagent_artifact_path"].startswith("artifacts/subagent/")

    @pytest.mark.asyncio
    async def test_verification_agent_returns_structured_contract(self, tmp_path):
        from graph.agent import agent_manager
        from runtime.subagent import SubAgentArtifact
        from tools.verification_agent_tool import VerificationAgentTool

        original_verifier_llm = agent_manager.verifier_llm
        original_tools = agent_manager.tools
        original_base_dir = agent_manager.base_dir
        agent_manager.verifier_llm = object()
        agent_manager.tools = [type("DummyTool", (), {"name": "read_file"})()]
        agent_manager.base_dir = tmp_path

        try:
            tool = VerificationAgentTool()
            fake_artifact = SubAgentArtifact(
                run_id="run-20260101T000000Z-cafebabe",
                name="verification_agent",
                status="ok",
                response_text=(
                    '{"verdict":"repair_required","summary":"The answer lacks evidence grounding.",'
                    '"checks":[{"name":"evidence-grounding","status":"fail","note":"No cited evidence review found."}],'
                    '"issues":["The answer overstates certainty without evidence."],'
                    '"repair_instructions":["Run evidence review before finalizing the answer."]}'
                ),
                tool_trace=(),
                verdict=None,
                tokens_used=120,
                steps_used=0,
                relative_path="artifacts/subagent/2026-01-01/run-20260101T000000Z-cafebabe/subagent_run.json",
                absolute_path=str(tmp_path / "subagent_run.json"),
                payload={},
            )
            run_agent = AsyncMock(return_value=fake_artifact)
            with patch(
                "tools.verification_agent_tool.role_model_is_configured",
                return_value=True,
            ), patch(
                "tools.verification_agent_tool.run_subagent",
                new=run_agent,
            ):
                summary, contract = await tool._arun(
                    "Summarize BRCA1 evidence",
                    "BRCA1 definitely increases under condition X.",
                )
        finally:
            agent_manager.verifier_llm = original_verifier_llm
            agent_manager.tools = original_tools
            agent_manager.base_dir = original_base_dir

        assert summary.startswith("Verifier verdict: repair_required.")
        assert contract["tool_name"] == "verification_agent"
        assert contract["structured_payload"]["verification"]["verdict"] == "repair_required"
        assert contract["metadata"]["verdict"] == "repair_required"
        assert contract["structured_payload"]["subagent_run"]["run_id"].startswith("run-")
        assert contract["metadata"]["subagent_artifact_path"].startswith("artifacts/subagent/")
        prompt = run_agent.await_args.kwargs["user_prompt"]
        assert 'Use "pass" when the draft is good enough to send as-is.' in prompt
        assert "Do not use repair_required for optional improvements" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# ReadFileTool
# ──────────────────────────────────────────────────────────────────────────────

class TestReadFileTool:
    def setup_method(self, method, tmp_path=None):
        from tools.read_file_tool import ReadFileTool
        self.root = Path(__file__).parent.parent
        self.tool = ReadFileTool(root_dir=str(self.root))

    def test_read_existing_file(self):
        out = _tool_summary(self.tool._run("memory/MEMORY.md"))
        assert "[ERROR]" not in out

    def test_read_skill_file(self):
        out = _tool_summary(self.tool._run("skills/get_weather/SKILL.md"))
        assert "weather" in out.lower()

    def test_file_not_found(self):
        out = _tool_summary(self.tool._run("nonexistent/file.txt"))
        assert "[ERROR]" in out and "not found" in out.lower()

    def test_path_traversal_blocked(self):
        out = _tool_summary(self.tool._run("../../../etc/passwd"))
        assert "[BLOCKED]" in out

    def test_path_traversal_double_dot(self):
        out = _tool_summary(self.tool._run("memory/../../etc/passwd"))
        assert "[BLOCKED]" in out

    def test_output_cap(self, tmp_path):
        # Write a large file inside root_dir
        from tools.read_file_tool import ReadFileTool, _MAX_OUTPUT
        big_file = self.root / "memory" / "_test_large.tmp"
        try:
            big_file.write_text("x" * (_MAX_OUTPUT + 1000), encoding="utf-8")
            tool = ReadFileTool(root_dir=str(self.root))
            out = _tool_summary(tool._run("memory/_test_large.tmp"))
            assert "[output truncated]" in out
            assert len(out) <= _MAX_OUTPUT + len("\n...[output truncated]") + 10
        finally:
            if big_file.exists():
                big_file.unlink()

    def test_directory_not_a_file(self):
        out = _tool_summary(self.tool._run("memory"))
        assert "[ERROR]" in out and "not a file" in out.lower()

    def test_read_file_returns_structured_contract(self):
        result = self.tool._run("memory/MEMORY.md")
        contract = _tool_contract(result)
        assert contract is not None
        assert contract["tool_name"] == "read_file"
        assert contract["status"] == "success"
        assert contract["artifact_refs"][0]["path"].endswith("memory/MEMORY.md")

    def test_secret_file_blocked(self):
        secret_path = self.root / "memory" / ".env"
        try:
            secret_path.write_text("SECRET=1\n", encoding="utf-8")
            out = _tool_summary(self.tool._run("memory/.env"))
            assert "[BLOCKED]" in out
        finally:
            if secret_path.exists():
                secret_path.unlink()


# ──────────────────────────────────────────────────────────────────────────────
# FetchURLTool
# ──────────────────────────────────────────────────────────────────────────────

class TestFetchURLTool:
    def setup_method(self, method):
        from tools.fetch_url_tool import FetchURLTool
        self.tool = FetchURLTool()

    def test_fetch_json_endpoint(self):
        """JSON responses should be returned without an error."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = '{"ok": true, "user-agent": "BioAPEX"}'
        mock_resp.raise_for_status = MagicMock()

        with patch("tools.fetch_url_tool.httpx.Client") as MockClient:
            ctx = MagicMock()
            ctx.__enter__ = MagicMock(return_value=ctx)
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.get = MagicMock(return_value=mock_resp)
            MockClient.return_value = ctx

            out = self.tool._run("https://httpbin.org/get")
        assert "[ERROR]" not in out
        assert "BioAPEX" in out or "user-agent" in out.lower()

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
        assert "[BLOCKED]" in out

    def test_fetch_connection_refused(self):
        out = self.tool._run("http://127.0.0.1:19999/nonexistent")
        assert "[BLOCKED]" in out

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
        out = _tool_summary(tool._run("anything"))
        assert "empty" in out.lower() or "could not be loaded" in out.lower()

    def test_nonexistent_knowledge_dir(self, tmp_path):
        from tools.search_knowledge_tool import SearchKnowledgeBaseTool
        tool = SearchKnowledgeBaseTool(
            knowledge_dir=str(tmp_path / "no_such_dir"),
            storage_dir=str(tmp_path / "storage"),
        )
        out = _tool_summary(tool._run("query"))
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

    def test_empty_knowledge_returns_structured_contract(self, tmp_path):
        from tools.search_knowledge_tool import SearchKnowledgeBaseTool

        tool = SearchKnowledgeBaseTool(
            knowledge_dir=str(tmp_path / "knowledge"),
            storage_dir=str(tmp_path / "storage"),
        )
        result = tool._run("anything")
        contract = _tool_contract(result)

        assert contract is not None
        assert contract["tool_name"] == "search_knowledge_base"
        assert contract["outcome"] == "success_empty"


# ──────────────────────────────────────────────────────────────────────────────
# WriteFileTool
# ──────────────────────────────────────────────────────────────────────────────

class TestWriteFileTool:
    def test_write_allowed_path(self, tmp_path):
        from tools.write_file_tool import WriteFileTool

        for relpath in ("memory", "skills", "knowledge"):
            (tmp_path / relpath).mkdir(parents=True, exist_ok=True)

        tool = WriteFileTool(root_dir=str(tmp_path))
        result = tool._run("memory/MEMORY.md", "# Updated\n")
        contract = _tool_contract(result)

        assert contract is not None
        assert contract["status"] == "success"
        assert (tmp_path / "memory" / "MEMORY.md").read_text(encoding="utf-8") == "# Updated\n"

    def test_nested_memory_write_rebuilds_memory_index(self, tmp_path):
        from graph.agent import agent_manager
        from tools.write_file_tool import WriteFileTool

        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        original_memory_indexer = agent_manager.memory_indexer
        agent_manager.memory_indexer = MagicMock()

        try:
            tool = WriteFileTool(root_dir=str(tmp_path))
            result = tool._run("memory/project/notes.md", "# Updated\n")
            contract = _tool_contract(result)
        finally:
            rebuilt = agent_manager.memory_indexer._maybe_rebuild.call_count
            agent_manager.memory_indexer = original_memory_indexer

        assert contract is not None
        assert contract["status"] == "success"
        assert contract["structured_payload"]["memory_index_rebuilt"] is True
        assert rebuilt == 1

    def test_invalid_typed_memory_frontmatter_is_rejected(self, tmp_path):
        from tools.write_file_tool import WriteFileTool

        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        tool = WriteFileTool(root_dir=str(tmp_path))

        result = tool._run(
            "memory/project/invalid.md",
            (
                "---\n"
                "type: unsupported_type\n"
                "name: Invalid note\n"
                "description: This should fail validation.\n"
                "---\n"
                "# Body\nNo write should happen.\n"
            ),
        )
        contract = _tool_contract(result)

        assert contract is not None
        assert contract["outcome"] == "invalid_input"
        assert not (tmp_path / "memory" / "project" / "invalid.md").exists()

    def test_write_secret_file_blocked(self, tmp_path):
        from tools.write_file_tool import WriteFileTool

        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        tool = WriteFileTool(root_dir=str(tmp_path))

        out = _tool_summary(tool._run("memory/.env", "SECRET=1\n"))
        assert "[BLOCKED]" in out
        assert not (tmp_path / "memory" / ".env").exists()

    def test_policy_can_disable_write_file(self, tmp_path):
        from tools.write_file_tool import WriteFileTool

        (tmp_path / "memory").mkdir(parents=True, exist_ok=True)
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            '{"production_hardening": {"tools": {"write_file_enabled": false}}}',
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            tool = WriteFileTool(root_dir=str(tmp_path))
            out = _tool_summary(tool._run("memory/MEMORY.md", "# Updated\n"))

        assert "[BLOCKED]" in out


# ──────────────────────────────────────────────────────────────────────────────
# SlurmTool
# ──────────────────────────────────────────────────────────────────────────────

class TestSlurmToolPolicy:
    def test_policy_can_disable_legacy_commands(self, tmp_path):
        from tools.slurm_tool import SlurmTool

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            '{"production_hardening": {"tools": {"slurm_legacy_commands_enabled": false}}}',
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            tool = SlurmTool(base_dir=str(tmp_path))
            result = tool._run(command="sinfo")

        contract = _tool_contract(result)
        assert contract is not None
        assert contract["outcome"] == "blocked"

    def test_policy_can_disable_slurm_tool(self, tmp_path):
        from tools.slurm_tool import SlurmTool

        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(
            '{"production_hardening": {"tools": {"slurm_enabled": false}}}',
            encoding="utf-8",
        )

        with patch("config._CONFIG_FILE", cfg_file):
            tool = SlurmTool(base_dir=str(tmp_path))
            result = tool._run(command="sinfo")

        contract = _tool_contract(result)
        assert contract is not None
        assert contract["outcome"] == "blocked"
