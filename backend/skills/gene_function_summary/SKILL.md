---
name: gene_function_summary
description: Get a short summary of gene function from UniProt/NCBI Gene and related pathways.
category: bio/literature
version: 1.0
requires_tools: [fetch_url]
requires_network: true
user_invocable: true
---

# Gene Function Summary

## When to use
User asks what a gene does, or for a brief summary of a gene's function and pathways.

## Inputs
- **gene**: Gene symbol or name (e.g. TP53, BRCA1)

## Steps

1. **UniProt**: Fetch from UniProt REST:
   - `https://rest.uniprot.org/uniprotkb/search?query=gene_exact:{gene}&format=json&fields=gene_names,protein_name,function,organism_name`
   - Parse first hit: protein name, function, organism.

2. **NCBI Gene** (if needed): If UniProt returns little, try:
   - `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gene&term={gene}[sym]&retmode=json` then efetch for description.

3. **Summarize**: Combine into 2–4 sentences: name, main function, organism, and optionally pathway/key terms.

## Output format
- Gene symbol
- Protein name
- Brief function (2–4 sentences)
- Organism
- Optional: pathway or process keywords

## Failure modes
- Gene not found: say "No summary found for {gene}. Check symbol."
- Multiple species: default to human or state organism.
