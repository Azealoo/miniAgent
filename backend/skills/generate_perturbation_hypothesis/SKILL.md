---
name: generate_perturbation_hypothesis
description: Generate candidate perturbation hypotheses (targets, mechanism, expected signature, experiment plan) for a given biological context and phenotype goal.
category: bio/perturbation
version: 1.0
requires_tools: [search_knowledge_base, ncbi_eutils, uniprot_api, fetch_url, python_repl, write_file]
requires_network: true
user_invocable: true
---

# Generate Perturbation Hypothesis

## Purpose
Given a biological context (cell type, condition, phenotype goal), produce structured, evidence-backed hypotheses for what gene perturbations to try.

## When to use
User asks: "What should we perturb to achieve X?", "Suggest perturbations for Y cell type to induce Z", or "Generate hypotheses for our Perturb-seq experiment."

## Required inputs
- **cell_type**: Cell type or model (e.g. "CD4+ T cells", "K562", "iPSC-derived neurons").
- **goal**: Phenotype or transcriptional goal (e.g. "induce apoptosis", "block cell cycle entry", "activate interferon response").
- **constraints** (optional): Available methods (e.g. "CRISPR KO", "CRISPRi", "overexpression"), any targets to avoid, budget.
- **markers** (optional): Known DE markers or pathway hits that contextualize the goal.

---

## Steps

### Step 1 — Gather prior knowledge from knowledge base
Use `search_knowledge_base` with queries about the cell type, phenotype, and known perturbations:
- Query 1: "{cell_type} {goal}"
- Query 2: "{goal} perturbation target"
- Query 3: "Perturb-seq {cell_type}" or relevant pathway

Note any relevant lab SOPs, past results, or known targets from local knowledge.

### Step 2 — Literature mining (PubMed/NCBI)
Use `ncbi_eutils` (esearch, db=pubmed) to find relevant papers:
- Query: "{cell_type} {goal} CRISPR perturbation"
- Retrieve top 5–10 PMIDs (esearch retmax=10).
- Optionally use esummary to get titles and extract candidate gene names mentioned.

### Step 3 — Pathway and gene annotation
For each candidate target:
1. Use `uniprot_api` to confirm it is a known protein in the relevant organism.
2. Use `ncbi_eutils` (esearch db=gene) if gene info needed.
3. Optionally use `fetch_url` to Reactome or Enrichr to confirm pathway membership.

### Step 4 — Score and rank candidates
Use `python_repl` to build a simple scoring table:
- **Evidence score**: 1 = known from local knowledge, 2 = found in literature, 3 = both.
- **Druggability/perturbability**: 1 = no known tool, 2 = CRISPRi/KO feasible, 3 = drugs available.
- **Pathway relevance**: 1 = indirect, 2 = same pathway, 3 = direct regulator of goal.
- **Rank**: Sum of scores. Present top 3–5 candidates.

### Step 5 — Build structured hypothesis report
For each top candidate, produce a structured block:

```
## Hypothesis: Perturb {GENE}
- **Rationale**: Why this target relates to the goal.
- **Mechanism**: Proposed mechanism linking perturbation to phenotype.
- **Expected signature**: What transcriptional changes to expect (directionality, key genes).
- **Recommended perturbation type**: KO / CRISPRi / OE / drug (with brief justification).
- **Controls**: Non-targeting control; optionally known positive control (e.g. a well-characterized perturbation of same pathway).
- **Readouts**: Key genes or pathways to measure; assay suggestions.
- **Risks and caveats**: Off-targets, cell-type specificity, redundancy.
- **Supporting evidence**: PMID(s) or knowledge base source.
```

### Step 6 — Optional: save hypothesis report
If user wants to save, use `write_file` to `knowledge/hypotheses/{cell_type}_{goal}_{timestamp}.md` with the full report (replacing spaces/special chars in filename).

---

## Output format
- **Summary**: One paragraph on the goal and approach.
- **Candidate table**: Gene | Evidence score | Mechanism | Perturbation type | Risk level.
- **Detailed hypothesis blocks**: One per top candidate (Step 5 format).
- **Next steps**: Suggest running golden task GT-S1 (QC) + `perturbation_signature_compare` after the experiment.

---

## Failure modes
- No literature found: Report "No PubMed results for query; hypotheses based on local knowledge only."
- Unknown cell type: Proceed with general knowledge; flag uncertainty.
- Too broad a goal: Ask user to narrow the phenotype (e.g. "induce apoptosis via intrinsic pathway").
