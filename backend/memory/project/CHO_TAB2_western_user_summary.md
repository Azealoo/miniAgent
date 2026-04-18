# Western Blot Protocol Summary: TAB2 Treatment in CHO Cells

## **⚠️ IMMEDIATE ACTION REQUIRED**
**Confirm TAB2 concentration units**: Are your concentrations in **nM** or **μg/mL**? This determines stock preparation.

## **EXPERIMENTAL DESIGN**
- **Cell lines**: CHO_WT (wild-type) vs CHO_TAB2 (TAB2-overexpressing)
- **TAB2 concentrations**: 0, 0.1, 1, 5, 10, 50, 100, 250, 500 (units to confirm)
- **Replicates**: 3 biological replicates per condition
- **Total samples**: 54 (2 × 9 × 3)

## **WEEKLY WORKFLOW**

### **Week 1: Cell Culture & Treatment**
**Day 1-2**: Seed cells (2.5 × 10⁵ cells/well in 6-well plates)
**Day 3**: Treat with TAB2 for 24 hours
**Day 4**: Harvest, lyse, quantify protein (BCA assay)

### **Week 2: Western Blot**
**Day 5**: SDS-PAGE (10% gel) and transfer to PVDF
**Day 6**: Immunoblotting (TAB2 + loading control antibodies)
**Day 7**: Analysis and optional reprobing

## **CRITICAL BUFFERS**
1. **RIPA Lysis Buffer**: 50 mM Tris pH 7.4, 150 mM NaCl, 1% NP-40, 0.5% deoxycholate, 0.1% SDS + inhibitors
2. **10× Running Buffer**: 72 g glycine, 15 g Tris, 5 g SDS per 500 mL
3. **Transfer Buffer**: 25 mM Tris, 192 mM glycine, 20% methanol
4. **TBST**: 20 mM Tris pH 7.6, 150 mM NaCl, 0.1% Tween-20

## **ANTIBODY RECOMMENDATIONS**
- **Primary**: Anti-TAB2 (1:1000, overnight at 4°C)
- **Loading control**: GAPDH or β-actin (1:5000)
- **Secondary**: HRP-conjugated anti-species (1:10000, 1 hour RT)

## **LOADING AND RUNNING**
- **Protein load**: 20 μg per lane
- **Gel**: 10% SDS-PAGE
- **Running**: 80V for 30 min (stacking), 120V for 90 min (resolving)
- **Transfer**: 100V for 90 min at 4°C

## **DATA ANALYSIS**
1. **Quantify bands** with ImageJ (background subtract)
2. **Normalize** TAB2 to loading control
3. **Plot dose-response** curves (log concentration vs normalized intensity)
4. **Statistical test**: Two-way ANOVA (cell line × concentration)
5. **Calculate EC₅₀** using four-parameter logistic fit

## **ESSENTIAL CONTROLS**
1. Vehicle control (0 nM TAB2)
2. No primary antibody control
3. Positive control (known TAB2-expressing lysate)
4. Ponceau S stain for transfer verification

## **SAFETY NOTES**
- **β-mercaptoethanol**: Use in fume hood
- **Acrylamide**: Neurotoxin - wear gloves
- **Methanol**: Flammable - ventilate well

## **NEXT STEPS**
1. Confirm TAB2 concentration units
2. Validate TAB2 antibody specificity
3. Run pilot with 3 concentrations (0, 10, 500) to test workflow
4. Prepare data analysis template before full experiment

## **FULL PROTOCOL**
Complete detailed protocol saved at: `memory/project/CHO_TAB2_western_complete_protocol.md`