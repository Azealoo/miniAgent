---
name: critique_hypothesis
description: Critically evaluate a perturbation hypothesis — challenge assumptions, propose negative controls, and flag confounders.
category: bio/perturbation
version: 1.0
requires_tools: [search_knowledge_base, ncbi_eutils, fetch_url, python_repl]
requires_network: true
user_invocable: true
---

# Critique Hypothesis

## Purpose
Challenge an existing perturbation hypothesis (from `generate_perturbation_hypothesis` or user-provided) to improve experimental rigor.

## When to use
User says "critique this hypothesis", "what could go wrong with this experiment?", or "play devil's advocate."

## Inputs
- **hypothesis**: Text of the hypothesis (pasted or from previous skill output).
- **target_gene** (optional): Gene being perturbed.
- **cell_type** (optional): Cell type used.

---

## Steps

### Step 1 — Identify key assumptions
Read the hypothesis and list the major assumptions:
1. That the gene is the primary driver of the phenotype.
2. That the perturbation method achieves complete loss/gain of function.
3. That the phenotype is specific to this perturbation (no broad toxicity).
4. That the cell type/model is appropriate.

### Step 2 — Literature check for contradictions
Use `ncbi_eutils` (esearch db=pubmed) to search for:
- "{gene} {cell_type} off-target effect"
- "{gene} redundant paralog"
- "{gene} essential gene toxicity"

Retrieve titles; flag any papers that contradict or complicate the hypothesis.

### Step 3 — Local knowledge check
Use `search_knowledge_base` for lab notes, past failed experiments, or known cell-line quirks.

### Step 4 — Structured critique
For each assumption, write a brief challenge:

```
## Challenge: {Assumption}
- **What could go wrong**: Specific risk (off-target, redundancy, toxicity, indirect effect).
- **Evidence**: PMID or local source, or "not found in literature."
- **Mitigation**: How to address this (e.g. rescue experiment, paralog knockout, dose titration).
```

### Step 5 — Negative controls
Propose negative controls:
- Non-targeting sgRNA (essential baseline).
- Perturbation of a gene in the same pathway but with an opposite expected phenotype.
- A second guide RNA targeting the same gene (to rule out on-target guide effects).

### Step 6 — Confounders to watch
- Cell cycle effects (perturbing cell cycle regulators creates indirect transcriptional changes).
- Batch effects if multiple guides are pooled.
- MOI (multiplicity of infection) if viral delivery.
- Guide efficiency variation (measure KO efficiency by Western or sequencing).

---

## Output format
- **Assumption list**: Numbered.
- **Per-assumption challenge**: As in Step 4 format.
- **Negative controls table**: Control | Purpose.
- **Confounders list**: Bullet list.
- **Verdict**: "Strong hypothesis with caveats", "Moderate — needs more evidence", or "Weak — reconsider target."
