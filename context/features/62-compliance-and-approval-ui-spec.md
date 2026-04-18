# Compliance And Approval UI Spec

## Overview

Build the compliance surface required for a production-grade BioAPEX frontend. The backend now supports dispositions such as `allow_with_warning`, `require_approval`, and `block`, plus structured compliance report artifacts. This phase should make those states visible, understandable, and hard to ignore.

## Requirements

- Surface compliance disposition clearly in the main session view and supporting inspector areas.
- Add UI states for:
  - allow
  - allow with warning
  - require approval
  - blocked
- Render compliance report details using the actual typed structure already defined in the frontend types.
- Show triggered rules, risk category, final disposition, and whether human approval is required.
- Distinguish between:
  - informational compliance summaries
  - blocking/preflight states that stop work
  - approval-required states that need operator attention
- Ensure blocked or approval-required workflows are reflected in the workflow timeline and run summary, not just in a small badge.
- Prepare space for future approval actions or operator acknowledgment without assuming those actions are already wired.
- Keep the compliance experience calm and reviewable rather than alarm-heavy, but make it impossible to miss high-risk states.

## References

- @frontend/src/lib/types.ts
- @frontend/src/lib/store.tsx
- @frontend/src/components/chat/ChatPanel.tsx
- @frontend/src/components/chat/ThoughtChain.tsx
- @backend/api/chat.py
- @context/features/43-workflow-progress-card-spec.md
- @context/features/55-sources-tab-spec.md

