# Perturb-seq Design Defaults

## Use this document for first-pass planning

These defaults are not universal rules, but they are useful anchors when the user asks for a rough design or sanity check.

## Core design questions

- How many targets are being perturbed?
- How many guides per target are planned?
- What is the desired number of cells per perturbation after filtering?
- How many biological replicates are required?
- What controls are included?

## Default planning considerations

- Include non-targeting controls and at least one positive control when possible.
- Track expected dropout from cell QC, guide assignment failure, and low-count perturbations.
- Distinguish library complexity from final analyzable cell count.
- Plan enough sequencing depth for both transcriptome and guide assignment.

## Useful outputs

- Estimated cells needed before and after QC
- Approximate replicate-aware cell budget
- Control strategy
- Major design risks

## Common risk factors

- Too few cells per perturbation
- No positive control perturbations
- Poor replicate structure
- Ignoring guide assignment loss
- Overly large library for the available sequencing budget
