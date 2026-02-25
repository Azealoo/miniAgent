---
name: data_location_help
description: Explain where project data and outputs live (e.g. GPFS, data/, predictions/) from knowledge base.
category: bio/hpc
version: 1.0
requires_tools: [search_knowledge_base]
requires_network: false
user_invocable: true
---

# Data Location Help

## When to use
User asks where data is stored, where to find results, or what directories to use for a pipeline.

## Inputs
- **topic**: Optional (e.g. "raw data", "predictions", "GEARS output", "norman").

## Steps

1. **Search**: Use `search_knowledge_base` with query like "data location", "where is data", "GPFS", "predictions directory", or the topic.

2. **Summarize**: Return paths and conventions (e.g. data/ for raw, predictions/ for outputs, tmp/ for scratch). If nothing found, state that and suggest asking the lab or checking project README.

3. **Remind**: Note that paths may be project-relative (e.g. backend is project root for read_file; for terminal, CWD may differ).

## Output format
- Directory/path summary
- Source (knowledge base or "not documented")
- Short reminder on path context
