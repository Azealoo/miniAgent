---
name: cache_to_knowledge
description: Save a fetched summary or document to the knowledge base for later retrieval (e.g. after PubMed/UniProt lookup).
category: bio/literature
version: 1.0
requires_tools: [write_file]
requires_network: false
user_invocable: true
---

# Cache to Knowledge

## When to use
User or agent has just fetched content (e.g. abstract, gene summary) and wants to save it to the knowledge base for future use.

## Inputs
- **source**: Short label (e.g. pubmed, uniprot).
- **id**: Identifier (e.g. PMID, UniProt ID).
- **content**: Markdown or text to save (title, summary, key facts).
- **path**: Optional; default knowledge/cache/{source}/{id}.md.

## Steps

1. **Path**: Use path `knowledge/cache/{source}/{id}.md` (sanitize id for filename). If path provided and under knowledge/, use it.

2. **Content**: Format as Markdown: title, source, id, date (optional), then content. Keep under 50k chars.

3. **Write**: Use `write_file` with path under knowledge/ and the composed content.

4. **Confirm**: Tell user "Cached to knowledge/cache/... . You can retrieve it later via search_knowledge_base."

## Output format
- Confirmation and path
- Note that search_knowledge_base will index it (after next index build if applicable)
