# T Cell Session Audit

## Date

2026-04-02

## Question

Does the pasted `session.v3` history for the "Top T Cell Biology Papers Recommendations" conversation align with BioAPEX's intended session design, tool-calling rules, evidence-review contract, and permission/approval behavior?

## Verdict

Partially aligned.

The session storage shape and quiet-transcript design are working as intended, and the first turn correctly withholds a substantive biology answer when evidence review is still pending.

The main problem is the second turn: the final answer claims to be grounded in evidence review, but the persisted review artifact does not support the three papers that were actually recommended.

There is also a smaller but real metadata-ordering bug where an `evidence_review` tool result can still serialize `review_completed: false` even after the review tool has just succeeded.

## What Aligns

- `backend/graph/session_manager.py` is persisting `blocks` as the primary session truth while also preserving legacy-compatible `tool_calls` and `retrievals`.
- `.omx/plans/p3-modern-agent-ux-slice-2-turn-details-and-transcript-policy.md` explicitly allows the modern dual representation and the quieter final transcript.
- The first turn behaved correctly for a biology question:
  - `compliance_preflight` returned `allow`
  - `evidence_review_gate` required review
  - no `evidence_review` completed
  - the assistant withheld a substantive biology recommendation
- The exploratory `evidence_retrieval` and `ncbi_eutils` calls in the first turn are consistent with current tool policy:
  - inspection-scoped lookups are allowed with warnings
  - final evidence-backed synthesis still depends on `evidence_review`

## Findings

### 1. High: the second turn's final answer is not grounded in the reviewed evidence

Evidence inspected:

- `backend/artifacts/evidence-review/2026-04-02/run-20260402T164113Z-cdee3155/evidence_review.json`
- `backend/artifacts/literature-retrieval/2026-04-02/run-20260402T164113Z-99443bda/evidence_card.yaml`
- `backend/artifacts/literature-retrieval/2026-04-02/run-20260402T164113Z-df1eff77/evidence_card.yaml`

What the review actually says:

- only 2 evidence cards were included
- 1 candidate was excluded because retrieval failed
- the included stable identifiers are `pmid:41918736` and `pmid:41912891`

What the final answer says:

- it recommends `PMID: 33785842`
- it recommends `PMID: 28467922`
- it recommends `PMID: 25148024`
- it says these choices are "Based on my evidence review"

Why this matters:

- the final answer is claiming provenance that is not present in the saved review artifact
- this breaks the intent of `backend/evidence/review_gate.py`, which is supposed to keep substantive biology answers grounded in completed review output rather than unsupported recall

### 2. High: `evidence_review` is too permissive for ranking/recommendation prompts

The review tool returned:

- `review_status: supported`
- `confidence: high`

But the saved review payload still shows:

- only 2 included evidence cards for a "top three papers" request
- one extracted fact about endometrial cancer immunotherapy rather than a cleanly ranked shortlist of general T-cell papers
- a synthesized conclusion that only says the retrieved evidence supports a high-confidence conclusion, not that it satisfies the requested recommendation/ranking contract

Interpretation:

- current review success criteria appear to mean "some relevant evidence was reviewed"
- they do not yet ensure "the requested top-N recommendation is fully evidenced and traceable"

### 3. Medium: `review_completed` metadata can be stale in the saved tool result

Relevant code path:

- `backend/api/chat.py` emits the `evidence_review` tool result
- only after that does it set `context.review_completed = True`
- `backend/tools/policy.py` serializes policy metadata from the current context state

Why this matters:

- the persisted tool result can say `review_completed: false` even though that very tool invocation just completed the review
- this is a real auditability bug because the stored metadata lags the actual turn state

## Permission / Approval Check

This pasted session does not exercise the permission-required path.

Observed behavior:

- both `compliance_preflight` calls returned `allow`
- neither turn required human approval
- there was no `approval_required`, `approved_override`, or access-scope denial in the transcript

Interpretation:

- the session is useful for checking evidence-review and transcript behavior
- it is not a good end-to-end sample for validating the approval UX or permission escalation design

## Design Notes

The subtle session-design choices are mostly holding up:

- having a tool-only assistant message followed by a later prose-only assistant message is consistent with the quiet-transcript design
- preserving both `blocks` and legacy `tool_calls` / `retrievals` is intentional compatibility behavior, not accidental duplication
- surfacing inspection tools before final review is consistent with the current policy split between `recommended` evidence gathering and `required` evidence review

The design break is not in transcript structure. It is in evidence traceability from reviewed artifacts to final prose.

## Recommended Follow-Up

1. Tighten `evidence_review` success criteria for ranking/recommendation prompts so "top N" answers cannot pass review with fewer than `N` grounded candidates unless the assistant explicitly says fewer were available.
2. Require the final assistant answer to derive shortlisted papers directly from reviewed evidence identifiers or evidence-card artifacts.
3. Fix the `backend/api/chat.py` ordering so `review_completed` is updated before the wrapped `evidence_review` result is serialized.
4. Add a dedicated approval-path regression transcript that actually exercises `require_approval` or access-scope denial, since this sample does not.

## Primary References

- `backend/graph/session_manager.py`
- `backend/api/chat.py`
- `backend/tools/policy.py`
- `backend/tools/registry.py`
- `backend/evidence/review_gate.py`
- `backend/artifacts/evidence-review/2026-04-02/run-20260402T164113Z-cdee3155/evidence_review.json`
- `.omx/plans/p3-modern-agent-ux-slice-2-turn-details-and-transcript-policy.md`
- `context/features/08-compliance-block-flow-spec.md`
- `frontend/src/test/app-shell.contract.test.tsx`
