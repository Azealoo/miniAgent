---
type: workflow_heuristic
name: RNA-seq differential expression readiness review template
description: Structured readiness checklist for bulk RNA-seq differential expression work covering design inputs, inspectable files, governance, and go/no-go criteria.
kind: project
scope: project
tags: [rnaseq, differential-expression, readiness-review]
---
# RNA-seq Differential Expression Readiness Review

## Review Context
- **Request Date**: 2026-04-03
- **User Request**: "Preparing an RNA-seq differential expression analysis and want a readiness review before doing anything else"
- **Current Status**: Intent stated, no experimental details provided
- **Scope note**: This template lists the context that should be inspected for a readiness review. It does not confirm that any project files, paths, or prior analyses currently exist.
- **Assumption boundary**: This checklist is for standard bulk RNA-seq differential expression. If the project is single-cell RNA-seq or Perturb-seq, use additional modality-specific QC and design checks instead of applying this template unchanged.

## Work Steps Identified

### Phase 1: Clarify the biological question and design
1. **Question and contrasts**: Define the biological question, primary endpoint, and exact comparisons to test
2. **Replicate structure**: Verify biological replicate count, technical replicates, and whether the design is paired, blocked, or time-course
3. **Confounders and covariates**: Document batch variables, sex, age, donor, lane, operator, or other known confounders
4. **Assay design**: Confirm organism, reference build, library type, strandedness, read layout, and read length

### Phase 2: Verify inspectable inputs
5. **Sample metadata**: Check that a sample sheet maps every file to condition, replicate, and covariates
6. **Raw data inventory**: Locate FASTQ files or a sequencing delivery manifest
7. **QC and preprocessing artifacts**: Review FastQC/MultiQC reports plus alignment or quantification logs if preprocessing has already started
8. **Quantification artifacts**: Confirm whether a count matrix or transcript abundance table already exists and how it was generated

### Phase 3: Check analysis intent and success criteria
9. **Analysis level**: Decide whether the endpoint is gene-level or transcript-level differential expression
10. **Modeling plan**: Choose the DE framework and the model terms required for the design
11. **QC thresholds**: Define the QC cutoffs or failure criteria that would block analysis
12. **Expected outputs**: Specify the required tables, plots, and downstream interpretation deliverables

## Context/Files Required for Inspection

### Required Inputs
1. **Study question and planned contrasts**: What comparison should the DE analysis answer, and what is the primary endpoint?
2. **Sample metadata sheet**: Condition labels, replicate identifiers, pairing/blocking fields, and covariates
3. **Library and assay protocol**: Library type, strandedness, single-end versus paired-end, read length, and any protocol quirks that affect counting
4. **Reference build and annotation**: Genome/transcriptome version plus GTF/GFF or transcript index provenance
5. **Raw data inventory**: FASTQ paths or a sequencing delivery manifest tied to the metadata sheet
6. **QC/preprocessing artifacts**: FastQC, MultiQC, adapter trimming summaries, and alignment or pseudoalignment logs if available
7. **Quantification artifact**: Count matrix or transcript abundance table if generation has already begun
8. **Analysis acceptance criteria**: Required outputs, QC thresholds, and any must-have downstream analyses

### Optional but Useful
9. **Previous analyses or pilot runs**: Helps interpret whether current artifacts are exploratory or production-ready
10. **Execution environment notes**: Cluster/runtime expectations, package locks, or workflow wrappers if operational planning is part of the request

## Compliance & Safety Concerns

### Governance and compliance
- **Human or clinical data**: Confirm IRB/consent status, de-identification rules, and access restrictions before file inspection or downstream sharing
- **Controlled-access data**: Check DUAs, workspace restrictions, and whether the analysis environment is approved for the dataset
- **Data movement**: Verify encryption, access controls, and export restrictions if identifiable or controlled data are involved

### Statistical validity
- **Replicate adequacy**: Enough biological replicates to support the requested contrasts
- **Design correctness**: Pairing, blocking, batch variables, and confounders must be representable in the model
- **Endpoint definition**: The intended DE endpoint and thresholds should be explicit before running a confirmatory analysis

### Reproducibility and traceability
- **Software versions**: Document all tools and versions used
- **Parameter recording**: Save all analysis parameters and commands
- **Reference provenance**: Record genome/annotation/index versions used for counting and interpretation
- **Code management**: Version control for analysis scripts or workflow configs

### Safety boundary
- **No intrinsic wet-lab biosafety issue is implied by a computational DE request alone**
- **Escalate separately** only if the request touches regulated samples, controlled human data, or actions outside standard computational analysis

## Likely Analysis Stages

### Stage 1: Intake and metadata validation
1. Confirm study question, contrasts, metadata completeness, and assay/reference details

### Stage 2: Read-level QC and preprocessing
2. Inspect raw read QC, trimming summaries, and alignment or pseudoalignment quality if raw data are available

### Stage 3: Quantification and sample-level QC
3. Generate or validate the count matrix, then review library size, mapping assignment, and outlier behavior

### Stage 4: Differential expression modeling
4. Fit the chosen DE model, apply multiple-testing control, and evaluate the requested contrasts

### Stage 5: Interpretation and reporting
5. Produce summary tables, QC evidence, plots, and downstream enrichment or interpretation outputs as requested

## Readiness Assessment

### Current Status: ❌ NOT READY TO PROCEED

**Critical Missing Information:**
1. Exact biological question and planned contrasts
2. Replicate structure, pairing/blocking status, and known batch/confounder fields
3. Assay details: library type, strandedness, read layout, and read length
4. Organism, reference build, and annotation provenance
5. Data location plus whether QC, alignment, or count artifacts already exist
6. Expected outputs and QC thresholds for declaring the analysis acceptable

**Gap Analysis:**
- The request gives intent but not the design details needed to judge statistical validity
- No inspectable sample metadata, raw data inventory, QC artifacts, or count matrix were provided
- Governance status is unknown if the dataset contains human or controlled data

### Recommendation

**Immediate Action Required:** Collect the following before calling the analysis ready:

1. **What is the biological question and the exact contrast list?**
2. **What is the sample structure?** Include biological replicates, technical replicates, pairing/blocking, and known confounders
3. **What assay was run?** Include library type, strandedness, single-end versus paired-end, and read length
4. **What organism/reference build and annotation should be used?**
5. **Where are the raw data and metadata files, and what QC/preprocessing artifacts already exist?**
6. **What is the analysis endpoint?** Gene-level or transcript-level DE, plus required outputs and QC thresholds
7. **Does the dataset involve human or controlled data?** If so, what governance requirements apply?

**Next Steps After Information Provided:**
1. Validate the study design against the requested contrasts
2. Inspect the provided files and confirm metadata-to-file consistency
3. Review QC and quantification artifacts or define the preprocessing plan if they do not yet exist
4. Finalize the DE model, acceptance criteria, and downstream output list

## Template for Response

Once you provide the missing information, we can proceed with:
- A design-specific readiness verdict tied to actual inspected inputs
- A QC and preprocessing checklist matched to the assay
- A DE modeling plan with explicit contrasts and covariates
- A governance checklist if the dataset involves human or controlled data
