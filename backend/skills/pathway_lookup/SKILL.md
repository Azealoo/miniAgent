---
name: pathway_lookup
description: Look up pathway or GO/Reactome/KEGG term definitions and key genes.
category: bio/literature
version: 1.0
requires_tools: [fetch_url, search_knowledge_base]
requires_network: true
user_invocable: true
---

# Pathway Lookup

## When to use
User asks what a pathway or GO/Reactome/KEGG term is, or which genes are in it.

## Inputs
- **term**: Pathway or term name or ID (e.g. "apoptosis", "GO:0006915", "R-HSA-109581")

## Steps

1. **Local first**: Use `search_knowledge_base` with the term to find lab-curated definitions.

2. **Online**: Use `fetch_url` for public APIs:
   - Reactome: `https://reactome.org/ContentService/data/pathway/{id}/containedGenes` or search.
   - GO: Quick description via EBI or geneontology.org if needed.
   - KEGG: Optional if you have a stable API.

3. **Synthesize**: Definition of the pathway/term + list of key genes (if available) + optional link.

## Output format
- Term/ID
- Definition (1–3 sentences)
- Key genes (if available)
- Source / link

## Failure modes
- Unknown term: report "No definition found; check ID or try alternate name."
