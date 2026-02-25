---
name: plate_map_generator
description: Generate a 96- or 384-well plate map for perturbations and replicates.
category: bio/calculations
version: 1.0
requires_tools: [python_repl, write_file]
requires_network: false
user_invocable: true
---

# Plate Map Generator

## When to use
User needs a plate layout for experiments (e.g. perturbations, replicates, controls on 96/384 well plate).

## Inputs
- **plate_size**: 96 or 384.
- **conditions**: List of condition names (e.g. "CTRL", "KO1", "KO2") and optional replicate count per condition.
- **layout**: Optional "randomized" or "blocked" (by row/column).

## Steps

1. **Parse**: Get plate size and list of conditions (with replicate counts if given).

2. **Assign wells**: Use `python_repl` to assign each condition to wells (A1–H12 for 96; extend for 384). If randomized, shuffle; if blocked, fill by row or column.

3. **Output**: Generate a text or CSV representation: well → condition. Optionally use `write_file` to save under `knowledge/` (e.g. `knowledge/plate_maps/plate_001.csv`).

4. **Present**: Show the map (e.g. grid or table) and note where controls and replicates are.

## Output format
- Plate grid or table (well, condition)
- Optional file path if saved
