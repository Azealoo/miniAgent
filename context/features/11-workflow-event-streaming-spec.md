# Workflow Event Streaming Spec

## Overview

Extend the current SSE-based chat stream so explicit workflow execution is visible in real time. The UI should be able to show step progress, blocked gates, job handoffs, and artifact creation without losing compatibility with the current token and tool stream.

## Requirements

- Preserve the current chat SSE event types and semantics.
- Define additional workflow-related event types, for example:
  - `workflow_start`
  - `workflow_step_start`
  - `workflow_step_end`
  - `workflow_blocked`
  - `workflow_artifact`
  - `workflow_done`
- Decide which workflow data belongs inline in SSE versus in referenced artifacts.
- Ensure workflow events can be interleaved with model tokens and tool events without corrupting the current frontend state logic.
- Add run IDs and step IDs to streaming events so the frontend can group them correctly.
- Define the minimum payload for each workflow event type.
- Ensure failed or blocked workflow events still end in a deterministic final state.
- Add frontend rendering requirements for grouped workflow progress in the chat transcript or thought-chain panel.

## References

- @backend/api/chat.py
- @backend/graph/agent.py
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @frontend/src/components/chat/ThoughtChain.tsx
- @frontend/src/components/chat/ChatMessage.tsx
- @context/features/10-internal-dag-runner-mvp-spec.md
- @context/features/14-rnaseq-workflow-skeleton-spec.md
