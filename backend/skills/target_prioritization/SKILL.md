---
name: target_prioritization
description: Rank perturbation targets by drugability, pathway relevance, and safety given constraints.
category: bio/perturbation
version: 1.0
requires_tools: [fetch_url, search_knowledge_base, python_repl]
requires_network: true
user_invocable: true
---

# Target Prioritization

## When to use
User has a list of candidate genes or perturbations and wants them ranked by suitability for follow-up (drugability, pathway, safety).

## Inputs
- **candidates**: List of gene symbols or targets.
- **criteria**: Optional weights (e.g. "prefer druggable", "avoid toxicity").

## Steps

1. **Local**: Use `search_knowledge_base` for lab-specific target lists or constraints.

2. **Annotate**: For each candidate, use `fetch_url` (UniProt/Open Targets/DrugBank if available) to get:
   - Druggability or known drugs
   - Pathway involvement
   - Safety/toxicity mentions (brief)

3. **Score**: In `python_repl`, build a simple score (e.g. 0–1 for druggable, pathway relevance, safety) and rank.

4. **Present**: Ranked table with short justification per target and caveats (e.g. "limited drug data").

## Output format
- Ranked list: Gene | Druggability | Pathway | Safety note | Score
- Brief caveats
