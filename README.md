# miniOpenClaw

A lightweight, fully transparent AI Agent system. Built around file-first design (Markdown/JSON instead of vector databases), instruction-driven skills (plain Markdown instead of Python functions), and full visibility into every agent operation.

---

## Table of Contents

- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Environment Setup](#environment-setup)
- [Running the App](#running-the-app)
- [Backend Architecture](#backend-architecture)
- [Frontend Architecture](#frontend-architecture)
- [Core Data Flows](#core-data-flows)
- [Key Design Decisions](#key-design-decisions)
- [API Reference](#api-reference)

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI + Uvicorn | Async HTTP + SSE streaming |
| Agent engine | LangChain 1.x `create_agent` | Not `AgentExecutor`; returns `CompiledStateGraph` |
| LLM | DeepSeek via `ChatDeepSeek` | `langchain-deepseek` package |
| RAG | LlamaIndex Core | Vector + BM25 hybrid search |
| Embeddings | OpenAI `text-embedding-3-small` | Swappable via `OPENAI_BASE_URL` |
| Token counting | tiktoken `cl100k_base` | Accurate token stats |
| Frontend | Next.js 14 App Router | TypeScript + React 18 |
| UI | Tailwind CSS + Shadcn/UI | Frosted glass / Apple aesthetic |
| Code editor | Monaco Editor | In-browser editing of Memory/Skill files |
| State | React Context | Single `AppProvider`, no Redux |
| Storage | Local filesystem | JSON sessions + Markdown files, no database |

---

## Project Structure

```
miniOpenClaw/
├── backend/
│   ├── app.py                    # FastAPI entry point, route registration, startup init
│   ├── config.py                 # RAG mode config (config.json persistence)
│   ├── requirements.txt
│   ├── .env.example
│   │
│   ├── api/                      # Route layer
│   │   ├── chat.py               # POST /api/chat — SSE streaming chat
│   │   ├── sessions.py           # Session CRUD + title generation
│   │   ├── files.py              # File read/write + skill listing
│   │   ├── tokens.py             # Token counting
│   │   ├── compress.py           # Manual conversation compression
│   │   └── config_api.py         # RAG mode toggle
│   │
│   ├── graph/                    # Agent core
│   │   ├── agent.py              # AgentManager — build & stream
│   │   ├── session_manager.py    # Session persistence (JSON files) + auto-compression
│   │   ├── prompt_builder.py     # System prompt assembler (6 components)
│   │   └── memory_indexer.py     # MEMORY.md vector index with MD5-based persistence
│   │
│   ├── tools/                    # 5 core tools
│   │   ├── __init__.py           # Tool factory — get_all_tools(base_dir)
│   │   ├── terminal_tool.py      # Sandboxed shell execution
│   │   ├── python_repl_tool.py   # Python interpreter
│   │   ├── fetch_url_tool.py     # Web fetching (HTML → Markdown)
│   │   ├── read_file_tool.py     # Sandboxed file reading
│   │   ├── search_knowledge_tool.py  # Knowledge base hybrid search
│   │   └── skills_scanner.py     # Skill directory scanner → SKILLS_SNAPSHOT.md
│   │
│   ├── workspace/                # System prompt components (editable)
│   │   ├── SOUL.md               # Personality, tone, boundaries
│   │   ├── IDENTITY.md           # Name, style
│   │   ├── USER.md               # User profile
│   │   └── AGENTS.md             # Operational protocols (memory & skill protocols)
│   │
│   ├── skills/                   # Skill directory (one subdirectory per skill)
│   │   └── <name>/SKILL.md
│   ├── memory/MEMORY.md          # Cross-session long-term memory
│   ├── knowledge/                # Knowledge base documents (for RAG retrieval)
│   ├── sessions/                 # Session JSON files (runtime, gitignored)
│   │   └── archive/              # Compressed message archives
│   ├── storage/                  # LlamaIndex persistent indexes (runtime, gitignored)
│   │   └── memory_index/
│   └── SKILLS_SNAPSHOT.md        # Auto-generated on startup (gitignored)
│
└── frontend/
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx           # Main page (three-column layout)
        │   └── globals.css
        ├── lib/
        │   ├── store.tsx          # React Context state management
        │   ├── api.ts             # Backend API client (custom SSE parser)
        │   ├── types.ts           # Shared TypeScript types
        │   └── utils.ts           # Utility helpers
        └── components/
            ├── chat/
            │   ├── ChatPanel.tsx
            │   ├── ChatMessage.tsx
            │   ├── ChatInput.tsx
            │   ├── ThoughtChain.tsx    # Collapsible tool call visualization
            │   └── RetrievalCard.tsx   # RAG retrieval result cards
            ├── layout/
            │   ├── Navbar.tsx
            │   ├── Sidebar.tsx         # Session list + Raw Messages view
            │   └── ResizeHandle.tsx    # Draggable panel dividers
            └── editor/
                └── InspectorPanel.tsx  # Monaco editor (Memory / Skills files)
```

---

## Environment Setup

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cd backend
cp .env.example .env
```

```env
# DeepSeek — main agent LLM
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# OpenAI — embeddings only (can point to any compatible proxy)
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
```

`OPENAI_BASE_URL` can be pointed at any OpenAI-compatible embedding proxy.

---

## Running the App

```bash
# Backend (port 8002)
cd backend
pip install -r requirements.txt
uvicorn app:app --port 8002 --host 0.0.0.0 --reload

# Frontend (port 3000)
cd frontend
npm install
npm run dev
```

Access locally at `http://localhost:3000`, or from other devices on the same network at `http://<your-ip>:3000`.

---

## Backend Architecture

### Startup sequence (`app.py` lifespan)

1. Configure LlamaIndex embedding model (`text-embedding-3-small`)
2. `skills_scanner.scan_skills()` — scans `skills/**/SKILL.md`, generates `SKILLS_SNAPSHOT.md`
3. `agent_manager.initialize()` — creates `ChatDeepSeek` LLM instance, registers 5 tools
4. `memory_indexer.rebuild_index()` — builds or loads the `MEMORY.md` vector index

### Agent engine (`graph/`)

#### `agent.py` — AgentManager

The core singleton. The agent is **rebuilt on every request** via `_build_agent()` so that live workspace edits are always reflected in the system prompt.

Key methods:

| Method | Description |
|---|---|
| `initialize(base_dir)` | Creates `ChatDeepSeek` LLM, registers 5 tools, wires dependencies |
| `_build_agent(rag_mode)` | Calls `build_system_prompt()` then `create_agent(llm, tools, system_prompt=…)` |
| `astream(message, history)` | Streams typed event dicts; `history` is pre-loaded by `chat.py` |

`astream()` yields 7 SSE event types in order:

```
[RAG mode]   retrieval → token... → tool_start → tool_end → new_response → token... → done
[Normal mode]            token... → tool_start → tool_end → new_response → token... → done
```

#### `session_manager.py` — Session persistence

Manages each session as a JSON file under `sessions/`. Key methods:

| Method | Description |
|---|---|
| `load_session(id)` | Returns the raw message array |
| `load_session_for_agent(id)` | LLM-optimized: merges consecutive assistant messages, prepends `compressed_context` as a synthetic assistant message |
| `save_message(id, role, content, tool_calls)` | Appends a message to the JSON file |
| `compress_history(id, summary, n)` | Archives first n messages to `sessions/archive/`, stores summary in `compressed_context` |
| `auto_compress_if_needed(id, llm, threshold=40)` | Compresses oldest 50% when message count ≥ threshold |

#### `prompt_builder.py` — System prompt assembly

Six components assembled in order, each capped at 20,000 chars:

```
① SKILLS_SNAPSHOT.md    — available skills list (auto-generated)
② workspace/SOUL.md     — personality, tone, boundaries
③ workspace/IDENTITY.md — name, style
④ workspace/USER.md     — user profile
⑤ workspace/AGENTS.md   — operational protocols
⑥ memory/MEMORY.md      — long-term memory (replaced by RAG guidance string in RAG mode)
```

#### `memory_indexer.py` — MEMORY.md vector index

LlamaIndex index dedicated to `memory/MEMORY.md`, persisted to `storage/memory_index/`.

- **Fast path**: on startup, if a `md5.txt` checksum matches the current file, loads the persisted index from disk (no re-embedding).
- **Slow path**: if the file has changed, chunks the content, re-embeds, persists the new index and updates `md5.txt`.
- **Runtime**: `_maybe_rebuild()` is called before every `retrieve()` — if MEMORY.md was edited (e.g. via the Monaco editor or `terminal`/`python_repl`), the index is automatically rebuilt.

### 5 core tools (`tools/`)

All inherit `BaseTool` and are registered via `get_all_tools(base_dir)`.

| Tool | File | Function | Safety |
|---|---|---|---|
| `terminal` | `terminal_tool.py` | Shell execution | Destructive command blacklist; CWD locked to project root; 30s timeout; 5,000 char output cap |
| `python_repl` | `python_repl_tool.py` | Python execution | Wraps `langchain_experimental.tools.PythonREPLTool`; 5,000 char output cap |
| `fetch_url` | `fetch_url_tool.py` | Web fetching | HTML→Markdown via `html2text`; 15s timeout; 5,000 char cap |
| `read_file` | `read_file_tool.py` | File reading | `root_dir` path traversal protection; 10,000 char cap |
| `search_knowledge_base` | `search_knowledge_tool.py` | Knowledge base search | Lazy index load; top-3 hybrid BM25+vector retrieval; persisted index |

### Skills system

Skills are pure Markdown instruction files (`skills/<name>/SKILL.md`) with YAML frontmatter. The agent reads a skill's `SKILL.md` via `read_file` at runtime — there are no Python functions per skill.

On startup, `skills_scanner.py` scans all skills and generates `SKILLS_SNAPSHOT.md`, which is injected as the first component of the system prompt.

**SKILL.md format:**
```yaml
---
name: my_skill
description: What this skill does
version: 1.0
---

## Steps
1. Use `fetch_url` to retrieve ...
2. Parse the result with `python_repl` ...
3. Reply to the user ...
```

The agent can create new skills autonomously via `terminal` or `python_repl` (e.g. `python -c "open('skills/new/SKILL.md','w').write(...)"`). New skills are picked up on the next request without a server restart.

### Session storage format

`sessions/{session_id}.json`:

```json
{
  "title": "Weather query",
  "created_at": 1706000000.0,
  "updated_at": 1706000100.0,
  "compressed_context": "User previously asked about weather...",
  "messages": [
    { "role": "user", "content": "What's the weather in Seattle?" },
    {
      "role": "assistant",
      "content": "Let me check...",
      "tool_calls": [
        { "tool": "terminal", "input": "curl wttr.in/Seattle", "output": "..." }
      ]
    },
    { "role": "assistant", "content": "Seattle is 58°F and cloudy." }
  ]
}
```

Legacy v1 format (plain array) is auto-migrated to v2 on load.

### API layer (`api/`)

#### `chat.py` — SSE streaming chat

`POST /api/chat` is the core endpoint. Internal flow:

1. Check if this is the session's first message (for title generation)
2. Auto-compress session if ≥ 40 messages (`auto_compress_if_needed`)
3. Load and prepare history for the LLM (`load_session_for_agent`)
4. Stream events from `agent_manager.astream(message, history)`
5. On `done`: persist user message + each assistant segment to the session file
6. On first message: generate a short English title via a second LLM call, emit `title` event

SSE event types:

| Event | Payload fields | When |
|---|---|---|
| `retrieval` | `query`, `results` | RAG retrieval complete (RAG mode only) |
| `token` | `content` | Each LLM output token |
| `tool_start` | `tool`, `input` | Before a tool call |
| `tool_end` | `tool`, `output` | After a tool returns |
| `new_response` | — | Agent starts new text segment after tool use |
| `done` | `content`, `session_id` | Full turn complete |
| `title` | `session_id`, `title` | Auto-generated title (first message only) |
| `error` | `error` | Unhandled exception |

---

## Frontend Architecture

Three-column IDE layout with draggable dividers:

```
┌────────────────────────────────────────────────────────┐
│                      Navbar                            │
├──────────┬─────────────────────────┬───────────────────┤
│          │                         │                   │
│ Sidebar  │      ChatPanel          │  InspectorPanel   │
│          │                         │                   │
│ Sessions │  Message bubbles        │  Memory / Skills  │
│          │  ├─ ThoughtChain        │  file list        │
│ Raw Msgs │  ├─ RetrievalCard       │  Monaco editor    │
│ RAG mode │  └─ Markdown content   │  Token stats      │
│          │                         │                   │
│          │  ChatInput              │                   │
├──────────┴─────────────────────────┴───────────────────┤
│                  ResizeHandle (draggable)               │
└────────────────────────────────────────────────────────┘
```

- **`store.tsx`**: Single React Context (`AppProvider`) — sessions, messages, streaming state, RAG mode, panel widths
- **`api.ts`**: Custom SSE parser for `POST /api/chat` (the browser's `EventSource` only supports GET); `API_BASE` uses `window.location.hostname` for automatic LAN/local adaptation
- **`types.ts`**: Shared TypeScript interfaces (`Message`, `Session`, `ToolCall`, etc.)
- **`utils.ts`**: Utility helpers (class merging, formatting)

---

## Core Data Flows

### Sending a message

```
Frontend                              Backend
│
├─ store.sendMessage(text)
│   └─ streamChat(text, sessionId) ──→ POST /api/chat
│                                       │
│                                       ├─ auto_compress_if_needed()
│                                       ├─ load_session_for_agent()
│                                       └─ agent_manager.astream(message, history)
│                                           │
│                                           ├─ [RAG] memory_indexer.retrieve()
│                                           │   └─ yield retrieval event
│                                           ├─ _build_agent()
│                                           │   ├─ build_system_prompt()
│                                           │   └─ create_agent(llm, tools, system_prompt)
│                                           └─ agent.astream_events(messages)
│ ← SSE: token ──────────────────────────────  ├─ yield token / tool_start / tool_end
│ ← SSE: tool_start / tool_end ─────────────   └─ yield done
│ ← SSE: done ───────────────────────────── save_message()
│ ← SSE: title ──────────────────────────── [first msg] _generate_title()
│
└─ update messages state + refresh sessions
```

### Conversation compression

```
User clicks compress ──→ POST /api/sessions/{id}/compress
                          │
                          ├─ Take first 50% of messages (min 4)
                          ├─ DeepSeek generates English summary (≤500 chars)
                          ├─ Archive originals → sessions/archive/{id}_{ts}.json
                          └─ Store summary in compressed_context

Next agent call ──→ load_session_for_agent()
                    └─ Prepend synthetic assistant message:
                       "[Summary of previous conversation]\n{summary}"
```

### Agent self-updating memory and skills

```
Update memory:
  Agent reads  → read_file("memory/MEMORY.md")
  Agent writes → terminal("python -c \"open('memory/MEMORY.md','w').write(...)\"")
               → memory_indexer MD5 check detects change on next retrieve()
               → index rebuilt automatically

Create a skill:
  Agent writes → terminal("mkdir -p skills/<name> && cat > skills/<name>/SKILL.md << 'EOF' ...")
               → new skill picked up on next request (agent rebuilt per request)
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `create_agent` instead of `AgentExecutor` | LangChain 1.x recommended API; returns `CompiledStateGraph` with native `astream_events` support |
| Agent rebuilt on every request | Ensures system prompt always reflects live workspace edits with zero extra infrastructure |
| 5 tools, no dedicated `write_file` | Agent uses `terminal` or `python_repl` for writes — more flexible and consistent with shell-first philosophy |
| File-first instead of database | Zero deployment friction; all state is human-readable and version-controllable |
| Skills = Markdown instructions | Agent reads and follows them autonomously — no new Python code per skill |
| MD5-based memory index persistence | Avoids re-embedding on every startup; stale index auto-rebuilt when file changes |
| Multi-segment responses stored separately | Faithfully preserves tool-call context; Raw Messages view shows full detail |
| System prompt components capped at 20K chars | Prevents `MEMORY.md` bloat from overflowing the context window |
| RAG results not persisted | Avoids session file bloat; retrieval context is per-request only |
| Path whitelists + traversal detection | Double protection on both `read_file` tool and the `/api/files` endpoint |
| `window.location.hostname` for API base | Single build works for both localhost and LAN access without configuration |
| Auto-compression at 40 messages | Keeps active context manageable; older history archived with English summary |

---

## API Reference

| Path | Method | Description |
|---|---|---|
| `/api/chat` | POST | SSE streaming chat |
| `/api/sessions` | GET | List all sessions |
| `/api/sessions` | POST | Create new session |
| `/api/sessions/{id}` | PUT | Rename session |
| `/api/sessions/{id}` | DELETE | Delete session |
| `/api/sessions/{id}/messages` | GET | Full messages (including system prompt) |
| `/api/sessions/{id}/history` | GET | Conversation history (with tool calls) |
| `/api/sessions/{id}/generate-title` | POST | AI-generated English title |
| `/api/sessions/{id}/compress` | POST | Manually compress conversation history |
| `/api/files?path=` | GET | Read file (whitelist-protected) |
| `/api/files` | POST | Save file — triggers memory index rebuild if `MEMORY.md` |
| `/api/skills` | GET | List available skills |
| `/api/tokens/session/{id}` | GET | Session token count (system + messages) |
| `/api/tokens/files` | POST | Batch file token count |
| `/api/config/rag-mode` | GET | Get RAG mode status |
| `/api/config/rag-mode` | PUT | Toggle RAG mode |
