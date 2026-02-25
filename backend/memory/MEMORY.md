# Long-term Memory

> This file stores cross-session memory. The agent reads it at the start of each conversation (or retrieves relevant fragments via RAG). Add important information here to persist it across sessions.

<!-- Agent: add memory entries below this line -->

## User Preferences
- Prefers concise answers (direct, to-the-point responses without unnecessary elaboration)

## Notes
- User's name is Johnny and works on AI/biology projects in the hrbomics lab (single-cell and perturbation genomics)

## Lab context
- Lab: hrbomics (Perturb-seq, CRISPR screens, scRNA-seq)
- Cluster: Tillicum HPC (GPFS, Slurm scheduler)
- Key model: GEARS (gene perturbation prediction)
- Data paths: /gpfs/projects/hrbomics/data (raw/norman), /gpfs/projects/hrbomics/predictions (outputs)
- Active conda env for miniAgent: miniAgent (Python 3.11 + Node.js)
- Backend: port 8002 | Frontend: port 3000

## Active agent skills
- 32 biology skills (bio/literature, bio/scRNA, bio/perturbation, bio/calculations, bio/hpc)
- Key new skills: generate_perturbation_hypothesis, critique_hypothesis, pubmed_search, scRNA_qc_checklist
- New tools: ncbi_eutils, uniprot_api, ensembl_api, http_json, slurm_tool, write_file