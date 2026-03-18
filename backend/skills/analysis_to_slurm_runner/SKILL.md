---
name: analysis_to_slurm_runner
description: Turn an analysis request into a Slurm-ready execution plan with commands, resource assumptions, and job structure.
category: bio/compute
version: 1.0
requires_tools: [search_knowledge_base, slurm_tool, python_repl, write_file]
requires_network: false
user_invocable: true
tags: [slurm, pipeline, execution, hpc, runbook]
aliases: [slurm_analysis_planner]
species: any
modality: compute
stage: reporting
stability: evolving
safety_level: medium
---

# Analysis to Slurm Runner

## Purpose

Translate a biological analysis request into a cluster-oriented run plan, including Slurm assumptions, commands, and a draft script when appropriate.

## When to use

Use this skill when the user wants to move from analysis planning to execution on an HPC cluster.

## Required inputs

- **analysis goal**: what should be run
- **toolchain** (optional): python, R, scanpy, nextflow, custom script
- **resource hints** (optional): GPU, memory, CPUs, wall time
- **output path** (optional): where a script should be saved

## Steps

1. Search local compute or pipeline guidance with `search_knowledge_base`.
2. Infer the likely resource profile from the requested analysis.
3. Use `python_repl` to organize the run plan if needed.
4. If a script is requested, draft a Slurm script or execution note using `write_file`.
5. Use `slurm_tool` only if the user explicitly wants to inspect cluster status or submit a job.

## Output format

- **Run plan**
- **Resource assumptions**
- **Suggested command structure**
- **Optional script path**

## Failure modes

- Missing execution details: provide a conservative template and list assumptions.
- Unknown pipeline: ask the user what script or entrypoint should be run.
- Unsafe submission request: do not submit without the user's clear instruction.

## Examples

- "Turn this scanpy workflow into a Slurm run plan."
- "Prepare a cluster script for a perturb-seq analysis job with 16 CPUs and 128G memory."
