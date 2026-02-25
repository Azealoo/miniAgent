---
name: buffer_recipe_scaler
description: Scale a buffer recipe to a target volume and compute component masses/volumes.
category: bio/calculations
version: 1.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
---

# Buffer Recipe Scaler

## When to use
User gives a buffer recipe (components + concentrations or amounts per L) and wants it scaled to a different volume.

## Inputs
- **recipe**: List of components with concentration (e.g. 50 mM Tris) or mass per liter.
- **target_volume**: Desired final volume (e.g. 100 mL).
- **MWs** (if needed): Molecular weights for components that need mass from molarity.

## Steps

1. **Parse**: Extract each component and its concentration or mass/L.

2. **Scale**: For each component: scaled_mass = (mass_per_L or M×MW) × (target_volume_L). Use `python_repl`.

3. **Order**: List components in a standard order (often Tris first, then others, then bring to volume).

4. **Present**: Table: Component | Amount (g or mL) | Notes; then "Bring to {target_volume} with water."

## Output format
- Scaled recipe table
- Final instruction (bring to volume, pH if relevant)
