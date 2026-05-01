# Compliance And Approval UI Spec

> **Status: Superseded (2026-04-03).** This spec is retained for historical
> reference only. The compliance-preflight runtime and the compliance-first
> UI surface it assumed were removed by the two 2026-04-03 slices:
> `.omx/plans/remove-compliance-preflight-active-runtime-slice-2026-04-03.md`
> and `.omx/plans/remove-stale-routes-and-compliance-ui-slice-2026-04-03.md`.
> The active SSE contract no longer emits compliance dispositions; tool
> gating is handled by `tool_awaiting_approval` and
> `frontend/src/components/chat/ApprovalGate.tsx`, not by severity-based
> compliance states. `ComplianceDisposition` in `frontend/src/lib/types.ts`
> and `ComplianceReportArtifact` in `frontend/src/test/fixtures.ts` survive
> only for archived-session deserialization. Do not build against this
> document; open a fresh spec if severity-based disclosure is revived. See
> Azealoo/miniAgent#73 for the triage that closed this out.

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

