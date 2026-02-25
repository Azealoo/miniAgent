---
name: gene_set_enrichment
description: Run or interpret gene set enrichment (Enrichr/g:Profiler) and summarize results.
category: bio/scRNA
version: 1.0
requires_tools: [fetch_url, python_repl]
requires_network: true
user_invocable: true
---

# Gene Set Enrichment

## When to use
User has a list of genes (e.g. DE genes) and wants enrichment against GO, KEGG, Reactome, or similar.

## Inputs
- **gene_list**: Comma- or newline-separated gene symbols.
- **background** (optional): Background set or "human"/"mouse".

## Steps

1. **Normalize**: Parse gene list into a clean list (max ~500 for API limits).

2. **Enrichr**: Use Enrichr API if available:
   - POST genes to `https://maayanlab.cloud/Enrichr/addList` then GET results from `https://maayanlab.cloud/Enrichr/enrich` with ontology (e.g. GO_Biological_Process_2021, KEGG_2021_Human).

3. **Or g:Profiler**: `fetch_url` to g:Profiler API with gene list and sources (GO, KEGG, REAC).

4. **Parse**: Extract top 10–15 terms: term name, p-value, adjusted p-value, genes overlapping.

5. **Interpret**: One paragraph summary: what biological processes/pathways are enriched and what that suggests.

## Output format
- Table: Term | p-value | adj. p-value | overlapping genes
- Short interpretation paragraph

## Failure modes
- API down: suggest offline tools (clusterProfiler, etc.) or retry later.
- Too many genes: suggest splitting or sampling.
