---
name: dilution_calculator
description: Calculate dilution factors, C1V1=C2V2, and serial dilutions.
category: bio/calculations
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# Dilution Calculator

## When to use
User asks for a dilution (e.g. "dilute 10x to 1x", "C1V1=C2V2", "serial dilution").

## Inputs
- **concentration_initial** (C1), **concentration_final** (C2), **volume_final** (V2) or **volume_initial** (V1); or dilution factor and total volume.

## Steps

1. **Parse**: Identify what is given and what is needed (V1, V2, C1, C2, or dilution factor).

2. **Formula**: C1×V1 = C2×V2. For dilution factor D: C2 = C1/D, V1 = V2/D.

3. **Compute**: Use `python_repl` to calculate and check units (e.g. µL, mL).

4. **Serial**: If user asks for serial dilution (e.g. 1:2 in 8 steps), compute each step concentration and volume to transfer.

5. **Present**: State formula used, result with units, and brief instruction (e.g. "Add 90 µL buffer to 10 µL stock").

## Output format
- Given values and target
- Formula and result with units
- One-line instruction
