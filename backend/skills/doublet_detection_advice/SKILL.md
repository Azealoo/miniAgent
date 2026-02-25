---
name: doublet_detection_advice
description: Advise on doublet detection and removal for scRNA (scrublet, scDblFinder, best practices).
category: bio/scRNA
version: 1.0
requires_tools: [search_knowledge_base]
requires_network: false
user_invocable: true
---

# Doublet Detection Advice

## When to use
User asks about doublets in single-cell data: how to detect, which tool, or when to remove.

## Inputs
- **method**: Optional (scrublet, scDblFinder, etc.); **expected_doublet_rate**: Optional.

## Steps

1. **Local**: Use `search_knowledge_base` for lab SOPs on doublet detection.

2. **Summarize**: Explain that doublets are two cells in one droplet; recommend tools (Scrublet for 10x, scDblFinder for flexibility). Mention expected rate (~0.4% per 1k cells for 10x).

3. **Workflow**: Suggest: run doublet scoring → set threshold or use automatic → filter or label. Note not to over-filter.

4. **Caveats**: Brief note on multiplet rate vs sequencing depth.

## Output format
- Recommended tool(s) and when to use
- Short workflow
- Caveats
