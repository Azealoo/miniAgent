---
type: workflow_heuristic
name: RNA-seq differential expression readiness assessment
description: Readiness assessment for small-study RNA-seq DE analysis based on available context inspection.
---
# RNA-seq Differential Expression Readiness Assessment

## Context Inspection Summary

### What was actually inspected:
1. ✅ RNA-seq readiness review templates in `memory/project/`
   - `rnaseq-de-readiness-review.md` - comprehensive template
   - `rnaseq-de-readiness-review-current.md` - current session template
2. ✅ Example RNA-seq files in `artifacts/examples/rnaseq/`
   - Sample sheet with 6 samples (3 control, 3 treated)
   - Paired-end FASTQ files
   - Count matrix and normalized counts
3. ✅ Knowledge base search for RNA-seq guidance
   - Found general RNA-seq QC and analysis guidance
   - No specific small-study RNA-seq DE templates found

### What was NOT found:
1. ❌ User's actual study design details
2. ❌ User's sample metadata or data files
3. ❌ Specific small-study RNA-seq DE analysis plan
4. ❌ Governance/compliance information for user's data

## Systematic Readiness Plan for Small-Study RNA-seq DE

### Phase 1: Design Validation (Critical for small studies)
1. **Biological question**: What hypothesis is being tested?
2. **Contrast definition**: Exact comparison groups (e.g., treated vs control)
3. **Replicate structure**: Number of biological replicates per group (minimum 3 recommended for small studies)
4. **Confounder assessment**: Batch effects, technical variables, known covariates

### Phase 2: Technical Readiness
1. **Data availability**: FASTQ files or count matrix location
2. **Metadata completeness**: Sample sheet with all experimental variables
3. **QC status**: Existing QC reports or need for QC pipeline
4. **Reference information**: Genome build, annotation version

### Phase 3: Analysis Planning
1. **DE method selection**: DESeq2, edgeR, or limma-voom
2. **Model specification**: Formula including covariates
3. **QC thresholds**: Library size, gene detection, outlier criteria
4. **Output requirements**: Result tables, visualizations, downstream analyses

## Readiness Decision

### Current Status: ❌ **NOT READY TO PROCEED**

**Missing Critical Information:**
1. **Study design**: No biological question, contrasts, or replicate structure provided
2. **Data location**: No indication of where user's actual data files are located
3. **Metadata**: No sample sheet or experimental variables provided
4. **Governance**: Unknown if data involves human/controlled material

**Small-Study Specific Concerns:**
- Power limitations with few replicates require careful design
- Increased risk of false positives/negatives
- Need for conservative multiple testing correction
- Importance of batch effect assessment

## Next Steps

**Immediate Actions Required:**
1. Provide the biological question and exact contrasts
2. Share sample metadata sheet with replicate structure
3. Indicate data location (FASTQs or count matrix)
4. Clarify if this is bulk RNA-seq (not single-cell/Perturb-seq)

**Once Information Provided:**
1. Validate design adequacy for small-study DE
2. Review metadata completeness and consistency
3. Check for batch effects and confounding
4. Recommend appropriate DE method and QC thresholds

**Small-Study Recommendations:**
- Aim for at least 3 biological replicates per group
- Consider paired/blocked design if possible
- Use conservative FDR correction (e.g., Benjamini-Hochberg)
- Include batch as covariate if present
- Consider using DESeq2 with `lfcShrink` for stable effect sizes