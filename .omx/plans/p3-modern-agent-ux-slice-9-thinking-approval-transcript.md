# P3 Modern Agent UX Slice 9 - Thinking Approval Transcript

## Goal

Refine the live BioAPEX turn transcript so thinking and tool activity feel closer to `claude_code_src`: calm sentence-style feedback, shared transcript typography, and a quieter approval surface when compliance requires operator confirmation.

## Scope

- Restyle the live thinking rail from bullet-like rows into sentence-style transcript lines.
- Restyle tool activity to share the same transcript font and tone as the thinking surface.
- Remove the persistent end-of-turn compliance card from the center chat.
- Add an inline approval prompt that can replay approval-required requests under audit.
- Preserve hard compliance blocks as non-overridable.

## Files In Scope

- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/components/chat/TurnActivityFeed.tsx`
- `frontend/src/components/chat/ThoughtChain.tsx`
- `frontend/src/components/session/SessionHistorySummary.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/store.tsx`
- `backend/api/chat.py`
- `frontend/src/components/chat/ChatMessage.test.tsx`
- `frontend/src/test/app-shell.contract.test.tsx`
- `backend/tests/test_compliance_preflight.py`
- `context/current-feature.md`

## Must Do

1. Keep streamed answer behavior intact while making live thinking/tool feedback less list-like.
2. Hide the disruptive persistent compliance card in the center transcript.
3. Add a real in-chat proceed action for `require_approval` turns that carries a message-scoped approval override through the chat request.
4. Keep hard `block` compliance behavior unchanged.
5. Verify the frontend transcript flow and the backend approval contract.

## Verification

- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
- `cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_compliance_preflight.py -q -k "approval_override or public_compliance_override"`

## Done Means

- the live process rail reads like one quiet transcript instead of stacked bullet cards
- approval-required turns can ask the user to proceed inline and replay the original request under audit
- center-chat compliance chrome is quieter without weakening hard-stop safety behavior
