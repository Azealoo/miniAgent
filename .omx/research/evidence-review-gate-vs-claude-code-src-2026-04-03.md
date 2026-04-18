# Evidence Review Gate vs Claude Code Source

Date: 2026-04-03

## Question

Should BioAPEX keep the current user-facing evidence-review branch (`review_first` vs `skip_review`) if the product goal is to stay clean and mimic `ponponon/claude_code_src` as closely as practical?

## Repo Truth

- BioAPEX currently runs a deterministic `evidence_review_gate` before ordinary answering.
- When the gate decides review is required, it sets `user_choice_required: true`.
- The runtime then blocks the turn until the user chooses either `review_first` or `skip_review`.
- The frontend renders those two buttons and replays the same request with an override payload.

Primary local anchors:

- `backend/evidence/review_gate.py`
- `backend/runtime/query_engine.py`
- `backend/api/chat.py`
- `frontend/src/components/chat/ChatMessage.tsx`
- `frontend/src/lib/api.ts`

## External Repo Truth

Primary-source inspection of `ponponon/claude_code_src` on 2026-04-03 showed:

- Its permission system is tool-safety oriented, not answer-domain oriented.
- `src/Tool.ts` centers permission checks in each tool contract via `checkPermissions`, `isReadOnly`, `isDestructive`, and related fields.
- `src/hooks/useCanUseTool.tsx` resolves permission decisions around tool execution (`allow`, `deny`, `ask`), then shows an interactive permission dialog only when a tool actually needs approval.
- `src/tools/AgentTool/builtInAgents.ts` keeps helper agents optional and feature-scoped.
- The built-in `verification` agent exists, but is feature-flagged and added only under a gated condition instead of being a universal per-turn branch.
- The built-in `Plan` and `verification` agents are read-only helper roles, not domain-specific user-choice routes inserted ahead of normal answering.
- No analogous biology-domain `review_first` / `skip_review` branch or evidence-review permission prompt was found in the inspected source surface.

## Comparison

BioAPEX's evidence-review prompt is not structurally similar to the reference implementation.

The Claude Code source does prompt for permissions, but those prompts are attached to risky tool execution. BioAPEX's evidence-review prompt is attached to a content-policy branch for a class of biology questions, even when no dangerous tool action is being requested. That makes it feel heavier and less clean than the reference.

## Recommendation

If the goal is to stay close to the Claude Code source style, do **not** keep the current user-choice evidence-review gate as the default path.

Best fit:

1. Keep evidence review as an internal capability.
2. Trigger it automatically when your product policy requires it.
3. Surface the result as process activity or provenance, not as a blocking fork asking the user to pick a route.

If you still want a user-visible choice, make it explicit user intent only:

- user asks for a quick answer
- user asks for a reviewed / source-grounded answer

That is cleaner than forcing the branch for broad biology questions.

## Decision

For a Claude-Code-like architecture, the current `review_first` / `skip_review` gate should be removed or narrowed sharply. Keep the review engine; remove the forced user-choice UX.

## Sources

- https://github.com/ponponon/claude_code_src
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/Tool.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/hooks/useCanUseTool.tsx
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools/AgentTool/builtInAgents.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools/AgentTool/built-in/planAgent.ts
- https://github.com/ponponon/claude_code_src/blob/adb321f6a3af4e0b76a1e076168bd521e9ba20af/src/tools/AgentTool/built-in/verificationAgent.ts
