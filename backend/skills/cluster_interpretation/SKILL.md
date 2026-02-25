---
name: cluster_interpretation
description: Interpret scRNA clusters using marker genes and suggest cell type or state.
category: bio/scRNA
version: 1.0
requires_tools: [read_file, python_repl, fetch_url]
requires_network: false
user_invocable: true
---

# Cluster Interpretation

## When to use
User has cluster IDs and marker genes (or a table) and wants biological interpretation (cell type or state).

## Inputs
- **markers**: Path to marker table or pasted list (cluster, gene, score/FC).
- **organism**: Optional (human/mouse).

## Steps

1. **Load**: Read marker table or parse user message. Get top genes per cluster.

2. **Interpret**: For each cluster, list top markers and suggest cell type or state (e.g. "T cells", "cycling", "stress") using prior knowledge. Optionally use `fetch_url` to check gene function if needed.

3. **Present**: Table or list: Cluster | Top markers | Suggested identity | Confidence (high/medium/low).

4. **Caveats**: Note that interpretation is suggestive; validation (e.g. known markers, GO) can strengthen.

## Output format
- Per-cluster: markers, suggested identity, confidence
- Short caveat
