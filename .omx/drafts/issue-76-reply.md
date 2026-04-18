<!-- Draft reply for Azealoo/miniAgent#76 -->
<!-- URL: https://github.com/Azealoo/miniAgent/issues/76 -->
<!-- Review and adjust before posting. This was NOT auto-posted. -->

Thanks for filing this. Before picking it up I need to flag that the issue body points at code that doesn't exist on `bioAgent`, so the fix as described isn't implementable against this branch yet.

Verified on `bioAgent` (HEAD `5303ada`):

- `backend/evidence/review_gate.py` does not exist. `backend/evidence/` contains only `__init__.py`, `review.py`, `retrieval.py`, and `claim_graph.py`.
- `review_completed` has zero Python references. Not in `backend/api/chat.py`, `backend/tools/policy.py`, `backend/tools/policy_wrappers.py`, `backend/tools/evidence_review_tool.py`, or `backend/evidence/review.py`. The only hits are inside the audit notes themselves (`.omx/research/summary.md`, `.omx/research/t-cell-session-audit-2026-04-02.md`).
- The file URLs in the body resolve against `claude/biology-research-agent-VMsGX`, an unmerged branch — consistent with the review-gate work never landing on `bioAgent`.

So the described ordering bug (`chat.py` serializing `evidence_review` before flipping `context.review_completed = True`) has no call site, no flag, and no gate module to reorder on this branch.

To unblock, could you pick one:

1. Merge the review-gate module from `claude/biology-research-agent-VMsGX` into `bioAgent` first; I'll rebase this issue onto the merged code.
2. Re-scope against what `bioAgent` actually has today — `backend/evidence/review.py` + `backend/tools/evidence_review_tool.py` + `backend/tools/policy_wrappers.py`. If a staleness bug exists here, it will be a different shape (policy-wrapper serialization order rather than a `review_completed` flip in `chat.py`) and the fixture would target that.
3. Close as a duplicate of whatever issue tracks the gate merge on the other branch.
