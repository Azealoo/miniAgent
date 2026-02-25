---
name: run_pipeline_safely
description: Propose safe commands and directory hygiene for running a pipeline.
category: bio/hpc
version: 1.0
requires_tools: [terminal, read_file]
requires_network: false
user_invocable: true
---

# Run Pipeline Safely

## When to use
User wants to run a bioinformatics pipeline or script and needs safe commands and directory setup.

## Inputs
- **pipeline**: Name or path (e.g. "GEARS", "nextflow rnaseq").
- **input_path**, **output_path**: Optional; or user describes.

## Steps

1. **Clarify**: Identify input/output dirs and whether they are on shared storage (e.g. GPFS). Prefer output to a project or scratch dir, not home if large.

2. **Hygiene**: Suggest:
   - Create output directory with mkdir -p.
   - Use absolute or project-relative paths.
   - Avoid overwriting without confirmation; suggest dated or versioned output.

3. **Command**: Propose the run command (e.g. nextflow run ..., python main.py ...). Do not execute destructive commands; only suggest.

4. **Checklist**: Short list: (1) Output dir exists, (2) Paths checked, (3) Resource (slurm) if needed.

## Output format
- Suggested commands (as text, not executed unless user confirms)
- Directory checklist
- One-line safety reminder
