---
name: paralog_redundancy_check
description: Check whether paralogs or compensatory family members may weaken interpretation of a perturbation target.
category: bio/perturb_seq
version: 1.0
requires_tools: [ensembl_api, uniprot_api, ncbi_eutils, python_repl]
requires_network: true
user_invocable: true
tags: [paralog, redundancy, compensation, target-risk]
aliases: [paralog_check, compensation_check]
species: any
modality: perturb_seq
stage: interpretation
stability: evolving
safety_level: medium
---

# Paralog Redundancy Check

## Purpose

Assess whether a perturbation target has paralogs or compensatory family members that could reduce the apparent phenotype.

## When to use

Use this skill when the user wants to understand why a knockout or knockdown may show a weak phenotype, or when screening candidate targets before perturbation.

## Required inputs

- **target genes**
- **species**
- **context** (optional): cell type, phenotype, perturbation type

## Steps

1. Use `ensembl_api` and `uniprot_api` to identify related family members or paralog context when available.
2. Use `ncbi_eutils` to look for literature about redundancy, compensation, or family-level perturbation behavior.
3. Use `python_repl` to assemble a concise table across targets if needed.
4. Explain whether redundancy is a likely concern, a plausible concern, or unsupported.
5. Suggest what the user may need next, such as combined targeting or more careful validation.

## Output format

- **Target assessment**
- **Potential compensatory genes**
- **Interpretation risk**
- **Suggested follow-up**

## Failure modes

- Weak annotation support: say that redundancy is only speculative.
- Missing species: ask the user to specify it.
- No clear paralog evidence: say so rather than inventing family relationships.

## Examples

- "Could paralog redundancy explain a weak phenotype for SOCS1 perturbation?"
- "Check compensation risk for these kinase targets in mouse T cells."
