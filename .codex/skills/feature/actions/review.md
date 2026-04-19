# Review Action

read my frontend: http://localhost:3000/
1. Read current-feature.md to understand the goals
2. Read any linked or relevant spec files under `context/features/`
3. Review all code and docs changed for this feature
4. Check goal completion:
   - ✅ fully implemented
   - ◐ partially implemented
   - ❌ missing
5. Run the BioAPEX review checklist:
   - scope control: no unnecessary features or unrelated refactors
   - mission alignment: supports reproducibility, provenance, transparency, safety, or evidence grounding where applicable
   - artifact discipline: durable outputs are files or structured records when the feature needs durable outputs
   - schema quality: new durable data is explicit, typed, and versionable when appropriate
   - workflow clarity: step logic, prerequisites, pass/fail states, and run state are explicit when workflow behavior is involved
   - safety and compliance: risky actions are gated appropriately and not silently executed
   - evidence quality: biology-facing claims are grounded or clearly marked as provisional when relevant
   - backward compatibility: existing session files, SSE contracts, file APIs, and skill loading behavior are preserved unless intentionally changed
   - frontend contract fit: frontend types and UI handling match any new backend payloads or states
   - verification: relevant tests, build checks, linting, or manual flow validation were completed
   - anti-pattern check: the change does not reintroduce any pattern rejected in `docs/anti-patterns.md` (regex-only permissions, single-phase compaction, `bash`/`python_repl` as default execution); cite the doc if you flag one
6. Report findings in this order:
   - blockers
   - important issues
   - minor issues
   - what is already solid
7. Final verdict must be one of:
   - Ready to complete
   - Needs targeted fixes
   - Needs scope clarification
