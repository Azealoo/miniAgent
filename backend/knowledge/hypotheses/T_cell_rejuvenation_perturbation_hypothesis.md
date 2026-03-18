# T Cell Rejuvenation Perturbation Hypothesis

**Date:** February 25, 2026  
**Goal:** Reverse T cell immunosenescence and restore youthful functional states  
**Cell type:** Human CD4+/CD8+ T cells (aged/old donors)  
**Phenotype goal:** Transcriptional and functional rejuvenation to young T cell state

## Summary
This hypothesis proposes targeting key regulators of T cell aging through CRISPR-based perturbations to reverse immunosenescence. Aged T cells exhibit hallmarks including: increased senescence markers (p16INK4a), metabolic dysfunction, chronic inflammation (inflammaging), and exhaustion (PD-1 upregulation). By perturbing central nodes in these pathways, we aim to restore youthful transcriptional programs and functional capacity.

## Top Candidate Targets

| Gene | Rank Score | Mechanism | Perturbation Type | Risk Level |
|------|------------|-----------|-------------------|------------|
| SIRT1 | 9 | NAD⁺-dependent deacetylase regulating senescence, metabolism, inflammation | Overexpression/activation | Medium |
| CDKN2A | 9 | Encodes p16INK4a, key senescence marker and cell cycle inhibitor | CRISPR KO | Medium |
| MTOR | 9 | Kinase regulating protein synthesis, autophagy, metabolism | CRISPRi or pharmacological inhibition | Medium |
| IL6 | 9 | Pro-inflammatory cytokine driving inflammaging | CRISPR KO or antibody blockade | Low |
| PDCD1 | 9 | PD-1 receptor mediating T cell exhaustion | CRISPR KO or antibody blockade | Medium |
| TP53 | 8 | Tumor suppressor inducing senescence | Partial KD (CRISPRi) | High |
| TERT | 7 | Telomerase maintaining telomere length | Overexpression | High |
| FOXO1 | 7 | Transcription factor for stress resistance and longevity | Overexpression | Low |

## Detailed Hypotheses

### Hypothesis 1: SIRT1 Overexpression
**Rationale:** SIRT1 declines with age, leading to metabolic dysfunction and inflammation. Restoration should improve mitochondrial function and reduce SASP.
**Expected signature:** ↑FOXO1/3, PGC-1α, NRF2, antioxidants; ↓NF-κB targets, SASP factors, p16
**Controls:** NTC, empty vector, SIRT1 inhibitor (EX-527)
**Readouts:** Mitochondrial function, ROS, cytokine production, β-gal staining

### Hypothesis 2: CDKN2A Knockout  
**Rationale:** p16INK4a accumulates with age, causing cell cycle arrest. KO should restore proliferative capacity.
**Expected signature:** ↓CDKN2A, p21; ↑cell cycle genes, proliferation markers
**Controls:** NTC, non-targeting gRNA
**Readouts:** Cell cycle analysis, proliferation assays, senescence markers

### Hypothesis 3: mTOR Inhibition
**Rationale:** mTOR signaling increases with age; inhibition extends lifespan and improves immune function.
**Expected signature:** ↓mTOR pathway, translation; ↑autophagy genes, FOXO targets
**Controls:** NTC, vehicle, mTOR activator
**Readouts:** Autophagy flux, metabolic profiling, protein synthesis

### Hypothesis 4: IL-6 Blockade
**Rationale:** IL-6 drives inflammaging; blockade should reduce chronic inflammation.
**Expected signature:** ↓IL-6, STAT3 targets, inflammatory cytokines; ↑anti-inflammatory genes
**Controls:** NTC, isotype control, IL-6 stimulation
**Readouts:** p-STAT3, cytokine multiplex, T cell differentiation

### Hypothesis 5: PD-1 Blockade
**Rationale:** PD-1 increases on aged T cells, contributing to exhaustion.
**Expected signature:** ↓PD-1, exhaustion markers; ↑activation markers, effector cytokines
**Controls:** NTC, isotype control, PD-L1 stimulation
**Readouts:** PD-1 expression, proliferation, exhaustion marker panel

## Experimental Design
- **Model:** Primary human T cells from young/old donors
- **Approach:** Pooled CRISPR screen with barcoded guides (10-20 targets + NTC)
- **Perturb-seq:** 500-1000 cells/perturbation, biological replicates
- **Readouts:** scRNA-seq (10X), CITE-seq for surface markers
- **Validation:** Functional assays on bulk populations

## Analysis Pipeline
1. QC and normalization (Scanpy/Seurat)
2. Differential expression vs. NTC
3. Pathway enrichment (GO, KEGG, Hallmark)
4. Signature comparison across perturbations
5. Trajectory analysis for "rejuvenation" assessment

## Expected Outcomes
Identification of 2-3 perturbations that significantly shift aged T cells toward youthful transcriptional states with functional improvements. These could inform therapeutic strategies against immunosenescence.

## Risks and Considerations
- Tumor suppressor inhibition (p53, p16) carries cancer risk
- Dose and timing critical for mTOR inhibition
- Context-dependent effects across T cell subsets
- Need for combination approaches for full rejuvenation

## Supporting Literature
- SIRT1 in T cell aging and metabolism
- p16INK4a as senescence biomarker
- mTOR inhibition and lifespan extension
- Inflammaging and IL-6
- PD-1 blockade in T cell exhaustion

## Next Steps
1. Design and clone guide libraries
2. Optimize T cell transduction
3. Pilot experiment with 3-5 targets
4. Scale to full Perturb-seq
5. Functional validation of hits