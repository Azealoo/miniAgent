---
name: dilution_calculator
description: Calculate C1V1=C2V2 dilutions, serial dilutions with plate-based replicates, and budget-conscious volume planning that accounts for micropipette systematic error.
category: bio/calculations
version: 2.0
requires_tools: [python_repl]
requires_network: false
user_invocable: true
tags: [dilution, serial-dilution, plate-planning, wet-lab]
aliases: [c1v1_calculator, serial_dilution_planner]
species: any
modality: wet_lab
stage: utilities
stability: stable
safety_level: low
---

# Dilution Calculator

## Purpose

Calculate simple dilutions, serial dilutions, and plate-aware dilution plans while accounting for realistic wet-lab overage and replicate structure.

## When to use
User asks for any dilution calculation: simple C1V1=C2V2, serial dilution from a protein stock, or plate-based experiment volume planning.

## Required inputs

- **stock concentration**
- **target concentration or concentration series**
- **final volume** or **plate format plus number of concentrations**
- **units** for concentration and volume
- **overage factor** (optional; default to the lab rule below)

---

## Key Lab Rules (always apply)

### 1. Serial dilution — stock used only once
- Use the stock concentration **only for the first step**: diluting stock → highest concentration tube/well.
- All subsequent steps dilute from the previous step's concentration. Stock is ignored after step 1.

### 2. Replicate count = wells ÷ concentrations
- Do **not** default to 3 replicates. Calculate from plate format:

| Plate format | Wells | Example: 6 conc. → replicates |
|---|---|---|
| 6-well | 6 | 1 |
| 12-well | 12 | 2 |
| 24-well | 24 | **4** (not 3) |
| 48-well | 48 | 8 |
| 96-well | 96 | 16 |

- Always compute: `replicates = total_wells / n_concentrations`

### 3. Volume per well (standard lab values)
| Plate format | Volume per well |
|---|---|
| 6-well | 2 mL |
| 12-well | 1 mL |
| 24-well | 500 µL |
| 48-well | 250 µL |
| 96-well | 100–200 µL |

### 4. Micropipette systematic error — prepare slightly more
Micropipettes tend to **under-aspirate** (air bubbles, worn seals). E.g. a 1 mL pipette may only deliver 995 µL.

**Overage rule**: prepare **1.05–1.10× the nominal volume** per tube.
- Want accuracy → lean toward 1.10×
- Want to save media → lean toward 1.05×
- Default: **1.05× for ≥500 µL volumes, 1.10× for <100 µL volumes**

---

## Steps

Use `python_repl` for all arithmetic and show units clearly.

### Simple dilution (C1V1 = C2V2)
1. Parse known values (C1, C2, V1, or V2).
2. Solve: `V1 = C2 * V2 / C1`  →  add `(V2 - V1)` of diluent.
3. Print result with units.

### Serial dilution from protein stock

```
Step 0: stock → tube_1 (highest concentration)
  V_stock = C_target_1 * V_tube_1 / C_stock
  V_diluent_0 = V_tube_1 - V_stock

Step i (i ≥ 1): tube_{i-1} → tube_i
  C_prev → C_i  (dilution factor D_i = C_{i-1} / C_i)
  V_transfer_i = C_i * V_tube_i / C_prev
  V_diluent_i  = V_tube_i - V_transfer_i
```

Apply overage multiplier to each `V_tube_i` before computing volumes.

### Plate-based experiment volume planning

```python
# --- User inputs ---
plate_format   = 24          # 6, 12, 24, 48, 96
n_conc         = 6           # number of concentrations
stock_conc_uM  = 95          # stock concentration (µM or any unit)
target_concs   = [10, 5, 2.5, 1.25, 0.625, 0.3125]  # µM, highest first
overage        = 1.05        # 1.05 to 1.10

# --- Derived ---
plate_volumes = {6: 2000, 12: 1000, 24: 500, 48: 250, 96: 150}  # µL
vol_per_well  = plate_volumes[plate_format]
replicates    = plate_format // n_conc
vol_per_tube  = vol_per_well * replicates * overage   # µL including overage

# Step 0: stock → tube for highest concentration
V_stock = target_concs[0] * vol_per_tube / stock_conc_uM
V_diluent_0 = vol_per_tube - V_stock

# Steps 1..N-1: serial dilution
for i in range(1, n_conc):
    V_transfer = target_concs[i] * vol_per_tube / target_concs[i-1]
    V_diluent  = vol_per_tube - V_transfer
    print(f"Tube {i+1} ({target_concs[i]} µM): transfer {V_transfer:.1f} µL, add {V_diluent:.1f} µL diluent")
```

---

## Output format

For each tube/step, report:
- Concentration (with unit)
- Volume to transfer from previous step (µL)
- Volume of diluent to add (µL)
- Total tube volume (= vol_per_well × replicates × overage)
- One-line bench instruction: "Transfer X µL from tube N-1, add Y µL buffer."

Finish with a summary table and a note on the overage factor chosen and why.

## Failure modes

- Missing units: ask the user to confirm units before calculating.
- Impossible dilution: explain why the requested concentration or volume cannot be achieved from the provided stock.
- Plate setup mismatch: if `total_wells / n_concentrations` is not an integer, warn the user and ask how they want to allocate replicates.

## Examples

- "How do I make 100 mL of a 1 mM solution from a 100 mM stock?"
- "Plan a 24-well serial dilution with 6 concentrations from a 95 uM stock."
- "How much extra media should I prepare for a 12-well plate with 2 replicates and 5 concentrations?"
