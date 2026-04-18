# Claude Code Source Backend Comparison

## Date

2026-04-02

## Question

What should BioAPEX learn from `ponponon/claude_code_src` on the backend/runtime side, and are there backend flaws in BioAPEX that need attention before we copy any of its patterns?

## Recommendation

BioAPEX should copy the reference repo's separation style, not its whole implementation.

Strong patterns worth borrowing:

- a narrow bootstrap/entrypoint layer
- a single conversation runtime that is separate from transport and UI
- a richer tool contract with explicit permission, mutability, and safety metadata
- a unified command/skill/plugin registration boundary
- typed sandbox and permission configuration

Patterns not worth copying literally:

- the CLI/TUI-heavy product surface
- its feature-flag sprawl
- very large orchestration files

## External Truth

Primary-source inspection of `ponponon/claude_code_src` on 2026-04-02 showed:

- `src/entrypoints/cli.tsx` is a thin bootstrap with fast paths and deferred imports.
- `src/commands.ts` centralizes built-in commands plus dynamic skill/plugin loading.
- `src/Tool.ts` defines a much richer tool contract than BioAPEX currently has, including read-only/destructive hints, validation, permission checks, interrupt behavior, rendering hooks, and deferred loading.
- `src/QueryEngine.ts` owns conversation lifecycle and state outside the entrypoint layer.
- `src/entrypoints/mcp.ts` reuses the same core tool abstractions to expose tools through MCP.
- `src/entrypoints/sandboxTypes.ts` defines typed sandbox schemas for network/filesystem policy.

## Repo Truth

BioAPEX already has good building blocks:

- `backend/app.py` gives us a clean FastAPI composition root.
- `backend/api/` gives us explicit transport boundaries.
- `backend/graph/agent.py` owns the LLM + tool runtime.
- `backend/tools/registry.py` and `backend/tools/policy.py` already introduce manifest/policy concepts.
- `backend/graph/session_manager.py` already persists richer typed session blocks than a plain chat log.

The main gap is not that BioAPEX lacks layers. It is that our runtime and safety contracts are still thinner and leakier than the reference repo's:

- too much request orchestration lives directly inside `backend/api/chat.py`
- our tool contract is mostly wrapper metadata rather than per-tool capability contracts
- mutable tool instances are created globally and reused
- production-hardening defaults are still development-first

## Findings

### 1. High: Python REPL state is shared across sessions

Evidence:

- `backend/graph/agent.py` initializes `self.tools` once in the singleton `AgentManager`.
- `backend/tools/__init__.py` constructs one `PythonReplTool` instance inside that shared tool list.
- `backend/tools/python_repl_tool.py` stores `_repl` as persistent private state and lazily initializes it once.

Why this matters:

- The code says the interpreter is persistent "within a session", but the actual lifetime is the process-global tool instance.
- Variables, imports, and cached objects can leak from one chat session into another.
- Concurrent requests can race against the same in-memory REPL state.

Recommendation:

- Move Python REPL state behind a per-session store keyed by `session_id`, or disable persistent REPL state entirely.

### 2. Medium: hosted deployment can become unsafe if dev defaults are carried forward

Evidence:

- `backend/app.py` documents `uvicorn app:app --port 8002 --host 0.0.0.0 --reload`.
- `backend/hardening.py` defaults `allow_loopback_without_auth=True`.
- `backend/hardening.py` also defaults `terminal_enabled=True`, `python_repl_enabled=True`, `write_file_enabled=True`, and connector/file mutation surfaces enabled.
- `backend/access_control.py` treats loopback as sufficient access when that policy flag is enabled.

Why this matters:

- The codebase documents the right production posture in `backend/docs/production-hardening.md`, but the runtime defaults remain permissive.
- In a reverse-proxy or shared-host deployment, loopback-based trust is easy to misunderstand.
- The dangerous tools are the exact ones that should fail closed first.

Recommendation:

- Keep these defaults for local development only.
- Add an explicit hosted profile or environment gate that disables loopback trust and high-risk tools by default.

### 3. Medium: tool policy is still thinner than the reference runtime

Evidence:

- `backend/tools/registry.py` uses coarse override metadata such as `access_scope`, `evidence_requirement`, and `compliance_preflight_required`.
- `backend/tools/policy.py` evaluates those coarse flags at runtime.
- `backend/config.py` defaults `tool_policy.allow_without_context=True`.
- By contrast, `claude_code_src`'s `src/Tool.ts` pushes more safety semantics into the tool contract itself.

Why this matters:

- Our current layer is good for route/tool gating, but it does not express read-only vs destructive behavior, interrupt behavior, or tool-specific permission logic as first-class contract surface.
- That makes it harder to build a more trustworthy approval UI or a safer automated planner later.

Recommendation:

- Evolve BioAPEX's tool manifest toward a proper typed contract rather than continuing to grow the override table.

## What To Mimic

### Narrow bootstrap

BioAPEX should keep `backend/app.py` thin and push more runtime assembly behind explicit factories.

### Central query runtime

The reference repo's strongest backend idea is a distinct query engine. BioAPEX should move more of the turn orchestration now living in `backend/api/chat.py` into a reusable runtime class that the API layer calls.

### Rich tool contract

The reference repo treats tool safety and behavior as part of the tool interface. BioAPEX should move in that direction for:

- read-only vs mutating classification
- destructive-action classification
- permission and approval behavior
- interrupt/cancel behavior
- user-visible summaries and capability descriptions

### Reusable multi-surface runtime

`claude_code_src` can expose the same tool layer through CLI and MCP entrypoints. BioAPEX should keep nudging toward the same principle:

- one core runtime
- multiple surfaces on top of it

## What Not To Mimic

- Do not import the CLI command explosion.
- Do not import TUI-specific abstractions into the backend.
- Do not copy giant monolithic files as-is; `src/QueryEngine.ts` is useful as a boundary example, not as a size target.

## Decision

BioAPEX should learn from `claude_code_src` structurally, but the first backend action should be internal hardening:

1. fix the shared Python REPL state leak
2. introduce a safer hosted default profile
3. extract chat-turn orchestration into a dedicated runtime layer
4. expand the tool contract so safety and approval behavior are tool-native
