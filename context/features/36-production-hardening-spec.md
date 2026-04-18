# Production Hardening Spec

## Overview

Harden the system for real-world deployment once the workflow, evidence, compliance, and artifact foundations are in place. This phase should consolidate safety, permissions, authentication, sandboxing, secrets handling, test coverage, and failure recovery into a deployment-ready posture.

## Requirements

- Review all execution-capable tools and define least-privilege policies for each.
- Tighten shell, file, and job execution boundaries so workflow features do not broaden the attack surface unintentionally.
- Define authentication and authorization requirements for user actions, approvals, exports, and connector use.
- Define secrets handling for API keys, cluster credentials, and external service tokens.
- Add explicit backup and restore expectations for sessions, artifacts, and registry state.
- Define failure-recovery behavior for interrupted workflow runs, partial exports, and transient external API failures.
- Expand the automated test matrix to include:
  - security-sensitive path tests
  - compliance gate tests
  - workflow persistence tests
  - artifact validation tests
- Define a deployment checklist for local, HPC, and any future hosted environments.

## References

- @backend/api/chat.py
- @backend/api/files.py
- @backend/config.py
- @backend/tools/terminal_tool.py
- @backend/tools/python_repl_tool.py
- @backend/tools/read_file_tool.py
- @backend/tools/write_file_tool.py
- @backend/tools/slurm_tool.py
- @backend/tests/test_tools.py
- @backend/tests/test_config.py
- @context/features/07-compliance-rules-mvp-spec.md
- @context/features/31-reproducibility-drills-spec.md
- @context/features/32-audit-logging-spec.md

## Implementation Notes

- Added a shared `production_hardening` policy contract in `backend/config.py` and `backend/hardening.py` so risky tools and APIs can be disabled without changing code.
- Wired `terminal`, `python_repl`, `slurm_tool`, `write_file`, `/api/files` writes, and connector configuration/runtime routes to the shared policy with fail-closed blocked responses.
- Unified secret-like file protection across file reads/writes and execution guardrails so `.env*`, private-key, certificate, and SSH private-key paths are blocked consistently.
- Added an inspectable loopback-or-bearer `GET /api/config/production-hardening` route plus an operator-facing runbook in `backend/docs/production-hardening.md`.
- Hardened malformed `production_hardening` config handling to fail closed instead of silently re-enabling risky surfaces, and aligned `/api/tokens/files` with the shared secret-path blocking rules.
- Added loopback-or-bearer access control for `/api/chat`, `/api/files` writes, connector validation/mutation/runtime routes, and config routes, with bearer-token env-var names and explicit CORS origins carried in the typed hardening policy.
- Tightened terminal and Python REPL secret-path blocking so `.env*` variants follow the same shared rules as the file APIs and file tools.
- Expanded verification to include compliance preflight plus workflow persistence/recovery coverage instead of only the non-workflow backend slice.
- Removed the implicit admin-token fallback so remote config and connector admin routes require `admin_bearer_token_env_var` explicitly instead of accepting the execution token by omission.
- Extended the Python REPL secret-path guard to block secret-like reads through `open(...)` and `pathlib.Path(...).read_text()/read_bytes()/open()`, including variable-bound `Path` objects that persist across REPL calls.
- Closed the remaining secret-read bypasses by wrapping lower-level Python REPL file entry points (`builtins.open`, `sys.modules[...]` access to wrapped modules, `os.open`, `io.open`, `codecs.open`, and `importlib`-mediated `os` access) and by blocking literal secret-path references embedded in terminal interpreter subprocess commands.
- Extended loopback-or-bearer access control to the remaining mutating or execution-triggering routes: session create/rename/delete/title/compress, skill-registry updates, and artifact-registry rebuild.
- Added a distinct inspection access scope with `production_hardening.api.inspection_bearer_token_env_var` so remote read-only inspection routes do not remain unauthenticated and do not silently fall back to execution/admin tokens.
- Closed additional secret-read bypasses by wrapping native Python REPL modules such as `posix` and `_io`, and by checking shell-expanded glob/brace/env-var path matches in the terminal tool before execution.
- Blocked native FFI module access in the Python REPL (`ctypes`, `_ctypes`, and `cffi`) so libc-backed file reads cannot bypass the guarded Python file APIs.
- Closed the remaining child-process and shell-local expansion bypasses by blocking Python REPL process execution through `subprocess` plus `os.system`/`os.popen`/`os.exec*`/`os.spawn*`, and by teaching the terminal guard to expand simple shell-local assignments before checking secret-like paths.
- Closed the remaining process-launch and command-substitution bypasses by extending Python REPL process blocking to `os.posix_spawn*` plus `asyncio` subprocess helpers, and by refusing shell command substitution in the terminal tool because `$()`/backticks cannot be safely resolved during pre-execution secret-path checks.
- Closed the remaining imported-launcher-module bypass by extending the Python REPL runtime patching to the live import/module table during execution, so modules such as `pty` inherit blocked process APIs instead of reaching the host interpreter's real `os`/`subprocess` implementations.
- Closed the remaining terminal pipeline reconstruction bypass by refusing `xargs` in the terminal tool, because stdin-driven argument expansion cannot be safely inspected before `shell=True` execution and could reconstruct secret-like paths from non-secret-looking fragments.
- Closed the remaining shell-loop reconstruction bypass by refusing terminal commands that use `read`, `mapfile`, or `readarray` to populate shell variables from stdin, because those runtime-assigned values can reconstruct secret-like paths after the pre-execution checks have already finished.
- Closed the remaining process-substitution reconstruction bypass by refusing terminal commands that use shell process substitution (`<(...)` / `>(...)`), because those dynamic shell programs can reconstruct secret-like paths after the pre-execution checks have already finished.
- Closed the remaining dynamic-shell reconstruction bypasses by refusing terminal commands that rely on shell positional parameters, shell control flow, shell variable-declaration builtins, `printf -v`, shell arrays, braced parameter expansion, or shell sourcing, because those features can mutate or expand runtime shell state after the pre-execution checks have already finished.
- Closed the remaining nested-child-shell reconstruction bypasses by refusing terminal commands that invoke `sh -c`, `bash -c`, and equivalent child-shell script execution patterns, because those inner shell programs can reconstruct secret-like paths after the outer pre-execution checks have already finished.
- Closed the remaining variable-hidden and interpreter-assembled child-shell bypasses by refusing terminal commands that launch child shells through variable expansion like `"$SHELL" -c ...`, and by blocking `python -c` snippets that attempt to spawn subprocesses with `os.system(...)`, `os.popen(...)`, or `subprocess.*`, because those inner process launches can reconstruct secret-like paths after the outer pre-execution checks have already finished.
- Closed the remaining interpreter-fed terminal bypasses by refusing nested Python execution beyond metadata-only help/version flags, plus nested shell interpreter launches from script/stdin forms such as `python <<'PY' ...`, `python script.py`, and `sh script.sh`, because those interpreter programs cannot be inspected safely before execution and can reconstruct secret-like paths after the outer prechecks have already finished.
- Closed the remaining non-Python interpreter terminal bypasses by refusing other arbitrary-code interpreters such as `perl`, `awk`, `ruby`, `node`, `php`, `lua`, `tclsh`, `Rscript`, and `julia`, because their inline programs and script entry points can reconstruct secret-like paths after the terminal prechecks have already finished and cannot be inspected safely before execution.
- Closed the remaining file-driven terminal launcher bypasses by refusing recipe launchers such as `make`, `just`, `ninja`, `tox`, and `nox`, plus wrapper launchers such as `npm run`, `pnpm run`, `yarn run`, `bun run`, `poetry run`, `pipenv run`, and `uv run`, because those entry points can hide nested execution inside project files or wrapper subcommands that the terminal prechecks cannot inspect safely before execution.
- Closed the remaining obvious nested-launcher gap by refusing `find -exec` / `-ok` style nested execution in the terminal tool, and documented the terminal guard as defense-in-depth rather than a full shell sandbox so shared or hosted deployments continue to rely on disabling terminal access instead of exhaustive shell-language coverage.
