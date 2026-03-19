# Baseline Freeze 01

Captured on 2026-03-18 from current source, runtime config, and route-level trace capture artifacts.

## Scope

This baseline freezes the current behavior implemented in:

- `README.md`
- `backend/app.py`
- `backend/api/chat.py`
- `backend/api/files.py`
- `backend/api/sessions.py`
- `backend/api/config_api.py`
- `backend/graph/agent.py`
- `backend/graph/session_manager.py`
- `backend/graph/prompt_builder.py`
- `backend/config.py`
- `backend/tools/__init__.py`
- `backend/tools/skills_scanner.py`
- `frontend/src/lib/store.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`

The baseline uses the code as the source of truth. This matters because some older prose docs are no longer fully current. For example, `README.md` still describes a 5-tool backend, while `backend/tools/__init__.py` currently registers 11 tools.

## Current System Snapshot

- Backend entrypoint is `backend/app.py`, which configures embeddings, scans skills, initializes `AgentManager`, and tries to build the memory index during startup.
- Frontend state is centralized in `frontend/src/lib/store.tsx` and consumes backend APIs through `frontend/src/lib/api.ts`.
- Current persisted runtime config in `backend/config.json` sets `rag_mode` to `true`.
- Current local skill source is `backend/skills/`, which contains 47 `SKILL.md` files.
- There are no configured `skills.extra_dirs`.
- There is no repo-root `.agents/skills` directory in the current workspace.

## Request Path Freeze

The current chat path is:

1. The frontend `sendMessage()` action in `frontend/src/lib/store.tsx` auto-creates a session if needed, appends a user message plus an empty streaming assistant placeholder, and calls `api.streamChat(message, sessionId, callbacks)`.
2. `frontend/src/lib/api.ts` sends `POST /api/chat` with `{message, session_id, stream: true}` and parses the response as SSE by splitting on blank lines and decoding each `data:` payload as JSON.
3. `backend/api/chat.py` validates `session_id` and message length, checks whether this is the first successful assistant turn, runs auto-compression if needed, and loads agent history through `SessionManager.load_session_for_agent()`.
4. `load_session_for_agent()` merges consecutive assistant messages and prepends `compressed_context` as a synthetic `system` message when present.
5. `AgentManager.astream()` in `backend/graph/agent.py` reads `rag_mode` from config, optionally retrieves memory hits and yields a `retrieval` event, rebuilds the agent for every request with `build_system_prompt()`, and then streams LangChain/LangGraph events as typed internal events.
6. `backend/api/chat.py` translates those internal events into SSE payloads, accumulates assistant text/tool-call segments, and delays user-message persistence until either `done` or `error`.
7. On `done`, `backend/api/chat.py` saves the user message exactly once, saves each assistant segment as a separate stored message, emits a `done` SSE event with concatenated assistant text, and may asynchronously generate and persist a title for the first successful turn.
8. On the frontend, `onRetrieval`, `onToken`, `onToolStart`, `onToolEnd`, `onNewResponse`, `onDone`, `onTitle`, and `onError` mutate the current in-memory message list and session list inside `AppProvider`.
9. `onNewResponse` closes the current assistant message and starts a fresh assistant placeholder, so a single backend turn can render as multiple assistant message blocks in the UI.
10. `onDone` clears streaming state and refreshes the session list; `onTitle` patches the matching session title if the backend title task returns before timeout/disconnect.

## SSE Event Contract

The current SSE payloads exposed by `POST /api/chat` are:

| Event type | Payload fields | Notes |
| --- | --- | --- |
| `retrieval` | `type`, `query`, `results` | Emitted only when RAG mode is enabled and retrieval returns hits. |
| `token` | `type`, `content` | Streams assistant text incrementally. |
| `tool_start` | `type`, `tool`, `input` | The backend does not currently expose `run_id` in SSE even though internal events carry it. |
| `tool_end` | `type`, `tool`, `output` | The frontend falls back to `tool` as the run identifier because `run_id` is absent. |
| `new_response` | `type` | Marks a fresh assistant text segment after a tool call. |
| `done` | `type`, `content`, `session_id` | `content` is the concatenated text from all assistant segments in the turn. |
| `title` | `type`, `session_id`, `title` | Only attempted after the first successful assistant turn. Sent after `done` if it resolves in time. |
| `error` | `type`, `error` | User message is still persisted before the error is surfaced. |

Current event ordering rules:

- Normal chat: `token* -> done -> title?`
- Tool-using chat: `token* -> tool_start -> tool_end -> new_response -> token* -> done -> title?`
- RAG-enabled chat with hits: `retrieval -> token* -> ... -> done -> title?`
- `new_response` is emitted only after a tool has finished and the model resumes text generation.
- If RAG mode is enabled but retrieval returns no hits, the turn collapses to the normal non-retrieval sequence.

One implementation detail worth freezing: `ChatRequest` accepts a `stream` boolean, but `backend/api/chat.py` currently always returns a `StreamingResponse` and does not branch on `stream`.

## Session JSON Structure

Current on-disk sessions are stored as JSON objects under `backend/sessions/<session_id>.json` with this shape:

```json
{
  "title": "New Chat",
  "created_at": 1710000000.0,
  "updated_at": 1710000000.0,
  "compressed_context": "",
  "messages": [
    {
      "role": "user",
      "content": "..."
    },
    {
      "role": "assistant",
      "content": "...",
      "tool_calls": [
        {
          "tool": "read_file",
          "input": "context/current-feature.md",
          "output": "..."
        }
      ]
    }
  ]
}
```

Important compatibility details:

- Legacy v1 sessions that are plain JSON lists are migrated in memory to the v2 dict structure and rewritten on read.
- `load_session()` returns raw stored messages only.
- `load_session_for_agent()` is not the same view as `get_history()`: it merges adjacent assistant messages and injects `compressed_context` as a synthetic `system` message.
- `GET /api/sessions/{id}/messages` prepends the current system prompt and returns raw stored messages after it; it does not expose the agent-only synthetic compressed-context message.
- `compress_history()` archives the oldest messages to `backend/sessions/archive/` and appends the new summary to `compressed_context`, separated by `---` if multiple compressions have occurred.

## File API and Skill Discovery Freeze

### `/api/files`

Current file API exposure from `backend/api/files.py`:

- The allowlist is resolved relative to the backend `base_dir` (`backend/` at runtime), not the repository root.
- Read/write prefixes allowed relative to that backend `base_dir`: `workspace/`, `memory/`, `skills/`, `knowledge/`
- Additional root file allowed: `SKILLS_SNAPSHOT.md`
- Path traversal is blocked before whitelist checks.
- Writes are capped at 500 KB.
- Saving `memory/MEMORY.md` triggers a memory-index rebuild attempt.
- The API creates parent directories as needed for allowed writes.

### `/api/skills`

Current behavior from `backend/api/files.py`:

- `GET /api/skills` returns discovered skills with `name`, `path`, `category`, and `stage`.
- It uses `collect_skill_entries(base, respect_enabled=False)`, so the list is discovery-oriented and not filtered down to only enabled skills.

### `skills_scanner`

Current discovery behavior from `backend/tools/skills_scanner.py`:

1. Scan `backend/skills/**/SKILL.md`
2. Scan configured extra directories from `backend/config.json`
3. Scan repo-root `.agents/skills/**/SKILL.md` if present

Precedence and filtering rules:

- Discovery is ordered exactly as listed above.
- Duplicate skill names are deduplicated by first hit; later duplicates are ignored.
- `scan_skills()` writes `backend/SKILLS_SNAPSHOT.md` using `respect_enabled=True`.
- `collect_skill_entries(..., respect_enabled=False)` is used when the API wants a full registry-style listing.

Current workspace state:

- `backend/skills/` contains 47 local skills.
- `skills.extra_dirs` is `[]`.
- `.agents/skills/` is absent.
- `read_file_extra_roots` is `[]` in config.

## Tool Inventory Freeze

`backend/tools/__init__.py` currently registers 11 tools.

### General-purpose and infrastructure tools

- `terminal`
- `python_repl`
- `fetch_url`
- `http_json`
- `slurm_tool`
- `read_file`
- `write_file`
- `search_knowledge_base`

### Biology-specific tools

- `ncbi_eutils`
- `uniprot_api`
- `ensembl_api`

This inventory supersedes the older README summary of 5 tools.

## Frontend State Flow Freeze

### Session bootstrap

- On mount, `AppProvider` loads sessions and the RAG config in parallel.
- If at least one session exists, it auto-loads the newest session into the chat view.

### Session selection

- `_loadSession()` sets the selected session id, fetches `/api/sessions/{id}/history`, filters to `user` and `assistant` roles, and assigns fresh client-side message ids.
- Stored `tool_calls` are preserved when history is rehydrated into UI messages.

### Streaming message assembly

- `sendMessage()` immediately appends a local user message and one streaming assistant placeholder before the network request completes.
- Retrieval results attach to the current streaming assistant message.
- `tool_start` stores `pendingTool`.
- `tool_end` appends a completed `tool_calls` entry and clears `pendingTool`.
- `new_response` closes the prior assistant block and starts a new one.
- `done` marks the final assistant block as no longer streaming and refreshes the session list.
- `title` updates the session list entry in place.
- `error` appends a warning line to the active assistant block and clears streaming state.

### RAG toggle

- `setRagMode(enabled)` calls `PUT /api/config/rag-mode` and updates local `ragMode` state after success.

### Compression action

- `compressSession()` calls `POST /api/sessions/{id}/compress`, reloads history, remaps stored messages into UI messages, and refreshes the session list.

## Gold-Path Traces

Captured trace docs are stored here:

- `traces/normal-chat.md`
- `traces/tool-using-chat.md`
- `traces/rag-enabled-chat.md`

Raw capture artifacts are stored here:

- `captures/normal-chat.json`
- `captures/tool-using-chat.json`
- `captures/rag-enabled-chat.json`
- `captures/index.json`

These captures were generated by running `backend/scripts/capture_chat_baseline.py`, which calls the current chat/session route functions and records the emitted SSE payloads plus stored session history. The internal agent events were deterministic stubs, but the translation, persistence, and title-generation behavior came from the live route code.

## Regression Criteria

Later phases should preserve these behaviors unless a later feature spec explicitly changes them:

- `POST /api/chat` continues to expose the current SSE event names and payload fields.
- `done` continues to include concatenated assistant text and `session_id`.
- Title generation remains post-`done`, first-successful-turn behavior rather than a pre-response prerequisite.
- Session files remain readable in both legacy list form and current v2 dict form.
- `load_session_for_agent()` continues to merge adjacent assistant messages and inject `compressed_context` as a synthetic `system` message.
- `/api/files` keeps its current whitelist boundaries unless a later file-access spec intentionally changes them.
- Skill scanning continues to support `backend/skills`, configured extra dirs, and `.agents/skills`, with first-hit-by-name precedence.
- `backend/tools/__init__.py` inventory changes are treated as contract changes and documented deliberately.
- Frontend `streamChat()` parsing and `AppProvider` state assembly remain compatible with the current SSE contract.

## Baseline Test Checklist

Use this checklist before and after major feature phases:

- Backend tests: run the existing backend suite in a repo-compatible Python environment. Current suite files are `test_api_health.py`, `test_config.py`, `test_memory_indexer.py`, `test_prompt_builder.py`, `test_session_manager.py`, `test_skills_scanner.py`, and `test_tools.py`.
- Frontend verification: run `npm run build` and `npm run lint` in `frontend/`.
- Manual normal-chat check: create or reuse a session, send a prompt that does not require a tool, confirm `token -> done -> title?` behavior and persisted session messages.
- Manual tool-use check: send a prompt that triggers at least one tool, confirm `tool_start`, `tool_end`, `new_response`, segmented assistant messages, and stored `tool_calls`.
- Manual RAG check: keep `rag_mode` enabled, send a prompt likely to hit memory, confirm retrieval cards appear before streamed text.
- Manual compression check: compress a session and confirm archive creation plus `compressed_context` reuse on later turns.
- Manual file API check: read and save an allowed file through the editor path, then confirm blocked access for a disallowed path.
- Manual skill scan check: confirm the skills list reflects `backend/skills`, configured extra dirs if any, and snapshot regeneration when skill configuration changes.

## Verification Run In This Step

Executed successfully in the repo’s `miniAgent` conda environment:

- `python backend/scripts/capture_chat_baseline.py`
  - wrote three route-level capture files under `context/baselines/01-baseline-freeze/captures/`
- `python -m pytest backend/tests/test_config.py backend/tests/test_prompt_builder.py backend/tests/test_skills_scanner.py -q`
  - `34 passed in 0.19s`
- `cd frontend && npm run build`
  - passed
- `cd frontend && npm run lint`
  - passed after adding a minimal Next.js ESLint config

Additional observed verification notes:

- `python -m pytest backend/tests/test_session_manager.py backend/tests/test_config.py backend/tests/test_prompt_builder.py backend/tests/test_skills_scanner.py -q` surfaced 5 failures in `test_session_manager.py`.
- Those failures reflect current drift between the session-manager tests and current implementation behavior around strict UUID validation and `compressed_context` being injected as a synthetic `system` message.
- The baseline bundle records the current implementation behavior; it does not attempt to resolve those pre-existing test failures.
