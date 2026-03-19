# Test Action

1. Read current-feature.md to understand what was implemented
2. Determine what kind of change it is:
   - backend logic or API change
   - frontend UI/state change
   - schema or artifact change
   - workflow or execution change
   - docs-only change
3. Run the most relevant verification for this repo:
   - backend: targeted `pytest` or relevant backend tests
   - frontend: `cd frontend && npm run build`
   - frontend lint when appropriate: `cd frontend && npm run lint`
   - manual flow checks for chat streaming, workflow state, artifact creation, or compliance behavior when needed
4. If the feature introduces testable backend logic and there are no tests yet, add focused tests where appropriate
5. Report exactly what was verified, what passed, and anything not tested
