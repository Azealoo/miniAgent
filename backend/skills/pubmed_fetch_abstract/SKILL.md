---
name: pubmed_fetch_abstract
description: Fetch and summarize a PubMed article by PMID (abstract, key methods, key findings).
category: bio/literature
version: 1.0
requires_tools: [fetch_url]
requires_network: true
user_invocable: true
---

# PubMed Fetch Abstract

## When to use
User provides a PMID or asks for the abstract/summary of a specific paper.

## Inputs
- **pmid**: PubMed ID (e.g. 12345678)

## Steps

1. **Fetch**: Use `fetch_url` with:
   - `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={pmid}&retmode=xml` or `rettype=abstract`

2. **Parse**: Extract title, authors, journal, year, abstract text from XML/response.

3. **Summarize**: Provide:
   - Full citation (title, authors, journal, year)
   - Abstract (full or first ~500 chars if very long)
   - Optional: 1–2 sentences on key methods and key findings.

4. **Link**: Include `https://pubmed.ncbi.nlm.nih.gov/{pmid}/`.

## Output format
- Citation block
- Abstract
- Key methods / findings (brief)
- URL

## Failure modes
- Invalid or missing PMID: report "Article not found."
- Parse error: return raw abstract if available.
