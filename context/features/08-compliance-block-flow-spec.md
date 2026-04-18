# Compliance Block Flow Spec

## Overview

Turn compliance screening into enforced runtime behavior. This phase defines exactly what happens after a rule is triggered, how blocks and approvals appear in the backend and frontend, and how compliance decisions are persisted for later auditing. The goal is to make safety gates operational, not informational.

## Requirements

- Define the runtime state machine for compliance decisions:
  - preflight pending
  - allowed
  - warning issued
  - blocked
  - approval required
  - approved override
- Ensure blocked operations do not proceed to tool execution, workflow execution, or dangerous procedural output.
- Ensure approval-required operations stop before execution and emit a clear structured response explaining what approval is needed.
- Define how blocked outcomes are streamed through the existing SSE channel without breaking current clients.
- Define how the frontend should render compliance events and blocked outcomes.
- Persist every compliance decision with enough detail to audit later:
  - original request
  - triggered rules
  - final disposition
  - approver if applicable
  - timestamp
- Decide whether approvals are per-message, per-workflow, or per-run.
- Define a safe fallback behavior if the compliance subsystem fails unexpectedly:
  - default to block or approval required for high-risk classes
- Add test coverage for blocked, approved, and allowed flows.

## References

- @backend/api/chat.py
- @backend/graph/agent.py
- @frontend/src/lib/api.ts
- @frontend/src/lib/store.tsx
- @frontend/src/lib/types.ts
- @frontend/src/components/chat/ChatPanel.tsx
- @frontend/src/components/chat/ChatMessage.tsx
- @context/features/07-compliance-rules-mvp-spec.md
- @context/features/32-audit-logging-spec.md
