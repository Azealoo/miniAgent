# Pseudobulk and Replicate Design

## When pseudobulk is preferred

- The biological replicate is the sample, donor, mouse, or independent culture.
- Many cells are measured per sample and the user wants condition-level differential expression.
- The design includes replicate structure, batch, donor, treatment, or timepoint effects.

## Common guidance

- Aggregate counts by `sample × cell_type` or `sample × cluster`.
- Do not treat individual cells as independent biological replicates.
- Use a design matrix that reflects the real replication unit.
- Report both effect size and adjusted p-value.
- Track the number of cells contributing to each pseudobulk profile.

## Warnings

- Very small cell counts per sample-cluster pair can destabilize inference.
- Strong imbalance across samples may require filtering or careful normalization.
- If only one replicate exists per condition, pseudobulk interpretation is limited.

## Useful outputs

- Aggregation key
- Minimum cell count threshold
- Suggested covariates
- Recommended downstream DE framework
