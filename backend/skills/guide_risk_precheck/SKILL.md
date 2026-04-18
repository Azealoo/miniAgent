---
name: guide_risk_precheck
description: Precheck biological and interpretation risks before selecting perturbation targets or guide designs.
category: bio/perturb_seq
version: 1.0
requires_tools: [search_knowledge_base, evidence_review, ensembl_api, ncbi_eutils, python_repl]
requires_network: true
user_invocable: true
tags: [guide, crispr, risk, precheck, perturbation]
aliases: [perturbation_risk_precheck]
species: any
modality: perturb_seq
stage: validation
stability: stable
safety_level: medium
---

# Guide Risk Precheck

## Purpose

Flag major biological and interpretation risks before the user commits to a perturbation target or downstream guide design workflow.

## When to use

Use this skill when the user is considering targets for CRISPR, CRISPRi, CRISPRa, or Perturb-seq and wants an early warning on likely failure modes.

## Required inputs

- **targets**: one or more target genes
- **system**: cell type, species, or model
- **perturbation type** (optional)

## Steps

1. Restate the perturbation system, species, cell context, and target list; say clearly when those assumptions are missing.
2. Use `search_knowledge_base` for local design notes, prior screen guidance, or target-specific warnings.
3. Use `ensembl_api` and `ncbi_eutils` to check gene structure, isoform complexity, prior perturbation context, and biologically plausible failure modes.
4. When public evidence is central to the risk call, run `evidence_review` on the target-plus-system question so supported concerns are separated from speculation.
5. Use `python_repl` to build a compact risk table when comparing multiple targets.
6. Return risks as warnings or hypotheses, not as definitive design failures, and recommend the next validation step before committing to guide design.

## Output format

- **Biological context or assumptions**: species, cell state, perturbation mode, and any inferred system assumptions.
- **Evidence or source basis**: which `search_knowledge_base`, `ensembl_api`, `ncbi_eutils`, and `evidence_review` findings support the warning.
- **Risk table**: Target | Risk type | Why it matters | Support level
- **Caveats or ambiguity**: sparse literature, system mismatch, or unresolved biological uncertainty.
- **Recommended next step**: what to validate experimentally or computationally before guide selection.

## Failure modes

- Very sparse literature: say the precheck is preliminary and avoid overconfident ranking.
- Too little system context: ask the user for cell type, species, or perturbation mode.
- Many targets: summarize the highest-risk ones first and note that the rest need a secondary pass.

## Examples

- "Precheck risks for TOX, NR4A1, and BATF before a Perturb-seq experiment."
- "What could go wrong if I target MYC in activated T cells?"
