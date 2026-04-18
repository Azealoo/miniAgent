# Harness-First General Agent Slice

Date: 2026-04-02

## Goal

Push BioAPEX toward a `claude_code_src`-style harness-first runtime without breaking the current app:

- keep ordinary chat turns inside the agent harness by default
- separate planner/verifier model roles from the executor
- keep workflow/protocol data and legacy surfaces as compatibility shims for now, but stop relying on hidden workflow chat-selection state for ordinary sends

## Landed changes

1. Added role-based backend model selection in `backend/runtime/model_factory.py`.
   - executor defaults to DeepSeek
   - planner, verifier, and title roles default to OpenAI

2. Added helper-agent runtime utilities in `backend/runtime/helper_agent_runner.py`.
   - helper tools now consume the runtime manifest instead of a hard-coded tool list
   - planner/verifier prompts include a tool catalog built from manifest metadata

3. Added `plan_agent` and `verification_agent` helper tools and wired them into the runtime tool set.

4. Updated `backend/graph/agent.py` to initialize role-specific models and instruct the executor to use helper agents deliberately.

5. De-emphasized workflow-first chat on the frontend.
   - composer no longer exposes the workflow picker/chip as a primary control
   - default sends now use general-agent mode unless an explicit legacy context supplies `selectedWorkflow`
   - quick-start paths now prime draft prompts without depending on hidden workflow state

6. Kept legacy workflow/request shapes as compatibility shims so existing transcript and workspace surfaces still compile.

## Next recommended slice

Extract more of `backend/api/chat.py` into a real `QueryEngine`-style runtime boundary and move the protocol/workflow branches behind explicit legacy entry points instead of keeping them in the default `/api/chat` hot path.
