---
archived: true
archived_on: 2026-04-18
superseded_by: T_cell_rejuvenation_perturbation_hypothesis.md
reason: Earlier, narrower draft (2026-02-03) superseded by the broader 2026-02-25 hypothesis covering SIRT1/CDKN2A/MTOR/IL6/PDCD1/TP53/TERT/FOXO1 targets.
---

# Perturbation Hypothesis: T-cell Rejuvenation

**Date Generated**: 2026-02-03  
**Cell Type**: Aged T-cells (CD4+/CD8+)  
**Goal**: Reverse immunosenescence - restore proliferative capacity, reduce senescence markers, improve mitochondrial function, reduce inflammaging cytokines  
**Method**: CRISPR-based perturbations (KO/KD/OE) with Perturb-seq readout

## Summary
Aging T-cells exhibit immunosenescence characterized by reduced proliferative capacity, increased senescence markers (p16, p21), mitochondrial dysfunction, and chronic low-grade inflammation (inflammaging). This hypothesis proposes targeting key regulators of mitochondrial metabolism and stress response pathways to rejuvenate aged T-cells.

## Top Candidate Targets

| Gene | Score | Pathway | Perturbation Type | Risk | Evidence |
|------|-------|---------|-------------------|------|----------|
| SIRT3 | 8 | Mitochondrial metabolism, mitophagy | Overexpression | Low | PMID:41630039 |
| PRKAA1 | 7 | AMPK signaling, energy metabolism | Activation | Low | Pathway knowledge |
| LKB1 | 6 | AMPK activation, metabolism | Overexpression | Medium | Pathway knowledge |
| FOXO3 | 6 | Transcription factor, stress response, autophagy | Overexpression | Low | PMID:24021689 |
| ERN1 | 5 | ER stress, UPR, mitochondrial ROS | Knockdown/Inhibition | Medium | PMID:40425229 |

## Detailed Hypotheses

### Hypothesis 1: SIRT3 Overexpression
- **Rationale**: SIRT3 is a mitochondrial deacetylase that regulates metabolism and mitophagy. Kaempferol treatment alleviates T-cell immunosenescence via SIRT3-LKB1-AMPK-mitophagy pathway (PMID:41630039).
- **Mechanism**: Enhances mitochondrial quality control, reduces ROS, improves metabolic flexibility.
- **Expected signature**: Upregulation of OXPHOS genes, mitophagy markers (PINK1, PARKIN), downregulation of SASP cytokines.
- **Controls**: Non-targeting sgRNA; positive: doxorubicin-induced senescence.
- **Readouts**: scRNA-seq, β-galactosidase, mitochondrial membrane potential, cytokine secretion.

### Hypothesis 2: PRKAA1 (AMPK) Activation
- **Rationale**: AMPK is a central energy sensor that promotes catabolic processes and inhibits anabolic pathways.
- **Mechanism**: Activates autophagy, fatty acid oxidation; inhibits mTOR signaling.
- **Expected signature**: Increased autophagy genes (LC3, ATG family), decreased mTOR targets, reduced senescence markers.
- **Controls**: Non-targeting sgRNA; AMPK activator (AICAR) as positive control.
- **Readouts**: Autophagy flux (LC3-II turnover), metabolic profiling, proliferation assays.

### Hypothesis 3: LKB1 Overexpression
- **Rationale**: LKB1 (STK11) is an upstream kinase that activates AMPK.
- **Mechanism**: Activates AMPK pathway, enhances mitochondrial biogenesis.
- **Expected signature**: Similar to AMPK activation but potentially broader metabolic effects.
- **Controls**: Non-targeting sgRNA; validate with phospho-AMPK staining.
- **Readouts**: AMPK phosphorylation, mitochondrial content, glucose uptake.

## Experimental Design
1. **Cell source**: Aged human T-cells from donors >65 years or replicatively exhausted in vitro.
2. **Perturbations**: CRISPRa for overexpression, CRISPRi for knockdown, CRISPRko for knockout.
3. **Library**: Include all top candidates + controls (non-targeting, positive senescence inducers).
4. **Readout**: Perturb-seq (10x Genomics) with ≥500 cells per perturbation.
5. **Validation**: Functional assays for proliferation, senescence, mitochondrial function.

## Expected Challenges
1. **Cell viability**: Some perturbations (e.g., ERN1 knockdown) may affect viability.
2. **Compensation**: Redundant pathways may compensate for single-gene perturbations.
3. **Heterogeneity**: Aged T-cell populations are heterogeneous; may need subset analysis.

## Next Steps
1. Design and clone sgRNA libraries for top candidates.
2. Optimize T-cell transduction and perturbation efficiency.
3. Run pilot experiment with 3-5 perturbations to validate approach.
4. Scale to full Perturb-seq screen.

## References
1. Chen W et al. (2026) Kaempferol alleviates T-cell immunosenescence via SIRT3-LKB1-AMPK-mitophagy pathway. *Immun Ageing*.
2. Wan Y et al. (2025) Dual roles of IRE1α inhibition in reversing mitochondrial ROS-induced CD8+ T-cell senescence. *J Immunother Cancer*.
3. Literature on FOXO3, AMPK, and senescence pathways in T-cells.