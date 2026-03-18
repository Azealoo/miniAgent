---
name: guide_risk_precheck
description: Precheck biological and interpretation risks before selecting perturbation targets or guide designs.
category: bio/perturb_seq
version: 1.0
requires_tools: [ensembl_api, ncbi_eutils, search_knowledge_base, python_repl]
requires_network: true
user_invocable: true
tags: [guide, crispr, risk, precheck, perturbation]
aliases: [perturbation_risk_precheck]
species: any
modality: perturb_seq
stage: validation
stability: evolving
safety_level: medium
---

# Guide Risk Precheck

## Purpose

Flag major biological and interpretation risks before the user commits to a perturbation target or downstream guide design workflow.

## When to use

Use this skill when the user is considering targets for CRISPR, CRISPRi, CRISPRa, or Perturb-seq and wants an early warning on likely failure modes.

## Required inputs

- **targets**: One or more target genes
- **system**: cell type, species, or model
- **perturbation type** (optional)

## Steps

1. Search local knowledge for any relevant design notes or target-specific warnings.
2. Use `ensembl_api` to inspect gene structure or related annotation if helpful.
3. Use `ncbi_eutils` to look for common risk signals such as:
   - essentiality or toxicity concerns
   - isoform complexity
   - known compensatory pathways
   - context-specific effects
4. Use `python_repl` to build a compact risk table if multiple targets are being reviewed.
5. Return risks as hypotheses or warnings, not as definitive design failures.

## Output format

- **Risk table**: Target | Risk type | Why it matters | Confidence
- **Best candidates to move forward**
- **Targets that need extra caution**

## Failure modes

- Very sparse literature: say the precheck is preliminary.
- Too little system context: ask the user for cell type or species.
- Many targets: summarize the highest-risk ones first.

## Examples

- "Precheck risks for TOX, NR4A1, and BATF before a Perturb-seq experiment."
- "What could go wrong if I target MYC in activated T cells?"
