# Tool Output Contracts Spec

## Overview

Standardize how tools return results so later workflow, provenance, evidence, and QA features can consume tool outputs without guessing. Today tools mostly emit strings. This phase should define structured payloads and compatibility rules so the current chat UI keeps working while backend logic gains machine-readable outputs.

## Requirements

- Define a common tool-result envelope that every tool should eventually support.
- The envelope should distinguish:
  - human-readable summary
  - structured payload
  - artifact references
  - warnings
  - error state
- Maintain backward compatibility with the current `tool_start` and `tool_end` SSE events.
- Decide whether the structured payload travels directly through SSE or is persisted as a referenced artifact and only summarized over SSE.
- Define output expectations for current high-impact tools:
  - `slurm_tool`
  - `ncbi_eutils_tool`
  - `uniprot_api_tool`
  - `ensembl_api_tool`
  - `search_knowledge_tool`
  - `read_file_tool`
  - `write_file_tool`
- Require tools that call external systems to preserve raw source payloads or a cached form when feasible.
- Require tools that write files or submit jobs to return explicit paths, identifiers, and status codes.
- Define a consistent error model so the agent and UI can distinguish blocked operations, retriable failures, malformed inputs, and successful empty results.
- Add a migration note for frontend components that currently assume tool outputs are plain strings.

## References

- @backend/graph/agent.py
- @backend/api/chat.py
- @backend/tools/__init__.py
- @backend/tools/slurm_tool.py
- @backend/tools/ncbi_eutils_tool.py
- @backend/tools/uniprot_api_tool.py
- @backend/tools/ensembl_api_tool.py
- @backend/tools/search_knowledge_tool.py
- @frontend/src/lib/api.ts
- @frontend/src/lib/types.ts
- @frontend/src/components/chat/ThoughtChain.tsx
- @context/features/04-artifact-registry-mvp-spec.md
