---
type: workflow_heuristic
name: RNA-seq differential expression readiness review - Current Session
description: Readiness assessment for RNA-seq DE analysis initiated in current session, following the shared bulk RNA-seq readiness framework.
---
# RNA-seq Differential Expression Readiness Review

## Review Context
- **Request Date**: Current session
- **User Request**: "I'm preparing an RNA-seq differential expression analysis and want a readiness review before doing anything else. First figure out the work in steps, identify what context or files you would need to inspect, call out any compliance or safety concerns, list the likely analysis stages, and then give me a concise recommendation on whether this request is ready to proceed."
- **Current Status**: Readiness review requested, but only the request text and shared readiness guidance have been inspected so far
- **Inspection boundary**: No sample sheet, FASTQ manifest, QC report, alignment log, or count matrix has been opened yet in this session
- **Scope note**: This assessment is for standard bulk RNA-seq differential expression unless the project is explicitly single-cell RNA-seq or Perturb-seq

## Work Steps Identified

### Phase 1: Clarify the study design
1. **Question and contrasts**: Define the biological question, the primary endpoint, and the exact comparisons to test
2. **Replicate structure**: Record biological replicates, technical replicates, and whether the design is paired, blocked, or time-course
3. **Confounders and covariates**: Capture batch variables, donor effects, sex, age, lane, or other known confounders
4. **Assay details**: Confirm organism, reference build, library type, strandedness, read layout, and read length

### Phase 2: Verify inspectable inputs
5. **Sample metadata**: Confirm that the sample sheet maps files to condition, replicate, and covariates
6. **Raw data inventory**: Locate FASTQ files or a sequencing delivery manifest
7. **QC/preprocessing artifacts**: Review FastQC/MultiQC plus alignment or pseudoalignment logs if preprocessing already started
8. **Quantification artifacts**: Confirm whether a count matrix or transcript abundance table exists and how it was produced

### Phase 3: Define readiness criteria
9. **Analysis level**: Decide whether the target is gene-level or transcript-level DE
10. **Modeling plan**: Choose the DE framework and required model terms
11. **QC thresholds**: Define the criteria that would block or allow the analysis
12. **Expected outputs**: List the required result tables, plots, and downstream interpretation outputs

## Context/Files Required for Inspection

### Required Inputs (Not yet inspected in this session)
1. **Study question and contrast list**: What comparison should the DE analysis answer?
2. **Sample metadata sheet**: Condition labels, replicate identifiers, pairing/blocking fields, and covariates
3. **Library and assay protocol**: Library type, strandedness, read layout, read length, and protocol quirks affecting counting
4. **Reference build and annotation**: Genome/transcriptome version plus GTF/GFF or transcript index provenance
5. **Raw data inventory**: FASTQ paths or sequencing delivery manifest tied to the metadata sheet
6. **QC/preprocessing artifacts**: FastQC, MultiQC, trimming summaries, and alignment or pseudoalignment logs if available
7. **Quantification artifact**: Count matrix or transcript abundance table if quantification has started
8. **Analysis acceptance criteria**: Required outputs, QC thresholds, and downstream deliverables

### Optional but Recommended
9. **Previous analyses or pilot runs**: Useful for interpreting current artifacts without assuming they are production-ready
10. **Execution environment notes**: Cluster/runtime expectations only if operational planning is part of the request

## Compliance & Safety Concerns

### Governance and compliance (status unknown)
- **Human or clinical data**: Need IRB/consent status, de-identification rules, and access restrictions before inspection or sharing
- **Controlled-access data**: Need DUA/workspace restrictions and confirmation that the analysis environment is approved
- **Data movement**: Need encryption and export controls if identifiable or controlled data are involved

### Statistical validity (cannot assess yet)
- **Replicate adequacy**: Need biological replicate counts and design structure before judging power
- **Modelability of the design**: Need pairing/blocking and confounder fields before defining the model
- **Endpoint definition**: Need the intended DE endpoint and thresholds before confirmatory analysis

### Reproducibility (best practices)
- **Software versions**: Document all tools and versions used
- **Parameter recording**: Save all analysis parameters and commands
- **Reference provenance**: Record genome/annotation/index versions used for counting and interpretation
- **Code management**: Version control for analysis scripts or workflow configs

### Safety boundary
- **No wet-lab biosafety concern is implied by a computational DE request by itself**
- **Escalate separately** only if the work involves regulated samples, controlled human data, or actions outside standard computational analysis

## Likely Analysis Stages

### Stage 1: Intake and metadata validation
1. Confirm the study question, contrast list, metadata completeness, and assay/reference details

### Stage 2: Read-level QC and preprocessing
2. Inspect raw read QC, trimming summaries, and alignment or pseudoalignment quality if raw data are available

### Stage 3: Quantification and sample-level QC
3. Generate or validate the count matrix, then review library size, mapping assignment, and outlier behavior

### Stage 4: Differential expression modeling
4. Fit the DE model, apply multiple-testing control, and evaluate the requested contrasts

### Stage 5: Interpretation and reporting
5. Produce summary tables, QC evidence, plots, and downstream interpretation outputs

## Readiness Assessment

### Current Status: ❌ NOT READY TO PROCEED

**Critical Missing Information:**
1. Exact biological question and planned contrasts
2. Replicate structure, pairing/blocking status, and known confounder fields
3. Assay details: library type, strandedness, read layout, and read length
4. Organism, reference build, and annotation provenance
5. Data location plus whether QC, alignment, or count artifacts already exist
6. Required outputs and QC thresholds for calling the analysis acceptable
7. Governance status if the dataset contains human or controlled data

**Gap Analysis:**
- Only the request text and shared readiness guidance have been inspected so far
- No sample metadata, raw data inventory, QC artifacts, alignment logs, or count matrix were provided
- The request gives intent but not the design details needed to judge statistical validity or operational readiness
- Governance status remains unknown if the dataset includes human or controlled data

### Recommendation

**Immediate Action Required:** Collect the following before treating the analysis as ready:

1. **What is the biological question and the exact contrast list?**
2. **What is the sample structure?** Include biological replicates, technical replicates, pairing/blocking, and confounders
3. **What assay was run?** Include library type, strandedness, single-end versus paired-end, and read length
4. **What organism/reference build and annotation should be used?**
5. **Where are the raw data and metadata files, and which QC/preprocessing artifacts already exist?**
6. **What is the analysis endpoint?** Gene-level or transcript-level DE, plus required outputs and QC thresholds
7. **Does the dataset involve human or controlled data?** If so, what governance requirements apply?
8. **If this is not bulk RNA-seq** and is instead single-cell RNA-seq or Perturb-seq, say so now because the readiness checklist changes materially

**Next Steps After Information Provided:**
1. Validate the study design against the requested contrasts
2. Inspect the supplied files and confirm metadata-to-file consistency
3. Review QC and quantification artifacts or define the preprocessing plan if they do not yet exist
4. Finalize the DE model, acceptance criteria, and downstream output list

## Template for Response

Once you provide the missing information, we can proceed with:
- A design-specific readiness verdict tied to actual inspected inputs
- A QC and preprocessing checklist matched to the assay
- A DE modeling plan with explicit contrasts and covariates
- A governance checklist if the dataset involves human or controlled data
