# Baseline Freeze Spec

## Overview

Establish a stable, fully documented snapshot of the current system before adding production-grade biology features. This phase should capture the real backend/frontend behavior as it exists today, including chat streaming, session persistence, skill scanning, file editing, memory retrieval, and the current tool registry. The output of this phase is the reference baseline all later phases must preserve or intentionally extend.

## Requirements

- Document the current request path from `POST /api/chat` through `AgentManager.astream()` to session persistence and frontend rendering.
- Capture the current SSE event contract exactly as implemented today: `retrieval`, `token`, `tool_start`, `tool_end`, `new_response`, `done`, `title`, and `error`.
- Record the current session JSON structure, including `title`, `created_at`, `updated_at`, `compressed_context`, and `messages`.
- Record the current writable and readable project areas exposed through `/api/files` and the current skill discovery behavior through `skills_scanner`.
- Freeze the current tool inventory from `backend/tools/__init__.py` and note which tools are biology-specific versus general-purpose.
- Create one gold-path trace for a normal chat request, one trace for a tool-using request, and one trace for a RAG-enabled request.
- Define regression criteria for later phases:
  - existing chat streaming must remain backward compatible unless a spec explicitly expands it
  - session files must remain readable after schema changes
  - skill scanning must still support `backend/skills`, configured extra dirs, and `.agents/skills`
- Produce a short inventory of the current frontend state flow:
  - session bootstrap
  - session selection
  - streaming message assembly
  - RAG toggle
  - compression action
- Define a baseline test checklist that must pass before and after each major feature phase.

## References

- @README.md
- @backend/app.py
- @backend/api/chat.py
- @backend/api/files.py
- @backend/graph/agent.py
- @backend/graph/session_manager.py
- @backend/graph/prompt_builder.py
- @backend/tools/__init__.py
- @backend/tools/skills_scanner.py
- @frontend/src/lib/store.tsx
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
