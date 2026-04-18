# BioAPEX Regression Eval Suite

A minimal, file-first eval harness that pins agent behavior on five
canonical biologist tasks. Use it to catch regressions after prompt,
tool, or routing changes.

## Task scenarios

| File                              | Scenario                |
| --------------------------------- | ----------------------- |
| `tasks/literature_lookup.yaml`    | Literature lookup       |
| `tasks/protocol_summarization.yaml` | Protocol summarization  |
| `tasks/gene_protein_lookup.yaml`  | Gene / protein lookup   |
| `tasks/data_file_parsing.yaml`    | Data file parsing       |
| `tasks/multi_step_workflow.yaml`  | Multi-step workflow     |

## Running

The runner treats `backend/` as its Python project root (same convention
as `app.py`). From `backend/`:

```bash
# Validate task YAMLs and produce a stub report — no backend calls, no
# LLM usage. Safe to run in CI.
python -m evals.run_evals --dry-run

# Run all 5 tasks against the live runtime and score with the verifier
# model as judge. Requires DEEPSEEK_API_KEY / OPENAI_API_KEY just like
# the normal chat path.
python -m evals.run_evals

# Run a subset.
python -m evals.run_evals --tasks literature_lookup,gene_protein_lookup

# Pick a different judge (any configured model role).
python -m evals.run_evals --judge-role planner

# Custom output path.
python -m evals.run_evals --output ../reports/eval-$(date +%F).json
```

Reports land under `backend/evals/reports/eval-<timestamp>.json` by
default. The process exit code is non-zero when any task fails the
pass gate (tool-sequence match + error-free run + rubric >= 60% of
max), except in `--dry-run` mode.

### How it wires in

The runner imports `graph.agent.agent_manager` directly and drives
`agent_manager.astream(prompt, [])` per task. Tool names are harvested
in call order from the streamed `tool_start` / `tool_end` events and
matched against the task's `expected_tool_sequence.regex`. Rubric
scoring reuses `runtime.model_factory.build_chat_model(<role>)` — by
default the verifier role, so you can steer the judge using the
existing `BIOAPEX_VERIFIER_*` env overrides without introducing a new
role config.

## YAML schema

Each file under `tasks/` is a single task spec:

```yaml
id: my_task                     # required; lowercase, no spaces
name: Short human-readable name
description: >-
  One or two sentences about what the task measures.
tags: [literature, retrieval]   # optional; free-form labels

input:
  prompt: >-
    The user message to send to the agent.

expected_tool_sequence:
  # Regex matched against the space-joined, ordered tool names the
  # agent called. Tool names come from backend/tools/registry.py
  # (the 15-tool surface: terminal, python_repl, fetch_url, http_json,
  # ncbi_eutils, evidence_retrieval, evidence_review, entity_grounding,
  # plan_agent, verification_agent, uniprot_api, ensembl_api,
  # read_file, write_file, search_knowledge_base).
  regex: "(^|\\b)(ncbi_eutils|evidence_retrieval|fetch_url)(\\b|$)"
  description: Short prose describing the intent of the regex.

rubric:
  - id: returns_specific_papers
    question: >-
      Full rubric question shown to the judge. Be specific enough that
      a reasonable judge with only the user prompt, the final answer,
      and the tool sequence can score it.
    max_score: 5
  - id: topic_alignment
    question: Another rubric question.
    max_score: 5
```

### How the tool-sequence regex is matched

Tool names are collected from the streamed events in the exact order
the agent called them (deduped per run id). They are joined with
single spaces to form a haystack like:

```
plan_agent read_file evidence_retrieval verification_agent
```

The task's `regex` is then applied with `re.search`. That means:

- `"read_file"` matches any run that touches `read_file` at least once.
- `"plan_agent.*verification_agent"` enforces ordering.
- Use `(^|\\b)` / `(\\b|$)` anchors if you need to avoid partial-name
  matches (e.g. `read_file` vs a hypothetical `read_file_meta`).

## How to add a task

1. Drop a new `my_scenario.yaml` into `tasks/`. The runner picks up
   every `.yaml` file in that directory.
2. Fill in the schema above. The `id` can be omitted; it then defaults
   to the filename stem.
3. Sanity-check the spec without calling the backend or any LLM:
   ```bash
   python -m evals.run_evals --dry-run --tasks my_scenario
   ```
   This will raise a descriptive error if the YAML is malformed or the
   regex won't compile.
4. Run it for real once the spec looks right:
   ```bash
   python -m evals.run_evals --tasks my_scenario
   ```
5. Commit the new YAML. No Python changes are needed to add a task.

## Design notes

- **In-process invocation** over HTTP: drives the same
  `agent_manager.astream` used by `/api/chat`, so prompt assembly,
  skill routing, policy wrappers, and helper-agent wiring all exercise
  normally.
- **Tool harvest** uses `tool_start` / `tool_end` rather than the turn
  ledger so the runner does not assume persistence shape.
- **Judge reuse** keeps a single source of truth for model config. If
  you want a dedicated judge model, set `BIOAPEX_VERIFIER_MODEL`,
  `BIOAPEX_VERIFIER_API_KEY`, etc., or pass `--judge-role planner` to
  pick a different configured role.
- **Deterministic runs** are encouraged: set
  `BIOAPEX_DETERMINISTIC_SEED=<int>` before running the suite so both
  the executor and the judge pin temperature to 0.
