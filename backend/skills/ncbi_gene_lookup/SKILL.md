---
name: ncbi_gene_lookup
description: Look up gene description and location via NCBI Gene (esearch/efetch).
category: bio/literature
version: 1.0
requires_tools: [fetch_url]
requires_network: true
user_invocable: true
---

# NCBI Gene Lookup

## When to use
User asks for gene info (symbol, description, chromosome, organism) from NCBI.

## Inputs
- **gene**: Gene symbol (e.g. BRCA1) or organism plus symbol.

## Steps

1. **Search**: `fetch_url` to esearch.fcgi db=gene, term="{gene}[sym]", retmode=json. Get id list.

2. **Fetch**: efetch.fcgi db=gene id={id} retmode=xml or json. Parse description, chromosome, organism, type (protein-coding etc.).

3. **Present**: Gene symbol, official name, description, organism, chromosome/position, and link to NCBI Gene.

## Output format
- Symbol, name, description, organism, location, link
