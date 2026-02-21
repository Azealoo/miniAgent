# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**miniOpenClaw** is a lightweight, transparent AI Agent system with file-first memory (Markdown/JSON instead of vector databases) and instruction-following skills (Markdown files, not Python functions). The project is currently in the **specification/planning phase** — no implementation exists yet. See `README.md` and `Plan.md` for the full technical spec (written in Chinese).

## Development Commands

### Backend
```bash
cd backend
cp .env.example .env          # First-time setup: fill in API keys
pip install -r requirements.txt
uvicorn app:app --port 8002 --host 0.0.0.0 --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev                   # Runs on http://localhost:3000
```

### Environment Variables (`backend/.env`)
```
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
OPENAI_API_KEY=sk-xxx           # Used only for embeddings
OPENAI_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

## Architecture

### Tech Stack
- **Backend**: FastAPI + LangChain 1.x (`create_agent` API, **not** `AgentExecutor`) + LlamaIndex for RAG
- **LLM**: DeepSeek via `ChatDeepSeek`; embeddings via OpenAI `text-embedding-3-small`
- **Frontend**: Next.js 14 App Router, TypeScript, Tailwind CSS + Shadcn/UI, Monaco Editor
- **State**: React Context (`store.tsx`), no Redux
- **Storage**: Local filesystem only — JSON sessions + Markdown files, no database

### Backend Structure (`backend/`)

**Startup sequence** (`app.py` lifespan):
1. `skills_scanner.scan_skills()` → scans `skills/**/SKILL.md`, generates `SKILLS_SNAPSHOT.md`
2. `agent_manager.initialize()` → creates `ChatDeepSeek` LLM, registers 5 tools
3. `memory_indexer.rebuild_index()` → builds vector index from `memory/MEMORY.md`

**Agent engine** (`graph/`):
- `agent.py`: `AgentManager` singleton — **rebuilds Agent on every request** to pick up live workspace edits; `astream()` yields 7 SSE event types: `retrieval`, `token`, `tool_start`, `tool_end`, `new_response`, `done`, `title`
- `session_manager.py`: JSON file persistence; `load_session_for_agent()` merges consecutive `assistant` messages (LLM requires strict alternation) and prepends `compressed_context` summaries
- `prompt_builder.py`: Assembles System Prompt from 6 components in order: `SKILLS_SNAPSHOT.md` → `workspace/SOUL.md` → `workspace/IDENTITY.md` → `workspace/USER.md` → `workspace/AGENTS.md` → `memory/MEMORY.md` (or a RAG guidance string). Each component capped at 20,000 chars.
- `memory_indexer.py`: LlamaIndex index for `MEMORY.md` stored at `storage/memory_index/`; MD5-based auto-rebuild on change

**5 core tools** (`tools/`), all inherit `BaseTool`, registered via `get_all_tools(base_dir)`:
- `terminal` — shell execution; blacklist for destructive commands; CWD sandboxed; 30s timeout; 5000 char output cap
- `python_repl` — wraps `langchain_experimental.tools.PythonREPLTool`
- `fetch_url` — `RequestsGetTool` + `html2text` conversion; 15s timeout; 5000 char cap
- `read_file` — `ReadFileTool` with `root_dir` path traversal protection; 10,000 char cap
- `search_knowledge_base` — LlamaIndex hybrid BM25+vector search over `knowledge/`; index at `storage/`

**Skills system**: Skills are Markdown instruction files (`skills/<name>/SKILL.md`) with YAML frontmatter (`name`, `description`). The Agent reads a skill's SKILL.md via `read_file` at runtime — there are no Python functions per skill.

**API routes** (all under `/api`): `chat.py`, `sessions.py`, `files.py`, `tokens.py`, `compress.py`, `config_api.py`. File read/write is whitelist-restricted to `workspace/`, `memory/`, `skills/`, `knowledge/`, and `SKILLS_SNAPSHOT.md`.

### Frontend Structure (`frontend/src/`)

Three-column IDE layout (Sidebar | ChatPanel | InspectorPanel) with draggable dividers (`ResizeHandle`).

- `lib/store.tsx`: Single React Context (`AppProvider`) — sessions, messages, streaming state, RAG mode, panel widths
- `lib/api.ts`: Custom SSE parser for `POST /api/chat` (browser `EventSource` only supports GET); `API_BASE` uses `window.location.hostname` for automatic LAN/local adaptation
- `components/chat/ThoughtChain.tsx`: Collapsible tool call visualization
- `components/chat/RetrievalCard.tsx`: RAG result cards (purple)
- `components/editor/InspectorPanel.tsx`: Monaco editor for editing `MEMORY.md` and `SKILL.md` files

### Session Storage Format

`sessions/{session_id}.json`:
```json
{
  "title": "...",
  "created_at": 0.0,
  "updated_at": 0.0,
  "compressed_context": "optional summary...",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [{"tool": "...", "input": "...", "output": "..."}]}
  ]
}
```
Legacy format (plain array) is auto-migrated to this v2 format on load.

### RAG Mode

When enabled (`config.json`): `memory_indexer.retrieve()` runs before the Agent call, top-3 results injected as a context block at the tail of the message history (not persisted). Saving `MEMORY.md` via the Monaco editor triggers `rebuild_index()` automatically.

### Conversation Compression

`POST /api/sessions/{id}/compress`: Takes first 50% of messages (min 4), generates a Chinese summary via DeepSeek (≤500 chars), archives originals to `sessions/archive/{id}_{timestamp}.json`, stores summary in `compressed_context`. On next agent call, summary is prepended as a synthetic `assistant` message.
