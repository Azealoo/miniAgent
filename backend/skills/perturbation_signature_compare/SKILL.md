---
name: perturbation_signature_compare
description: Compare gene signatures across perturbations and suggest clustering or grouping.
category: bio/perturbation
version: 1.0
requires_tools: [read_file, python_repl]
requires_network: false
user_invocable: true
---

# Perturbation Signature Compare

## When to use
User has multiple perturbation signatures (e.g. DE lists or effect sizes per gene per perturbation) and wants to compare or group them.

## Inputs
- **signatures**: Path(s) to table(s) or user-described format (perturbation × gene × score/FC).
- **method**: "correlation", "overlap", or "both".

## Steps

1. **Load**: If paths given, use `read_file`; otherwise ask for a matrix or list of (perturbation, gene, score) triples.

2. **Structure**: Build a perturbation × gene matrix (e.g. log2FC or binary DE).

3. **Compare**: Use `python_repl` to compute:
   - Pairwise correlation between perturbations (across genes), or
   - Jaccard overlap of top-N genes per perturbation.

4. **Cluster**: Suggest grouping (e.g. "perturbations A and B are similar; C is distinct") and optionally suggest visualization (heatmap, dendrogram).

5. **Summarize**: Table or list of similar pairs/groups and one-sentence biological interpretation.

## Output format
- Similarity matrix or pairwise list
- Suggested groups
- Optional: heatmap command or code snippet
