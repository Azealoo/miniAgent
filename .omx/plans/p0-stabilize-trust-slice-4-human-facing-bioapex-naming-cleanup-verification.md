# P0 Stabilize Trust - Slice 4 - Verification

## Required Coverage In The Slice

- human-facing naming cleanup coverage for `README.md` and `backend/workspace/IDENTITY.md`
- explicit compatibility verification that protected runtime/package/header identifiers remain unchanged

## Verification Commands

1. `cd /gpfs/projects/hrbomics/miniAgent && rg -n 'miniOpenClaw|\bClaw\b' README.md backend/workspace/IDENTITY.md`
Purpose: confirm the touched human-facing docs/prompt no longer contain the legacy names.
Expected result: no matches.

2. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_api_health.py -q -k 'health_returns_ok'`
Purpose: confirm root health compatibility remains `{"status": "ok", "service": "miniOpenClaw"}`.

3. `cd /gpfs/projects/hrbomics/miniAgent/backend && /gpfs/home/yininz6/.conda/envs/miniAgent/bin/python -m pytest tests/test_tools.py -q -k 'test_fetch_json_endpoint'`
Purpose: confirm the fetch-tool compatibility path still preserves the existing `miniOpenClaw` user-agent expectation.

4. `cd /gpfs/projects/hrbomics/miniAgent && rg -n 'miniOpenClaw|mini-openclaw' backend/app.py backend/tools/fetch_url_tool.py frontend/package.json frontend/package-lock.json backend/tests/test_api_health.py backend/tests/test_tools.py`
Purpose: confirm the protected machine-facing compatibility surfaces still intentionally retain their legacy identifiers.
Expected result: matches only in those protected files.

## Exit Criteria

- command 1 returns no matches
- commands 2 and 3 pass
- command 4 shows the preserved legacy identifiers only in the protected compatibility surfaces
- no unplanned machine-facing contract or package-identity changes land in the slice
