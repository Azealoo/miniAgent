# Data and Pipeline Conventions (hrbomics / miniAgent)

## Directory layout (project root)
- **data/**: Raw or processed datasets (e.g. norman, gene2go, essential_all_data_pert_genes.pkl). Large files may live here on GPFS.
- **artifacts/**: Durable workflow, evidence, compliance, QA, and provenance outputs under `artifacts/<workflow>/<YYYY-MM-DD>/<run_id>/`.
- **predictions/**: Output of prediction pipelines (e.g. GEARS predictions).
- **norman_seed2/**: Model directory for GEARS/norman-style models.
- **tmp/**: Temporary files and job scratch (e.g. Slurm TMPDIR). Clean periodically.
- **miniAgent/backend/**: Backend code; **backend/knowledge/** holds curated docs and **knowledge/cache/** holds cached fetched content (e.g. PubMed, UniProt).

## Artifact layout
- Each execution-oriented run should reserve a directory of the form `artifacts/<workflow>/<YYYY-MM-DD>/<run_id>/`.
- `run_id` uses the canonical format `run-YYYYMMDDTHHMMSSZ-xxxxxxxx`.
- Each prepared run directory should materialize a root `run.json` record plus `content_hashes.json`.
- User-supplied files belong under `inputs/user/`; generated files belong under `outputs/generated/` unless they are one of the reserved stable artifact names.
- Stable artifact names include `dataset_manifest.yaml`, `workflow_plan.json`, `compliance_report.json`, `evidence_card.yaml`, `protocol_run.yaml`, `qa_report.json`, `checklist_results.json`, `prov.json`, and `ro-crate/`.

## Running jobs (Slurm)
- Use `sbatch` with appropriate partition and resources (GPU, CPU, memory, time).
- Set `TMPDIR` and `UV_CACHE_DIR` to project or scratch paths for large runs.
- Example: see project-level `gears_predictions_official.sh` for GEARS prediction job template.

## Paths for the agent
- **read_file**: Paths are relative to backend directory (project root for miniAgent is the backend folder). Allowed roots include backend and repo root (for .agents/skills).
- **write_file**: Only paths under `memory/`, `skills/`, and `knowledge/` are allowed.
- **/api/files**: May read under `artifacts/` for inspection, but does not allow writes there.
- **search_knowledge_base**: Indexes `backend/knowledge/` (including `knowledge/cache/`). Add Markdown or text files there for retrieval.
- **terminal**: Commands run with CWD = backend directory. Use absolute or project-relative paths for data (e.g. ../data) when needed.

## Caching online lookups
- Use the **cache_to_knowledge** skill to save PubMed abstracts, gene summaries, or other fetched content to `knowledge/cache/<source>/<id>.md`. These will be searchable after the knowledge index is built or rebuilt.
