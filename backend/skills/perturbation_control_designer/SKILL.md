---
name: perturbation_control_designer
description: Suggest a control strategy for perturbation experiments, including non-targeting, positive, and interpretation controls.
category: bio/perturb_seq
version: 1.0
requires_tools: [search_knowledge_base, ncbi_eutils, python_repl]
requires_network: true
user_invocable: true
tags: [controls, perturbation, perturb-seq, experimental-design]
aliases: [control_strategy_builder]
species: any
modality: perturb_seq
stage: design
stability: evolving
safety_level: medium
---

# Perturbation Control Designer

## Purpose

Build a control strategy for perturbation experiments so that screen results are easier to interpret and validate.

## When to use

Use this skill when the user is designing a CRISPR, CRISPRi, CRISPRa, or Perturb-seq experiment and wants to know which controls to include.

## Required inputs

- **perturbation type**
- **biological question**
- **system**: cell type, species, or model
- **known target class** (optional)

## Steps

1. Search local references with `search_knowledge_base` for any lab-specific control expectations.
2. Use `ncbi_eutils` to look for representative positive controls when needed.
3. Organize controls into categories:
   - non-targeting controls
   - positive controls
   - pathway or phenotype-specific interpretation controls
   - process controls if needed
4. Use `python_repl` only if a small design table helps.
5. State what each control helps the user learn.

## Output format

- **Control categories**
- **Recommended examples**
- **Why each control matters**
- **Main caveats**

## Failure modes

- Too broad a biological question: provide a general control framework and say that the exact positive control depends on the pathway.
- No good literature-backed positive control found: say so explicitly.
- Very unusual system: return a conservative control set and note the uncertainty.

## Examples

- "What controls should I include for a Perturb-seq screen of T-cell exhaustion regulators?"
- "Design controls for a CRISPRi experiment targeting interferon signaling genes."
