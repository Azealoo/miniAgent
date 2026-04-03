# Complete Western Blot Protocol: TAB2 Protein Treatment in CHO_WT vs CHO_TAB2

## **⚠️ CRITICAL NOTE: TAB2 Concentration Units**
**Before starting**: You must confirm whether your TAB2 protein concentrations are in **nM** or **μg/mL**. This protocol assumes **nM** as the working unit. If your protein is labeled differently:
- **If μg/mL**: Convert to molarity using TAB2 molecular weight (~70 kDa for full-length human TAB2)
- **If unknown**: Run a pilot experiment with both nM and μg/mL scales to determine biologically active range

## **1. EXPERIMENTAL DESIGN**

### **1.1 Experimental Matrix**
| Factor | Levels | Notes |
|--------|--------|-------|
| **Cell Lines** | CHO_WT, CHO_TAB2 | TAB2-overexpressing vs wild-type |
| **TAB2 Concentrations** | 0, 0.1, 1, 5, 10, 50, 100, 250, 500 nM | Wide log-spaced range for dose-response |
| **Biological Replicates** | 3 | Independent cell passages |
| **Total Samples** | 2 × 9 × 3 = **54 samples** | |

### **1.2 Controls**
- **Vehicle control**: 0 nM TAB2 (buffer only)
- **No treatment control**: Untreated cells (optional, for time-zero)
- **Positive control**: Known TAB2-expressing cell lysate
- **Loading control**: GAPDH or β-actin on every blot
- **Secondary-only control**: No primary antibody

### **1.3 Randomization and Blinding**
- **Plate layout**: Randomize treatments across plates
- **Gel loading**: Load samples in randomized order
- **Blinding**: Code samples if possible for unbiased analysis

## **2. MATERIALS PREPARATION**

### **2.1 Cell Culture**
- **Cell lines**: CHO_WT and CHO_TAB2 (authenticated, mycoplasma-free)
- **Growth medium**: DMEM/F12 + 10% FBS + 1% Pen/Strep
- **Culture vessels**: 6-well plates (or appropriate for protein yield)
- **Trypsin-EDTA**: 0.25% for detachment

### **2.2 TAB2 Protein Preparation**
**Stock solution preparation**:
1. **Reconstitute TAB2 protein** according to manufacturer instructions
2. **Determine stock concentration**: Use provided info or measure by BCA
3. **Calculate dilution series**:
   ```
   Final concentrations: 0, 0.1, 1, 5, 10, 50, 100, 250, 500 nM
   Assume 2 mL medium per well in 6-well plate
   Prepare 10× concentrated stocks in PBS + 0.1% BSA
   Add 200 μL of 10× stock to 1.8 mL medium per well
   ```
4. **Aliquot and store**: -80°C in single-use aliquots

### **2.3 Buffer Recipes**
**RIPA Lysis Buffer (50 mL)**:
- 25 mL 1M Tris-HCl pH 7.4 (final 50 mM)
- 7.5 mL 5M NaCl (final 150 mM)
- 5 mL 10% NP-40 (final 1%)
- 2.5 mL 10% sodium deoxycholate (final 0.5%)
- 0.5 mL 10% SDS (final 0.1%)
- 10 mL dH₂O
- **Add fresh**: 1× protease inhibitor cocktail, 1× phosphatase inhibitors

**10× Running Buffer (500 mL)**:
- Glycine: 72 g
- Tris base: 15 g
- SDS: 5 g
- Bring to 500 mL with dH₂O
- **For 1×**: Dilute 100 mL in 900 mL dH₂O

**Transfer Buffer (1 L)**:
- Tris base: 3.03 g (25 mM)
- Glycine: 14.4 g (192 mM)
- Methanol: 200 mL (20%)
- dH₂O to 1 L

**TBST (1 L)**:
- Tris-HCl pH 7.6: 2.42 g (20 mM)
- NaCl: 8.77 g (150 mM)
- Tween-20: 1 mL (0.1%)
- dH₂O to 1 L

**Blocking Buffer**:
- 5% non-fat dry milk in TBST
- Or 5% BSA in TBST for phospho-antibodies

**Laemmli Sample Buffer (2×)**:
- 4% SDS
- 20% glycerol
- 120 mM Tris-HCl pH 6.8
- 0.02% bromophenol blue
- 10% β-mercaptoethanol (add fresh)

## **3. STEP-BY-STEP PROTOCOL**

### **Week 1: Cell Culture and Treatment**

#### **Day 1-2: Cell Preparation**
1. **Thaw and expand cells** 3-4 days before experiment
2. **Passage cells** to ensure log-phase growth
3. **Day before treatment**: Seed cells in 6-well plates
   - **Density**: 2.5 × 10⁵ cells/well (adjust for 70-80% confluence at treatment)
   - **Volume**: 2 mL complete medium per well
   - **Incubate**: 37°C, 5% CO₂ overnight

#### **Day 3: TAB2 Treatment**
1. **Prepare TAB2 dilutions** (keep on ice):
   - Make 10× concentrated stocks in PBS + 0.1% BSA
   - Prepare all concentrations from highest to lowest
   - Include vehicle control (PBS + 0.1% BSA only)

2. **Treat cells**:
   - Aspirate old medium from all wells
   - Add 1.8 mL fresh complete medium to each well
   - Add 200 μL of appropriate 10× TAB2 stock
   - Gently swirl to mix
   - **Note**: Work quickly to minimize time differences

3. **Incubate**:
   - Return plates to incubator (37°C, 5% CO₂)
   - **Treatment duration**: 24 hours (standard for protein treatments)
   - **Alternative**: If studying early signaling, consider shorter times (15 min - 4 hours)

### **Week 1: Harvest and Lysis**

#### **Day 4: Cell Harvest**
1. **Prepare workspace**:
   - Pre-chill PBS on ice
   - Prepare RIPA buffer with fresh inhibitors
   - Label 1.5 mL tubes

2. **Harvest cells**:
   - Aspirate medium
   - Wash twice with 1 mL ice-cold PBS
   - Add 150 μL RIPA buffer per well
   - Scrape cells thoroughly with cell scraper
   - Transfer lysate to pre-chilled tube

3. **Process lysates**:
   - Incubate on ice for 30 minutes, vortex every 10 minutes
   - Sonicate: 3 × 10 seconds at 30% amplitude (or pass through 27G needle)
   - Centrifuge: 14,000 × g, 4°C, 15 minutes
   - Transfer supernatant to fresh tube (avoid pellet)

4. **Protein quantification** (BCA assay):
   - Prepare BSA standards: 0, 0.125, 0.25, 0.5, 1, 2 mg/mL
   - Dilute samples 1:10 in PBS
   - Follow manufacturer protocol
   - Measure absorbance at 562 nm
   - Calculate concentrations from standard curve

5. **Prepare samples for SDS-PAGE**:
   - Normalize all samples to 2 μg/μL with RIPA buffer
   - Mix 1:1 with 2× Laemmli buffer (final 1 μg/μL)
   - Add β-mercaptoethanol to 5% final
   - Heat at 95°C for 5 minutes
   - Store at -80°C or proceed immediately

### **Week 2: Western Blotting**

#### **Day 5: SDS-PAGE and Transfer**
1. **Prepare gel**:
   - Use 10% resolving gel for TAB2 (~70 kDa)
   - 5% stacking gel
   - Allow 30 minutes to polymerize

2. **Load samples**:
   - Load 20 μg protein per lane (20 μL of 1 μg/μL)
   - Include pre-stained ladder in first and last lanes
   - Leave empty lanes between groups if possible

3. **Run electrophoresis**:
   - Stacking gel: 80 V for 30 minutes
   - Resolving gel: 120 V until dye front reaches bottom (~90 minutes)
   - Monitor for straight migration

4. **Prepare transfer**:
   - Cut PVDF membrane to gel size
   - Activate PVDF in methanol for 1 minute
   - Equilibrate membrane, gel, and filter papers in transfer buffer

5. **Assemble transfer sandwich** (cathode to anode):
   - Sponge
   - 3× Filter paper
   - Gel
   - Membrane
   - 3× Filter paper
   - Sponge
   - Remove all air bubbles

6. **Transfer**:
   - Wet transfer: 100 V for 90 minutes at 4°C
   - Or semi-dry: 25 V for 30 minutes

7. **Verify transfer**:
   - Stain membrane with Ponceau S (0.1% in 5% acetic acid) for 5 minutes
   - Destain with dH₂O
   - Document with scanner or camera
   - Destain completely with TBST before blocking

#### **Day 6: Immunoblotting**
1. **Block membrane**:
   - Incubate in 5% milk/TBST for 1 hour at RT with gentle shaking
   - For phospho-antibodies: Use 5% BSA/TBST

2. **Primary antibody incubation**:
   - **TAB2 antibody**: Dilute according to manufacturer (typically 1:1000)
   - **Loading control**: GAPDH or β-actin (1:5000)
   - Incubate overnight at 4°C with gentle shaking
   - **Alternative**: 2 hours at RT for high-affinity antibodies

3. **Wash**:
   - 3 × 10 minutes with TBST
   - Use generous volume (50 mL for mini-blot)

4. **Secondary antibody incubation**:
   - Anti-species HRP conjugate (1:10000 in blocking buffer)
   - Incubate 1 hour at RT with gentle shaking

5. **Wash**:
   - 3 × 10 minutes with TBST

6. **Detection**:
   - Mix ECL reagents (1:1 ratio)
   - Incubate membrane for 1 minute
   - Drain excess, wrap in plastic
   - Image with chemiluminescence detector
   - Use multiple exposures (30 sec, 1 min, 5 min)
   - **Avoid saturation** - bands should not be completely white

#### **Day 7: Stripping and Reprobing (if needed)**
1. **Strip membrane**:
   - Incubate in stripping buffer (62.5 mM Tris pH 6.8, 2% SDS, 100 mM β-ME)
   - 50°C for 30 minutes with occasional agitation
   - Or use commercial mild stripping buffer

2. **Wash extensively**:
   - 6 × 10 minutes with TBST

3. **Re-block and reprobe**:
   - Block as before
   - Probe with next primary antibody
   - **Recommended order**: Low abundance → high abundance targets

## **4. DATA ANALYSIS**

### **4.1 Image Quantification**
1. **Open images** in ImageJ/Fiji
2. **Draw rectangles** around each band
3. **Measure intensity** (integrated density)
4. **Subtract background** from adjacent area
5. **Normalize**: TAB2 intensity / loading control intensity

### **4.2 Statistical Analysis**
1. **Calculate fold change** relative to 0 nM control for each cell line
2. **Plot dose-response curves**:
   - X-axis: log10(concentration)
   - Y-axis: normalized intensity
3. **Statistical tests**:
   - Two-way ANOVA (cell line × concentration)
   - Post-hoc tests for specific comparisons
   - Consider using R or GraphPad Prism

### **4.3 EC₅₀ Calculation**
1. **Fit four-parameter logistic model**:
   ```
   Y = Bottom + (Top - Bottom) / (1 + 10^((LogEC₅₀ - X) × HillSlope))
   ```
2. **Compare EC₅₀ values** between CHO_WT and CHO_TAB2
3. **Calculate maximum response** (Top) for each cell line

## **5. QUALITY CONTROL AND TROUBLESHOOTING**

### **5.1 Essential QC Checks**
| Check | Acceptable Range | Action if Failed |
|-------|-----------------|------------------|
| **Protein concentration** | 1-5 μg/μL | Adjust lysis volume |
| **BCA assay R²** | >0.98 | Repeat standards |
| **Ponceau S stain** | Even staining across lanes | Repeat transfer |
| **Background** | Low, uniform | Increase blocking/washes |
| **Band specificity** | Single band at expected size | Optimize antibody conditions |

### **5.2 Troubleshooting Guide**
**Problem**: High background
- **Solution**: Increase blocking time, try BSA instead of milk, increase wash stringency

**Problem**: No signal
- **Solution**: Check antibody expiration, optimize dilution, verify transfer efficiency

**Problem**: Multiple bands
- **Solution**: Increase blocking, optimize antibody concentration, try different buffer

**Problem**: Smearing
- **Solution**: Reduce protein load, ensure fresh protease inhibitors, avoid over-heating samples

**Problem**: Curved bands
- **Solution**: Run gel at lower voltage, ensure even buffer distribution, check gel integrity

## **6. TIMELINE AND WORKFLOW SUMMARY**

### **7-Day Complete Workflow**
- **Day 1-2**: Cell preparation and seeding
- **Day 3**: TAB2 treatment application
- **Day 4**: Harvest, lysis, quantification
- **Day 5**: SDS-PAGE and transfer
- **Day 6**: Immunoblotting and detection
- **Day 7**: Analysis and optional reprobing

### **Batch Processing Recommendations**
- Process all samples for same target together
- Keep exposure times consistent
- Include inter-gel controls
- Document all deviations

## **7. SAFETY AND COMPLIANCE**

### **7.1 Biosafety**
- CHO cells: Typically BSL-1
- Follow institutional biosafety guidelines
- Proper disposal of biological waste

### **7.2 Chemical Safety**
- **β-mercaptoethanol**: Use in fume hood, highly toxic
- **Acrylamide**: Neurotoxin, wear gloves, avoid skin contact
- **Methanol**: Flammable, use in well-ventilated area
- **SDS**: Irritant, wear eye protection

### **7.3 Documentation**
- Record all reagent lot numbers
- Document antibody dilutions and incubation times
- Save all raw images and analysis files
- Maintain lab notebook with detailed notes

## **8. EXPECTED RESULTS AND INTERPRETATION**

### **8.1 Possible Outcomes**
1. **Dose-dependent increase** in TAB2 levels (positive feedback)
2. **Dose-dependent decrease** (negative regulation)
3. **No change** (TAB2 not autoregulated)
4. **Different responses** between CHO_WT and CHO_TAB2

### **8.2 Interpretation Guidelines**
- **EC₅₀ difference**: Indicates altered sensitivity in TAB2-overexpressing cells
- **Maximum response difference**: Suggests different signaling capacity
- **Hill slope difference**: May indicate cooperative binding or multiple mechanisms

## **9. NEXT STEPS AFTER EXPERIMENT**

1. **Validate findings** with orthogonal method (e.g., qPCR, immunofluorescence)
2. **Test additional time points** if dynamic response observed
3. **Investigate downstream signaling** if TAB2 levels change
4. **Repeat with different TAB2 preparations** to confirm specificity
5. **Publish/share data** with complete methodology

---

**Protocol Version**: 1.0  
**Last Updated**: Current date  
**Author**: BioAPEX  
**For**: CHO_TAB2 vs CHO_WT western blot experiment