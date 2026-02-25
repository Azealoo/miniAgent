# Perturb-seq Best Practices

## Overview
Perturb-seq combines single-cell RNA sequencing with CRISPR-based perturbations to measure transcriptional effects across many genes and cells in one experiment.

## Experimental design
- **Library design**: Include non-targeting controls (NTC) and multiple guides per target when possible. Balance number of perturbations with cell coverage (aim for ≥100–500 cells per perturbation for power).
- **Replicates**: Biological replicates (e.g. different cultures or batches) improve robustness. Document batch in metadata for downstream batch correction.
- **Controls**: Wild-type or NTC cells are essential for baseline comparison and doublet/multiplet assessment.

## QC and preprocessing
- **Cell QC**: Filter by UMI count, gene count, and mitochondrial percentage (e.g. mito < 10–20%). Remove obvious empty droplets and damaged cells.
- **Doublets**: Use Scrublet or scDblFinder; expect higher doublet rate in pooled screens. Consider removing doublets or modeling them.
- **Ambient RNA**: In droplet-based data, consider ambient correction (e.g. SoupX, cellBender) if contamination is suspected.
- **Normalization**: Library-size normalization + log1p is standard; SCTransform or Pearson residuals are alternatives. Then select HVGs and scale.

## Analysis
- **Differential expression**: Compare each perturbation to NTC (or WT). Use methods that account for UMI count and batch (e.g. MAST, Wilcoxon with batch covariate, or pseudobulk DESeq2).
- **Effect size**: Report log2FC and adjusted p-value; consider effect size thresholds (e.g. |log2FC| > 0.5) for prioritization.
- **Pathway and signature**: Run gene set enrichment (GO, KEGG, Reactome) on DE genes. Compare signatures across perturbations to cluster similar effects.

## Caveats
- Guide-level variability: multiple guides per gene help distinguish on-target from off-target.
- Cell type and context: effects depend on cell type; stratify or annotate clusters when interpreting.
- False positives: use FDR control and replication to reduce false discovery.
