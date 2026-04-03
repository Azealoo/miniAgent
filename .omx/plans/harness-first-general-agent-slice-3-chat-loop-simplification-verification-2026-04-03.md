# Harness-First General Agent Slice 3 Verification

Date: 2026-04-03

## Focused verification

Backend targeted:

```bash
cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_runtime_query_engine.py tests/test_chat_streaming.py tests/test_tool_policy.py tests/test_compliance_preflight.py -q
```

Frontend targeted:

```bash
cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm test -- src/components/chat/ChatMessage.test.tsx src/test/app-shell.contract.test.tsx
```

Frontend typecheck:

```bash
cd /gpfs/projects/hrbomics/miniAgent/frontend && PATH=/gpfs/home/yininz6/.conda/envs/miniAgent/bin:$PATH /gpfs/home/yininz6/.conda/envs/miniAgent/bin/npm run typecheck
```

## Exit conditions

- no backend test still assumes ordinary chat runs `compliance_preflight` first
- no frontend contract test still assumes approval replay is available from chat
- typecheck remains green after request/prop removal

## Results

- 2026-04-03: backend targeted suite passed (`40 passed`)
- 2026-04-03: frontend targeted `ChatMessage` and app-shell contract tests passed earlier in this slice
- 2026-04-03: frontend typecheck passed earlier in this slice
