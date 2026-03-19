# BioAPEX

A transparent, file-first biologist-assistant system for scientific workflows, evidence synthesis, protocol support, provenance-rich artifacts, and reproducible computational biology.

## Context Files

Read the following to get the full context of the project:

- @context/project-overview.md
- @context/coding-standards.md
- @context/ai-interaction.md
- @context/current-feature.md

## Mission

BioAPEX is built to make rigorous biological work faster, safer, and more traceable.

When working in this repo:

- prefer structured workflows over hidden agent behavior
- prefer file-based artifacts over chat-only outputs
- preserve provenance and reproducibility
- ground important claims in evidence when possible
- enforce safety and compliance checks before risky execution
- keep the system transparent and inspectable

## Commands

- Conda env name: `miniAgent`
- Conda env path: `/gpfs/home/yininz6/.conda/envs/miniAgent`
- Backend dev server: `./start-backend.sh`
- Frontend dev server: `./start-frontend.sh`
- Direct backend run: `cd backend && uvicorn app:app --port 8002 --host 0.0.0.0 --reload`
- Frontend dev: `cd frontend && npm run dev`
- Frontend build: `cd frontend && npm run build`
- Frontend production server: `cd frontend && npm run start`
- Frontend lint: `cd frontend && npm run lint`
