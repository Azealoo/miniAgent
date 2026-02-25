---
name: pubmed_search
description: Search PubMed for articles by query; return top N PMIDs with titles, year, journal, and link.
category: bio/literature
version: 1.0
requires_tools: [fetch_url]
requires_network: true
user_invocable: true
---

# PubMed Search

## When to use
User asks for literature search, papers on a topic, or "find papers about X".

## Inputs
- **query**: Search terms (e.g. "Perturb-seq CRISPR single cell")
- **max_results**: Optional; default 10, max 50

## Steps

1. **Build URL**: NCBI E-utilities esearch:
   - `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={query}&retmax={max_results}&retmode=json`
   - URL-encode the query.

2. **Fetch**: Use `fetch_url` with the constructed URL.

3. **Parse**: From JSON response, extract `idlist` (PMIDs) and optionally run efetch for titles/summaries, or use esummary:
   - `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={comma-separated PMIDs}&retmode=json`

4. **Present**: For each article, show PMID, title, year, journal, and link `https://pubmed.ncbi.nlm.nih.gov/{PMID}/`.

## Output format
- Number of results found.
- For each: PMID | Title | Year | Journal | Link

## Failure modes
- No results: report "No articles found for query."
- API error: report the error and suggest refining the query.
