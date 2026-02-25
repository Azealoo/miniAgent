# User Profile

> **Note for agent**: This file describes the primary user you interact with. Update it as you learn more about the user through conversation. You can ask the user directly if you are unsure about their preferences or background.

## About the User

- **Name**: (unknown — ask if relevant)
- **Primary language**: Chinese / English (adapt to their message)
- **Technical level**: (unknown — calibrate based on their questions)
- **Lab**: hrbomics biology lab (single-cell / perturbation genomics)
- **Cluster**: Tillicum HPC (GPFS storage, Slurm scheduler)
- **Primary use cases**: Perturb-seq analysis, scRNA QC, literature review, lab calculations, HPC job submission

## Preferences

- Prefers concise answers (direct, to-the-point responses without unnecessary elaboration)

## Notes

- User's name is Johnny and works on AI/biology projects
- Lab focuses on perturbation screens (GEARS model, Perturb-seq/CRISPR)
- Main data lives in /gpfs/projects/hrbomics/data (norman, gene2go)
- Predictions stored in /gpfs/projects/hrbomics/predictions
- Environment: conda miniAgent env (Python + Node), backend port 8002, frontend port 3000
