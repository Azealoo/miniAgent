---
name: primer_design_advice
description: Advise on PCR primer design (Tm, length, GC%, avoiding secondary structure).
category: bio/calculations
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# Primer Design Advice

## When to use
User asks about designing PCR primers or evaluating primer parameters (Tm, GC content, length).

## Inputs
- **sequence**: Optional target sequence; or **primer_sequence** for evaluation.
- **task**: "design" or "evaluate".

## Steps

1. **Evaluate**: If primer sequence given, use `python_repl` to compute: length, GC%, simple Tm estimate (e.g. 2*(A+T)+4*(G+C) for short oligos). Note: no hairpin/dimer check without a proper library; recommend using Primer3 or IDT for full design.

2. **Design**: If design requested, explain best practices: length 18–25 bp, Tm 58–62 °C, GC 40–60%, avoid 3' complementarity. Suggest using Primer3 or a lab tool for actual design; offer to compute Tm/GC for candidate sequences.

3. **Present**: For evaluation: length, GC%, Tm. For design: bullet list of guidelines and tool suggestions.

## Output format
- For evaluation: length, GC%, Tm
- For design: guidelines and tool recommendations
