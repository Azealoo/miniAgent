# Harness-First General Agent Review

Date: 2026-04-02

## Reviewer Findings

1. Medium: ordinary sends no longer honored legacy workflow state, while some quick-start paths still depended on it implicitly.
2. Low: helper-agent tests did not verify the real manifest-driven exposure path.

## Resolution

1. Quick-start entry points in the sidebar and flows workspace now intentionally prime general-agent drafts without relying on hidden workflow state.
2. Added manifest-driven exposure coverage for planner/verifier runtime tools and restored verifier exposure for `evidence_review`.

## Verdict

Approved after fixes.

## Residual Risk

Workflow history and legacy workflow surfaces still exist as compatibility shims, so the remaining structural work is to keep moving routing logic out of `backend/api/chat.py` and into the runtime boundary cleanly.
