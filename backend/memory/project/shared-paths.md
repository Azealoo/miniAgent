---
type: project_fact
name: Shared BioAPEX paths and runtime defaults
description: Durable filesystem locations and local runtime defaults that frequently matter during project work.
kind: project
scope: project
tags: [paths, runtime, environment]
---
# Paths

- Main data lives in `/gpfs/projects/hrbomics/data`, including `norman` and `gene2go`.
- Predictions are stored in `/gpfs/projects/hrbomics/predictions`.

# Runtime

- Use the `miniAgent` conda environment for backend and frontend work.
- Backend development defaults to port `8002`.
- Frontend development defaults to port `3000`.
