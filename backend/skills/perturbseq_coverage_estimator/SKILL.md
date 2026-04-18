---
name: perturbseq_coverage_estimator
description: Estimate the cell budget and practical coverage needed for a Perturb-seq design.
category: bio/perturb_seq
version: 1.0
requires_tools: [search_knowledge_base, python_repl]
requires_network: false
user_invocable: true
tags: [perturb-seq, coverage, design, cells, planning]
aliases: [perturbation_coverage_planner]
species: any
modality: perturb_seq
stage: design
stability: stable
safety_level: low
---

# Perturb-seq Coverage Estimator

## Purpose

Estimate how many cells are needed for a Perturb-seq experiment after accounting for targets, controls, replicates, and attrition.

## When to use

Use this skill when the user is planning a screen and needs a first-pass estimate of required cell numbers or analyzable coverage.

## Required inputs

- **number of targets**
- **guides per target**
- **desired cells per perturbation after QC**
- **replicates**
- **controls** (optional but recommended)
- **expected loss rate** (optional)

## Steps

1. Search `knowledge/perturbseq-design-defaults.md` with `search_knowledge_base`.
2. Clarify whether the target is per guide, per gene, or per perturbation group.
3. Use `python_repl` to calculate:
   - perturbation units
   - target analyzable cells
   - total cell budget before QC
   - impact of control arms and replicates
4. State assumptions explicitly, especially any default attrition rate.
5. Give a simple planning recommendation rather than pretending the estimate is exact.

## Output format

- **Assumptions**
- **Coverage table**
- **Estimated total cells needed**
- **Design risks**

## Failure modes

- Missing key numbers: ask the user for targets, replicates, and desired coverage.
- Unclear whether coverage is per guide or per target: ask before calculating.
- Unrealistic requested coverage: say the estimate is likely too costly or impractical.

## Examples

- "Estimate cells needed for 120 targets, 3 guides each, 400 cells per perturbation, 2 replicates."
- "How many cells should I plan for a small pilot Perturb-seq screen?"
