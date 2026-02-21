# miniAgent

A lightweight, fully transparent AI Agent system. Built around file-first design (Markdown/JSON instead of vector databases), instruction-driven skills (plain Markdown instead of function-calling), and full visibility into every agent operation.

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
| Agent engine | LangChain 1.x `create_react_agent` | Not `AgentExecutor` |
| LLM | DeepSeek via `ChatOpenAI` | OpenAI-compatible API |
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
miniAgent/
├── backend/
│   ├── app.py                    # FastAPI entry point, route registration, startup init
│   ├── config.py                 # Global config management (config.json persistence)
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
│   │   ├── prompt_builder.py     # System prompt assembler
│   │   └── memory_indexer.py     # MEMORY.md vector index (RAG)
│   │
│   ├── tools/                    # 6 core tools
│   │   ├── __init__.py           # Tool factory
│   │   ├── terminal_tool.py      # Sandboxed shell execution
│   │   ├── python_repl_tool.py   # Python interpreter
│   │   ├── fetch_url_tool.py     # Web scraping (HTML → Markdown)
│   │   ├── read_file_tool.py     # Sandboxed file reading
│   │   ├── write_file_tool.py    # Sandboxed file writing (memory/, skills/, knowledge/)
│   │   ├── search_knowledge_tool.py  # Knowledge base search
│   │   └── skills_scanner.py     # Skill directory scanner
│   │
│   ├── workspace/                # System prompt components
│   │   ├── SOUL.md               # Personality, tone, boundaries
│   │   ├── IDENTITY.md           # Name, style
│   │   ├── USER.md               # User profile
│   │   └── AGENTS.md             # Operational protocols (memory & skill protocols)
│   │
│   ├── skills/                   # Skill directory (one subdirectory per skill)
│   │   └── <name>/SKILL.md
│   ├── memory/MEMORY.md          # Cross-session long-term memory
│   ├── knowledge/                # Knowledge base documents (for RAG retrieval)
│   ├── sessions/                 # Session JSON files
│   │   └── archive/              # Compressed message archives
│   ├── storage/                  # LlamaIndex persistent indexes
│   │   └── memory_index/
│   └── SKILLS_SNAPSHOT.md        # Auto-generated skill snapshot (on startup)
│
└── frontend/
    └── src/
        ├── app/
        │   ├── layout.tsx
        │   ├── page.tsx           # Main page (three-column layout)
        │   └── globals.css
        ├── lib/
        │   ├── store.tsx          # React Context state management
        │   └── api.ts             # Backend API client (custom SSE parser)
        └── components/
            ├── chat/
            │   ├── ChatPanel.tsx
            │   ├── ChatMessage.tsx
            │   ├── ChatInput.tsx
            │   ├── ThoughtChain.tsx    # Collapsible tool call visualization
            │   └── RetrievalCard.tsx   # RAG retrieval result cards (purple)
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

1. `skills_scanner.scan_skills()` — scans `skills/**/SKILL.md`, generates `SKILLS_SNAPSHOT.md`
2. `agent_manager.initialize()` — creates the LLM instance, registers 6 tools
3. `memory_indexer.rebuild_index()` — builds the `MEMORY.md` vector index for RAG

### Agent engine (`graph/`)

#### `agent.py` — AgentManager

The core singleton. The agent is **rebuilt on every request** so that live workspace edits are always reflected in the system prompt.

`astream()` yields 7 SSE event types in order:

```
[RAG mode]   retrieval → token... → tool_start → tool_end → new_response → token... → done
[Normal mode]            token... → tool_start → tool_end → new_response → token... → done
```

Auto-compression runs at the top of every `astream()` call: if the session has ≥ 40 messages, the oldest 50% are automatically summarized and archived before the agent runs.

#### `session_manager.py` — Session persistence

Manages each session as a JSON file. Key methods:

| Method | Description |
|---|---|
| `load_session(id)` | Returns the raw message array |
| `load_session_for_agent(id)` | LLM-optimized: merges consecutive assistant messages, prepends `compressed_context` |
| `save_message(id, role, content, tool_calls)` | Appends a message to the JSON file |
| `compress_history(id, summary, n)` | Archives first n messages, stores summary in `compressed_context` |
| `auto_compress_if_needed(id, llm, threshold=40)` | Automatically compresses when message count hits the threshold |

#### `prompt_builder.py` — System prompt assembly

Six components assembled in order, each capped at 20,000 chars:

```
① SKILLS_SNAPSHOT.md    — available skills list
② workspace/SOUL.md     — personality, tone, boundaries
③ workspace/IDENTITY.md — name, style
④ workspace/USER.md     — user profile
⑤ workspace/AGENTS.md   — operational protocols
⑥ memory/MEMORY.md      — long-term memory (skipped in RAG mode)
```

#### `memory_indexer.py` — MEMORY.md vector index

LlamaIndex index dedicated to `memory/MEMORY.md` (stored at `storage/memory_index/`). Uses MD5 to detect changes and auto-rebuild. Also rebuilt whenever `MEMORY.md` is saved via the Monaco editor or the `write_file` tool.

### 6 core tools (`tools/`)

All inherit `BaseTool` and are registered via `get_all_tools(base_dir)`.

| Tool | File | Function | Safety |
|---|---|---|---|
| `terminal` | `terminal_tool.py` | Shell execution | Destructive command blacklist; CWD locked to project root; 30s timeout; 5000 char output cap |
| `python_repl` | `python_repl_tool.py` | Python execution | Wraps LangChain `PythonREPLTool` |
| `fetch_url` | `fetch_url_tool.py` | Web scraping | HTML→Markdown via html2text; 15s timeout; 5000 char cap |
| `read_file` | `read_file_tool.py` | File reading | Path traversal protection; 10,000 char cap |
| `write_file` | `write_file_tool.py` | File writing | Whitelist: `memory/`, `skills/`, `knowledge/` only; path traversal protection; 50,000 char cap; auto-rebuilds memory index on `MEMORY.md` write |
| `search_knowledge_base` | `search_knowledge_tool.py` | Knowledge base search | Lazy index loading; top-3 hybrid BM25+vector retrieval |

### Skills system

Skills are pure Markdown instruction files (`skills/<name>/SKILL.md`) with YAML frontmatter. The agent reads a skill's `SKILL.md` via `read_file` at runtime — there are no Python functions per skill.

On startup, `skills_scanner.py` scans all skills and generates `SKILLS_SNAPSHOT.md` which is injected into the system prompt.

**SKILL.md format:**
```yaml
---
name: my_skill
description: What this skill does
version: 1.0
---

## Steps
1. Use `fetch_url` to ...
2. Parse the result ...
3. Reply to the user ...
```

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

1. Auto-compress session if ≥ 40 messages
2. Load and merge session history for the LLM
3. Stream `token`, `tool_start`, `tool_end`, `new_response`, `done` events
4. On `done`: persist user message + each assistant segment to the session file
5. On first message: generate a short English title via a second LLM call

SSE event types:

| Event | Data | When |
|---|---|---|
| `retrieval` | `{query, results}` | RAG retrieval complete |
| `token` | `{content}` | Each LLM output token |
| `tool_start` | `{tool, input}` | Before tool call |
| `tool_end` | `{tool, output}` | After tool returns |
| `new_response` | `{}` | Agent starts new text segment after tool use |
| `done` | `{session_id}` | Full turn complete |
| `title` | `{session_id, title}` | Auto-generated title (first message only) |
| `error` | `{error}` | Unhandled exception |

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
│ RAG/Wrench│  └─ Markdown content   │  Token stats      │
│ Tokens   │                         │                   │
│          │  ChatInput              │                   │
├──────────┴─────────────────────────┴───────────────────┤
│                  ResizeHandle (draggable)               │
└────────────────────────────────────────────────────────┘
```

- **`store.tsx`**: Single React Context — sessions, messages, streaming state, RAG mode, panel widths
- **`api.ts`**: Custom SSE parser for `POST /api/chat` (browser `EventSource` only supports GET); `API_BASE` uses `window.location.hostname` for automatic LAN/local adaptation

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
│                                       ├─ [RAG] memory_indexer.retrieve()
│                                       │   └─ yield retrieval event
│                                       ├─ build_system_prompt()
│                                       └─ agent.astream()
│ ← SSE: token ─────────────────────────│   ├─ yield token/tool_start/tool_end
│ ← SSE: tool_start/tool_end ───────────│   └─ yield done
│ ← SSE: done ───────────────────────────── save_message()
│ ← SSE: title ──────────────────────── [first msg] _generate_title()
│
└─ update messages state + refresh sessions
```

### Conversation compression

```
User clicks compress ──→ POST /api/sessions/{id}/compress
                          │
                          ├─ Take first 50% of messages (min 4)
                          ├─ DeepSeek generates summary (≤500 chars)
                          ├─ Archive to sessions/archive/
                          └─ Store summary in compressed_context

Next agent call ──→ load_session_for_agent()
                    └─ Prepend synthetic assistant message:
                       "[Summary of previous conversation]\n{summary}"
```

### Agent self-updating memory/skills

```
Agent learns something → read_file("memory/MEMORY.md")
                       → write_file("memory/MEMORY.md", <full updated content>)
                       → memory_indexer.rebuild_index() [auto-triggered]

Agent creates a skill  → write_file("skills/<name>/SKILL.md", <content>)
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| `create_react_agent` instead of `AgentExecutor` | LangChain 1.x recommended API with native streaming support |
| Agent rebuilt on every request | Ensures system prompt always reflects live workspace edits |
| File-first instead of database | Zero deployment friction; all state is human-readable |
| Skills = Markdown instructions | Agent reads and executes them autonomously — no new Python functions needed |
| Multi-segment responses stored separately | Faithfully preserves tool-call context; Raw Messages view shows full detail |
| System prompt components capped at 20K chars | Prevents `MEMORY.md` bloat from overflowing the context window |
| RAG results not persisted | Avoids session file bloat; retrieval context is per-request only |
| Path whitelists + traversal detection | Double protection on both file read and write tools |
| `window.location.hostname` for API base | Single build works for both localhost and LAN access |
| Auto-compression at 40 messages | Keeps active context manageable; older history archived with summary |

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
| `/api/sessions/{id}/generate-title` | POST | AI-generated title |
| `/api/sessions/{id}/compress` | POST | Manually compress conversation history |
| `/api/files?path=` | GET | Read file |
| `/api/files` | POST | Save file (editor use) |
| `/api/skills` | GET | List available skills |
| `/api/tokens/session/{id}` | GET | Session token count |
| `/api/tokens/files` | POST | Batch file token count |
| `/api/config/rag-mode` | GET | Get RAG mode status |
| `/api/config/rag-mode` | PUT | Toggle RAG mode |
