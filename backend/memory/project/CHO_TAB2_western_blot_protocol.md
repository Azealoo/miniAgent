# Western Blot Experimental Protocol: TAB2 Protein Treatment in CHO Cell Lines

## Experimental Overview
**Objective**: Determine dose-dependent effects of TAB2 protein treatment on protein expression/signaling in CHO_WT vs CHO_TAB2 cell lines.

**Cell Lines**:
- CHO_WT: Wild-type Chinese Hamster Ovary cells
- CHO_TAB2: TAB2-overexpressing CHO cells (presumed stable transfection)

**Treatment**:
- TAB2 protein at concentrations: 0, 0.1, 1, 5, 10, 50, 100, 250, 500 nM (assumed)
- Treatment duration: 24 hours (standard for protein treatment studies)

**Experimental Design**:
- 2 cell lines × 9 concentrations × 3 biological replicates = 54 total samples
- Biological replicates: independent cell passages/platings
- Technical replicates: Load each sample in duplicate on gel if possible

---

## Part 1: Cell Culture and Treatment

### Materials
- CHO_WT and CHO_TAB2 cell lines
- Complete growth medium (DMEM/F12 + 10% FBS + 1% Pen/Strep)
- TAB2 protein (recombinant, specify source and purity)
- Sterile PBS
- Trypsin-EDTA (0.25%)
- Cell counting equipment (hemocytometer or automated counter)
- 6-well plates or appropriate culture vessels

### Protocol

#### Day 1: Cell Seeding
1. **Thaw and passage cells** 2-3 days before experiment to ensure log-phase growth
2. **Seed cells** in 6-well plates:
   - Density: 2.5-3.0 × 10⁵ cells/well (adjust based on growth rate)
   - Volume: 2 mL complete medium per well
   - Plate layout: Randomize treatments to avoid position effects
3. **Incubate** at 37°C, 5% CO₂ for 24 hours to reach ~70-80% confluence

#### Day 2: Treatment
1. **Prepare TAB2 protein dilutions**:
   - Make stock solutions in appropriate buffer (PBS + 0.1% BSA recommended)
   - Prepare serial dilutions to achieve final concentrations
   - Keep on ice during preparation

2. **Treatment application**:
   - Aspirate old medium from wells
   - Add 2 mL fresh complete medium containing appropriate TAB2 concentration
   - Control wells: Add medium with vehicle only (0 nM)
   - Note: Include "no treatment" wells for time-zero comparison if needed

3. **Incubate** for 24 hours at 37°C, 5% CO₂

---

## Part 2: Cell Lysis and Protein Extraction

### Materials
- Ice-cold PBS
- RIPA lysis buffer (50 mM Tris-HCl pH 7.4, 150 mM NaCl, 1% NP-40, 0.5% sodium deoxycholate, 0.1% SDS)
- Protease inhibitor cocktail (add fresh)
- Phosphatase inhibitors (if studying phosphorylation)
- Cell scrapers
- Microcentrifuge tubes (1.5 mL)
- Sonicator or needle/syringe for shearing
- BCA or Bradford protein assay kit

### Protocol

#### Day 3: Harvest and Lysis
1. **Wash cells**: Aspirate medium, wash twice with 1 mL ice-cold PBS
2. **Add lysis buffer**: 100-200 μL RIPA + inhibitors per well
3. **Scrape cells**: Use cell scraper to collect lysate
4. **Transfer** to pre-chilled 1.5 mL tubes
5. **Incubate** on ice for 30 minutes with occasional vortexing
6. **Shear DNA**: Sonicate (3 × 10 sec pulses, 30% amplitude) or pass through 27G needle 10×
7. **Clarify**: Centrifuge at 14,000 × g, 4°C for 15 minutes
8. **Collect supernatant**: Transfer to fresh tubes, avoid pellet
9. **Aliquot**: Split into aliquots for protein assay and western blot

### Protein Quantification
1. **BCA assay** (recommended for RIPA lysates):
   - Prepare standards (BSA: 0, 0.125, 0.25, 0.5, 1, 2 mg/mL)
   - Dilute samples 1:10 in PBS
   - Follow manufacturer's protocol
   - Measure absorbance at 562 nm

2. **Normalize concentrations**:
   - Dilute all samples to same concentration (1-2 μg/μL) in 1× Laemmli buffer
   - Add reducing agent: 5% β-mercaptoethanol or 100 mM DTT
   - Heat at 95°C for 5 minutes
   - Store at -80°C if not running immediately

---

## Part 3: Gel Electrophoresis

### Materials
- 10% or 12% SDS-PAGE gel (depending on target protein size)
- 10× Running buffer (see buffer scaling protocol if glycine-limited)
- Pre-stained protein ladder
- Loading tips
- Electrophoresis apparatus
- Power supply

### Buffer Preparation (10× Running Buffer)
**Original recipe (500 mL)**:
- Glycine: 72 g
- Tris base: 15 g  
- SDS: 5 g
- Bring to 500 mL with dH₂O

**For 1× working solution**: Dilute 100 mL 10× buffer in 900 mL dH₂O

### Protocol
1. **Assemble gel apparatus** with 1× running buffer
2. **Load samples**:
   - Load 20-30 μg protein per lane (10-15 μL of 2 μg/μL sample)
   - Include ladder in first and/or last lane
   - Leave empty lanes between groups if possible
3. **Run gel**:
   - Stacking gel: 80 V for 30 minutes
   - Resolving gel: 120 V until dye front reaches bottom (~90 minutes)
4. **Monitor**: Watch for straight migration and proper separation

---

## Part 4: Protein Transfer

### Materials
- Transfer buffer (25 mM Tris, 192 mM glycine, 20% methanol)
- PVDF or nitrocellulose membrane (0.45 μm pore size)
- Filter paper
- Sponges
- Transfer apparatus (wet or semi-dry)
- Methanol (for PVDF activation)

### Protocol
1. **Prepare membrane**:
   - PVDF: Activate in methanol for 1 minute, then equilibrate in transfer buffer
   - Nitrocellulose: Wet directly in transfer buffer
2. **Assemble transfer sandwich** (cathode to anode):
   - Sponge
   - 3× Filter paper
   - Gel
   - Membrane
   - 3× Filter paper
   - Sponge
3. **Transfer conditions**:
   - Wet transfer: 100 V for 60-90 minutes at 4°C
   - Semi-dry: 25 V for 30 minutes
4. **Verify transfer**: Stain membrane with Ponceau S (0.1% in 5% acetic acid) to check efficiency

---

## Part 5: Immunoblotting

### Materials
- Blocking buffer: 5% non-fat dry milk or BSA in TBST
- TBST: 20 mM Tris-HCl pH 7.6, 150 mM NaCl, 0.1% Tween-20
- Primary antibodies (specify based on targets)
- HRP-conjugated secondary antibodies
- Enhanced chemiluminescence (ECL) substrate
- Imaging system (chemiluminescence detector)

### Primary Antibody Considerations
**Essential targets**:
1. **TAB2** (your treatment protein of interest)
2. **Loading controls**:
   - GAPDH or β-actin (total protein)
   - Histone H3 (nuclear)
   - α-tubulin (cytoskeletal)
3. **Signaling markers** (if studying pathway activation):
   - Phospho-proteins relevant to TAB2 signaling
   - Total forms of same proteins

### Protocol
1. **Block membrane**: 5% milk in TBST, 1 hour at RT with gentle shaking
2. **Primary antibody incubation**:
   - Dilute in blocking buffer (check manufacturer's recommendation)
   - Incubate overnight at 4°C with gentle shaking
   - Or: 2 hours at RT for high-affinity antibodies
3. **Wash**: 3 × 10 minutes with TBST
4. **Secondary antibody incubation**:
   - Anti-species HRP conjugate (1:5000-1:10000)
   - 1 hour at RT with gentle shaking
5. **Wash**: 3 × 10 minutes with TBST
6. **Detection**:
   - Mix ECL reagents according to manufacturer
   - Incubate membrane for 1-5 minutes
   - Image with appropriate exposure times (avoid saturation)

---

## Part 6: Stripping and Reprobing

### Materials
- Stripping buffer: 62.5 mM Tris-HCl pH 6.8, 2% SDS, 100 mM β-mercaptoethanol
- Or: Commercial mild stripping buffer

### Protocol
1. **Wash membrane** with TBST
2. **Incubate** in stripping buffer at 50°C for 30 minutes with occasional agitation
3. **Wash extensively**: 6 × 10 minutes with TBST
4. **Re-block** and proceed with next primary antibody
5. **Recommended probing order**:
   - Low abundance targets first
   - Phospho-proteins before total proteins
   - Loading controls last

---

## Part 7: Data Analysis

### Quantification
1. **Image analysis** using ImageJ or commercial software:
   - Draw rectangles around bands
   - Subtract background
   - Normalize to loading control
2. **Calculate fold change** relative to control (0 nM)
3. **Statistical analysis**:
   - Perform on 3 biological replicates
   - Two-way ANOVA (cell line × concentration)
   - Post-hoc tests for specific comparisons
   - Consider log transformation for concentration-response

### Expected Outcomes
1. **CHO_WT**: Dose-dependent response to TAB2 treatment
2. **CHO_TAB2**: Possibly altered sensitivity due to baseline overexpression
3. **EC₅₀ calculation** for each cell line
4. **Maximum response** comparison between cell lines

---

## Part 8: Troubleshooting and Quality Controls

### Essential Controls
1. **No primary antibody control**: Secondary only
2. **Isotype control**: Non-specific IgG
3. **Positive control lysate**: Known expressing cell line
4. **Ladder verification**: Check expected band sizes
5. **Ponceau S stain**: Verify equal loading and transfer

### Common Issues and Solutions
| Issue | Possible Cause | Solution |
|-------|---------------|----------|
| High background | Insufficient blocking | Increase blocking time, try BSA instead of milk |
| No signal | Antibody dilution too high | Titrate antibody, check expiration |
| Multiple bands | Non-specific binding | Optimize antibody conditions, try different blocking |
| Smearing | Overloading or degradation | Reduce protein load, fresh protease inhibitors |
| Curved bands | Gel running too hot | Run at lower voltage, use cooling |

### Reagent Validation
1. **TAB2 protein**: Verify activity with positive control assay
2. **Antibodies**: Validate with knockout/knockdown controls if available
3. **Cell lines**: Authenticate with STR profiling
4. **Mycoplasma**: Test cultures regularly

---

## Part 9: Timeline and Workflow

### 7-Day Workflow
**Day 1-2**: Cell culture preparation
**Day 3**: Treatment application
**Day 4**: Harvest, lysis, quantification
**Day 5**: Gel electrophoresis and transfer
**Day 6**: Immunoblotting and detection
**Day 7**: Stripping/reprobing, data analysis

### Batch Processing Recommendations
- Process all samples for same target in single batch
- Keep exposure times consistent across gels
- Include inter-gel controls for normalization
- Document all deviations from protocol

---

## Part 10: Safety and Compliance

### Biosafety
- CHO cells: BSL-1 typically
- Follow institutional guidelines
- Proper disposal of biological waste

### Chemical Safety
- β-mercaptoethanol: Use in fume hood
- Acrylamide: Neurotoxin, wear gloves
- Methanol: Flammable, use in well-ventilated area

### Documentation
- Maintain detailed lab notebook
- Record lot numbers of all reagents
- Save raw images and analysis files
- Archive membranes at -20°C

---

## Appendix: Sample Gel Layout Example

**Gel 1 (15 wells)**:
1. Ladder
2. CHO_WT_0_rep1
3. CHO_WT_0_rep2
4. CHO_WT_0_rep3
5. CHO_WT_0.1_rep1
6. CHO_WT_0.1_rep2
7. CHO_WT_0.1_rep3
8. CHO_WT_1_rep1
9. CHO_WT_1_rep2
10. CHO_WT_1_rep3
11. CHO_WT_5_rep1
12. CHO_WT_5_rep2
13. CHO_WT_5_rep3
14. Ladder
15. Empty

**Gel 2 (15 wells)**:
1. Ladder
2. CHO_WT_10_rep1
3. CHO_WT_10_rep2
4. CHO_WT_10_rep3
5. CHO_WT_50_rep1
6. CHO_WT_50_rep2
7. CHO_WT_50_rep3
8. CHO_WT_100_rep1
9. CHO_WT_100_rep2
10. CHO_WT_100_rep3
11. CHO_WT_250_rep1
12. CHO_WT_250_rep2
13. CHO_WT_250_rep3
14. CHO_WT_500_rep1
15. Ladder

**Continue with CHO_TAB2 samples on additional gels**

---

## Notes for Your Specific Experiment

1. **Concentration units**: Confirm if nM or μg/mL - this affects stock preparation
2. **TAB2 source**: Recombinant protein characteristics (species, tags, purity)
3. **Expected TAB2 size**: ~70 kDa (human) - choose appropriate gel percentage
4. **CHO_TAB2 line**: Confirm overexpression level before experiment
5. **Treatment duration**: 24 hours standard, but consider time course if studying early signaling

**Success criteria**:
- Clear dose-response in CHO_WT
- Altered response in CHO_TAB2 (right-shifted or amplified)
- Good technical reproducibility (CV < 20% between replicates)
- Clean blots with specific bands

**Deliverables**:
- Raw western blot images
- Quantified band intensities
- Dose-response curves
- Statistical analysis report
- Annotated protocol with any modifications