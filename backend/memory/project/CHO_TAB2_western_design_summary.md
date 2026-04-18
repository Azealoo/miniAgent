# Western Blot Experimental Design: TAB2 Treatment in CHO Cells

## 1. Experimental Layout

**Cell Lines**:
- CHO_WT (wild-type control)
- CHO_TAB2 (TAB2-overexpressing)

**Treatment Conditions**:
- TAB2 protein concentrations: 0, 0.1, 1, 5, 10, 50, 100, 250, 500 (units: confirm nM or μg/mL)
- Treatment duration: Standard is 24 hours (adjust based on TAB2 mechanism)

**Replication**:
- 3 biological replicates (independent cell passages)
- Total samples: 2 × 9 × 3 = 54 samples

## 2. Key Design Decisions

### A. Concentration Range
- **Wide range** (0.1-500) to capture full dose-response
- **Log spacing** for EC₅₀ determination
- **Vehicle control** (0 concentration) essential

### B. Cell Line Comparison
- **CHO_WT**: Baseline response to TAB2
- **CHO_TAB2**: Altered sensitivity expected due to overexpression
- **Statistical test**: Two-way ANOVA (cell line × concentration)

### C. Sample Processing
- **Harvest time**: Consistent across all samples
- **Lysis buffer**: RIPA with fresh protease/phosphatase inhibitors
- **Protein load**: 20-30 μg per lane, normalized by BCA assay

## 3. Western Blot Workflow

### Day 1-2: Cell Culture
- Seed 2.5-3.0 × 10⁵ cells/well in 6-well plates
- Grow to 70-80% confluence

### Day 3: Treatment
- Prepare TAB2 dilutions in complete medium
- Treat for 24 hours (standard duration)

### Day 4: Harvest
- Wash with ice-cold PBS
- Lyse with RIPA buffer (100-200 μL/well)
- Quantify protein (BCA assay)
- Prepare samples in Laemmli buffer

### Day 5: Electrophoresis & Transfer
- Run 10% SDS-PAGE (TAB2 ~70 kDa)
- Transfer to PVDF/nitrocellulose
- Verify with Ponceau S stain

### Day 6: Immunoblotting
- Block with 5% milk/TBST
- Primary antibodies: TAB2 + loading control (GAPDH/β-actin)
- Secondary: HRP-conjugated
- Detect with ECL

### Day 7: Analysis
- Quantify bands (ImageJ)
- Normalize to loading control
- Plot dose-response curves
- Calculate EC₅₀ values

## 4. Critical Controls

1. **No primary antibody** (secondary only)
2. **Isotype control** (non-specific IgG)
3. **Positive control** (known TAB2-expressing lysate)
4. **Ponceau S stain** (equal loading/transfer)
5. **Inter-gel controls** for normalization

## 5. Data Analysis Plan

### Primary Questions:
1. Does TAB2 treatment affect TAB2 protein levels?
2. Is response different between CHO_WT and CHO_TAB2?
3. What is the EC₅₀ for each cell line?

### Statistical Approach:
- Two-way ANOVA (cell line × concentration)
- Post-hoc tests for specific comparisons
- Log transformation of concentrations
- Curve fitting for EC₅₀ calculation

## 6. Practical Considerations

### Gel Layout:
- Split 54 samples across 4 gels (15-well each)
- Include ladder and controls on every gel
- Randomize sample order to avoid position effects

### Antibody Validation:
- Verify TAB2 antibody specificity
- Test loading control antibodies
- Optimize dilutions with pilot experiment

### Reagent Notes:
- Confirm TAB2 protein units (nM vs μg/mL)
- Record lot numbers of all reagents
- Aliquot protein to avoid freeze-thaw cycles

## 7. Success Criteria

- Clear dose-response in CHO_WT
- Altered curve in CHO_TAB2 (right-shifted or amplified)
- Technical reproducibility (CV < 20% between replicates)
- Specific bands without non-specific staining

## 8. Next Steps

1. **Confirm concentration units** for TAB2 protein
2. **Validate TAB2 antibody** with positive/negative controls
3. **Pilot experiment** with subset of concentrations
4. **Finalize gel layout** based on available equipment
5. **Prepare data analysis template** before running experiment