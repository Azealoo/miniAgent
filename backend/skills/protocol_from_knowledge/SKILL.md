---
name: protocol_from_knowledge
description: Find and return a protocol or SOP from the local knowledge base.
category: bio/literature
version: 1.0
requires_tools: [search_knowledge_base, read_file]
requires_network: false
user_invocable: true
---

# Protocol from Knowledge

## When to use
User asks for a protocol, SOP, or "how we do X" and expects an answer from lab docs.

## Inputs
- **query**: Protocol name or topic (e.g. "PCR", "RNA extraction", "Perturb-seq library prep").

## Steps

1. **Search**: Use `search_knowledge_base` with the query. If results point to specific files, use `read_file` to get full content when helpful.

2. **Synthesize**: Return the relevant protocol section(s) or SOP. Preserve structure (steps, reagents, notes). If multiple hits, summarize or list sources.

3. **Attribution**: State source (file or document name) so user can open the full doc.

## Output format
- Protocol steps and key details
- Source(s) (file path or doc name)
