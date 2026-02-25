---
name: molarity_mass_volume
description: Convert between molarity, mass, and volume using molecular weight.
category: bio/calculations
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# Molarity, Mass, and Volume

## When to use
User asks to convert between molarity (M), mass (g/mg), and volume (L/mL/µL) given molecular weight.

## Inputs
- **MW**: Molecular weight (g/mol).
- Two of: **molarity**, **mass**, **volume** (with units).

## Steps

1. **Parse**: Identify knowns and unknown; normalize units (L, mL, µL; g, mg; M, mM, µM).

2. **Formulas**: moles = mass/MW; moles = M × V(L); so mass = M × V × MW.

3. **Compute**: Use `python_repl` to solve and round to sensible precision.

4. **Present**: Show equation, result with units, and one-line instruction (e.g. "Weigh 0.049 g and bring to 50 mL").

## Output format
- Known values and target
- Formula and result with units
- Practical instruction
