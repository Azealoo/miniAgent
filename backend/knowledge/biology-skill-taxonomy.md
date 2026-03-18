# Biology Skill Taxonomy

Use this taxonomy when assigning `category`, `stage`, `species`, and `modality` metadata to skills.

## Core domains

- `bio/literature`
  - Literature search, claim synthesis, evidence tables, target dossiers
- `bio/single_cell_rna`
  - QC, normalization, annotation, differential expression, trajectory, integration
- `bio/perturb_seq`
  - Screen design, guide planning, controls, hit prioritization, validation planning
- `bio/crispr_screen`
  - sgRNA design advice, control selection, follow-up logic
- `bio/multiomics`
  - CITE-seq, RNA plus ATAC, cross-modal interpretation
- `bio/spatial`
  - Spatial QC, domain interpretation, deconvolution, communication
- `bio/molecular_lab`
  - Wet-lab calculations, plate planning, buffer design, cell culture support
- `bio/compute`
  - Pipeline planning, Slurm support, reproducibility, result summarization

## Workflow stages

- `design`
- `qc`
- `preprocess`
- `analysis`
- `annotation`
- `interpretation`
- `prioritization`
- `validation`
- `reporting`
- `utilities`

## Example mappings

- A marker panel builder:
  - `category: bio/single_cell_rna`
  - `stage: annotation`
  - `modality: single_cell_rna`

- A perturbation coverage estimator:
  - `category: bio/perturb_seq`
  - `stage: design`
  - `modality: perturb_seq`

- A Slurm runner helper:
  - `category: bio/compute`
  - `stage: reporting` or `utilities`, depending on the goal

## Metadata tips

- Use `species: human`, `mouse`, or `any` when relevant.
- Use `modality` for the experimental context, such as `single_cell_rna`, `perturb_seq`, `wet_lab`, `literature`, or `compute`.
- Use `tags` for searchable keywords, not for broad categories.
- Use `aliases` for common alternate names or abbreviations.

## Growth strategy

When adding many skills, prefer:
- One skill per clear user job
- Reuse of existing tools
- Shared knowledge documents for common reference material
- Consistent output structure across related skills

Avoid:
- Many tiny skills that only wrap a single database endpoint
- Skills whose names overlap too strongly without clearer metadata
- Category strings that mix domain and output style in the same field
