---
name: slurm_job_template
description: Generate an sbatch script template for GPU or CPU jobs (Slurm).
category: bio/hpc
version: 1.0
requires_tools: [python_repl, write_file]
requires_network: false
user_invocable: true
---

# Slurm Job Template

## When to use
User needs a Slurm sbatch script for a compute job (e.g. Python, R, nextflow) with GPU or CPU.

## Inputs
- **job_name**: Job name for SBATCH.
- **gpus**: Number of GPUs (0 for CPU-only).
- **cpus**: CPUs per task (e.g. 8).
- **mem**: Memory (e.g. 32G, 200G).
- **time**: Time limit (e.g. 02:00:00).
- **script_body**: Optional; command or script to run (e.g. "python train.py").

## Steps

1. **Gather**: Get job name, partition/qos if known, GPU count, CPU count, memory, time, and main command.

2. **Template**: Use `python_repl` to build sbatch lines:
   - #SBATCH --job-name=...
   - #SBATCH --gpus=... (if >0)
   - #SBATCH --cpus-per-task=...
   - #SBATCH --mem=...
   - #SBATCH --time=...
   - #SBATCH --output=... #SBATCH --error=...
   - Optional: module load, conda activate, then script_body.

3. **Output**: Print the full script. Optionally use `write_file` to save under `knowledge/` or user-specified path if they ask.

4. **Remind**: Note that they should edit paths and commands before submitting.

## Output format
- Complete sbatch script
- One-line reminder to customize and submit with sbatch
