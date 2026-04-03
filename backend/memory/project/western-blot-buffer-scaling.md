---
type: workflow_heuristic
name: Glycine-limited Western blot running buffer scaling
description: Practical scaling rule for the 10x running-buffer recipe when glycine is limited and round-number volumes are preferred.
---
# Original Recipe

- Glycine: `72 g`
- Tris base: `15 g`
- SDS: `5 g`
- Bring to `500 mL` with water

# Constraint

- When glycine is capped at `30 g`, the maximum proportional batch is `208.3 mL`.

# Preferred Heuristic

- Prefer a `200 mL` batch when easy measurement is more useful than squeezing out the absolute maximum volume.
- A `200 mL` batch uses `28.8 g` glycine and preserves `1.2 g` for future work while maintaining the original ratios.
