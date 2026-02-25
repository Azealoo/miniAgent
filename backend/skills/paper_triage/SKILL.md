---
name: paper_triage
description: Classify relevance of a paper (perturb-seq/scRNA), extract main claims and limitations from abstract.
category: bio/literature
version: 1.0
requires_tools: []
requires_network: false
user_invocable: true
---

# Paper Triage

## When to use
User pastes an abstract or asks whether a paper is relevant to perturb-seq / scRNA / single-cell perturbation.

## Inputs
- **abstract**: The abstract text (or user provides it in the message)

## Steps

1. **Identify**: If the user did not paste the abstract, ask for it or use the last provided text.

2. **Classify**: Determine relevance:
   - High: Perturb-seq, CRISPR screens, single-cell perturbation, scRNA-seq of perturbations.
   - Medium: scRNA-seq, single-cell methods, gene regulation.
   - Low: Other (specify).

3. **Extract**: From the abstract, list:
   - Main claims (1–3 bullets)
   - Key methods (e.g. platform, perturbations, analysis)
   - Stated limitations or caveats (if any).

4. **Respond**: Present classification + claims + methods + limitations in a short structured block.

## Output format
- **Relevance**: High / Medium / Low + one sentence.
- **Main claims**: Bullet list.
- **Key methods**: Short line.
- **Limitations**: Bullet list or "None stated."
