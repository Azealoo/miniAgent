# P8 Process-First Streaming Output And Frontend Runtime Alignment Verification Map

Date: 2026-04-02
Status: future phase after `P7`

## Verification Policy

- Keep the process-first transcript policy explicit in every slice.
- Verify parser, reducer, and display behavior separately before doing broad sweep runs.
- Keep backend and frontend stream-contract checks paired when a slice changes both sides.

## Slice Matrix

### Slice 1: Typed Stream Event Contract

- Primary checks:
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- Review focus:
  - complete typed event coverage
  - no silently ignored `plan` or `verification` events
  - parser remains resilient to malformed SSE chunks

### Slice 2: Optimistic Stream Reducer

- Primary checks:
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts src/test/app-shell.contract.test.tsx`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- Review focus:
  - one reducer path for optimistic assistant turns
  - preserved `new_response` behavior
  - no request-id or pending-tool regressions

### Slice 3: Live Process Rail Completeness

- Primary checks:
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- Review focus:
  - process-first rail remains above the answer
  - live `plan` and `verification` blocks appear correctly
  - approval and evidence-review prompts still fit the layout

### Slice 4: Shared Block Normalization Across Surfaces

- Primary checks:
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
- Review focus:
  - live, completed, and reloaded turns share the same block semantics
  - no duplicate fallback derivation logic left in major surfaces

### Slice 5: Narrow Backend Stream Contract Hardening

- Primary checks:
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_runtime_query_engine.py -q`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts`
- Review focus:
  - stable event payload shape
  - optional event-index semantics if added
  - no unnecessary transport complexity

### Slice 6: Final Polish And Regression Closeout

- Primary checks:
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/lib/api.stream-chat.test.ts src/components/chat/ChatMessage.test.tsx src/components/editor/TurnDetailsPanel.test.tsx src/test/app-shell.contract.test.tsx`
  - `cd frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck`
  - `cd backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_chat_streaming.py tests/test_runtime_query_engine.py -q`
- Review focus:
  - parser, reducer, and renderer agree on one stream story
  - process-first transcript policy still holds
  - frontend/backend event contract stays coherent

## Phase Completion Check

Before calling `P8` ready:

- the frontend has a typed live stream-event grammar
- `plan_created`, `plan_updated`, and `verification_result` render live
- optimistic assistant updates go through one reducer path
- chat and inspector surfaces derive blocks consistently
- SSE remains the transport, but not the primary mental model
- focused frontend and backend streaming checks are green
