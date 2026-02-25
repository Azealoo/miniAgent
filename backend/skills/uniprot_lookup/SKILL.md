---
name: uniprot_lookup
description: Fetch protein entry from UniProt by ID or gene name (function, domains, organism).
category: bio/literature
version: 1.0
requires_tools: [fetch_url]
requires_network: true
user_invocable: true
---

# UniProt Lookup

## When to use
User asks for protein info: function, domains, organism, or UniProt ID.

## Inputs
- **query**: UniProt ID (e.g. P53_HUMAN) or gene name (e.g. TP53).

## Steps

1. **Search**: If gene name: `https://rest.uniprot.org/uniprotkb/search?query=gene_exact:{gene}&format=json`. If ID: direct fetch by ID.

2. **Parse**: protein_name, function, organism, optional domains/features. Extract first entry if multiple.

3. **Present**: Entry ID, name, function, organism, and optional link.

## Output format
- Entry ID, protein name, function, organism, link
