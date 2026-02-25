---
name: unit_conversion
description: Convert between common lab units (mg/mL to M, % to molar, ng/µL, etc.) given MW where needed.
category: bio/calculations
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# Unit Conversion

## When to use
User asks to convert concentration or mass units (e.g. mg/mL to mM, % w/v to M, ng/µL to nM).

## Inputs
- **value** and **from_unit**, **to_unit**; **MW** (if conversion involves moles).

## Steps

1. **Parse**: Identify value, from_unit, to_unit. If converting to/from molar, get MW (ask if not given).

2. **Convert**: Use `python_repl`: normalize to base (e.g. g/L, mol/L), then convert to target. Handle % w/v, mg/mL, µg/µL, nM, µM, mM, M.

3. **Present**: Show formula and result with units. Round appropriately.

## Output format
- Input and target units
- Result with units
