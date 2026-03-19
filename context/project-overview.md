# BioAPEX Project Overview

A transparent, file-first biologist-assistant system for scientific workflows, evidence synthesis, protocol support, and reproducible computational biology.

---

## Mission

BioAPEX exists to help biologists move faster **without sacrificing rigor**.

The core product goal is not just to answer questions. It is to help users:

- run structured scientific workflows
- preserve provenance
- generate auditable artifacts
- connect claims to evidence
- enforce safety and compliance gates
- make reproducible work easier than ad hoc work

BioAPEX should behave less like a generic chatbot and more like a careful scientific collaborator with visible reasoning, visible execution, and durable outputs.

---

## Core Problem

Biology work is often fragmented across:

- chat tools
- notebooks
- scripts
- cluster jobs
- protocol docs
- paper notes
- supplementary tables
- folder conventions that only one person understands

This creates recurring problems:

- irreproducible analyses
- missing provenance
- unsupported conclusions
- weak handoff between wet-lab and computational work
- difficult audits of what was run, why it was run, and what evidence supported the result

BioAPEX solves this by making workflows, evidence, and outputs **explicit, structured, and inspectable on disk**.

---

## Product Direction

BioAPEX is a **biologist-assistant platform**, not a general note-taking app and not a hidden-agent black box.

The long-term direction is to support:

- computational biology workflows such as QC, quantification, and downstream analysis
- literature triage and evidence-card generation
- protocol execution support with deviation tracking
- compliance and safety gating
- provenance-rich reporting and export
- HPC-backed execution for real analysis runs

The product should always prefer:

- explicit workflow steps over implicit multi-tool behavior
- structured artifacts over only chat text
- evidence-backed synthesis over unsupported claims
- conservative safety behavior over risky automation

---

## Primary Users

| User Type | Needs |
| --- | --- |
| Computational biologist | Repeatable workflows, QC visibility, run tracking, evidence-backed interpretation |
| Wet-lab scientist | Protocol guidance, deviation logging, reagent/sample traceability, safe escalation |
| Translational or biomedical researcher | Literature grounding, claim tracking, report-ready outputs, compliance awareness |
| Bioinformatics core or platform team | Standardized pipelines, provenance bundles, reproducibility, HPC integration |

---

## Core Capabilities

### 1. Transparent Agent Interaction

The assistant should stream:

- retrieval events
- tool calls
- workflow progress
- final outputs

Users should be able to inspect what the system did rather than trust hidden internal behavior.

### 2. File-First Scientific Artifacts

Important outputs should exist as files, not only as chat text.

Examples include:

- dataset manifests
- workflow run records
- protocol-run records
- evidence cards
- compliance reports
- QA reports
- report bundles
- provenance exports

### 3. Structured Scientific Workflows

Repetitive scientific tasks should become explicit workflows with:

- required inputs
- declared steps
- QC gates
- failure states
- output contracts

This is especially important for analysis tasks that should be rerunnable and reviewable.

### 4. Evidence-Centered Reasoning

Biological claims should be grounded in structured evidence whenever possible.

BioAPEX should support:

- literature retrieval
- normalized entity grounding
- evidence cards
- claim-to-evidence links
- contradiction-aware review over time

### 5. Safety and Compliance Gating

BioAPEX must not treat biosafety, privacy, or human-subject concerns as optional warnings.

The system should support:

- deterministic preflight checks
- blocked actions
- approval-required flows
- auditable compliance decisions

### 6. HPC and External Workflow Integration

The system should be able to hand off real workloads to external execution environments while keeping metadata, provenance, and audit behavior under BioAPEX control.

---

## Current Architecture Direction

BioAPEX currently follows a backend/frontend split:

- `backend/`: FastAPI service, agent runtime, tool registry, sessions, skills, memory, knowledge, and execution logic
- `frontend/`: Next.js interface for chat, state management, tool traces, file inspection, and future workflow visualization

The system is intentionally:

- file-first
- inspectable
- editable
- extensible through skills and context files

This should remain true as the platform matures.

---

## Architectural Principles

- **File-first**: durable state should live in files whenever practical.
- **Transparent**: users should be able to inspect prompts, skills, tool traces, and artifacts.
- **Structured**: important scientific work should produce typed or schema-driven outputs.
- **Reproducible**: runs should be reconstructable from stored inputs, parameters, and artifacts.
- **Safe by default**: risky work should block or escalate before execution.
- **Composable**: workflows, skills, evidence, and tools should work together through explicit contracts.

---

## What BioAPEX Is Not

BioAPEX is not:

- a generic developer productivity tool
- a note-taking or bookmark-stashing product
- a purely conversational assistant with no durable outputs
- a system that hides important execution details behind polished summaries
- a workflow engine that ignores scientific evidence and compliance

---

## Near-Term Priorities

The current roadmap should emphasize:

1. structured artifacts and schemas
2. compliance and safety gates
3. workflow definitions and runner logic
4. QC-aware computational workflows
5. evidence retrieval and grounding
6. provenance, audit, and export
7. production hardening

These priorities should guide feature decisions across both backend and frontend work.

---

## Success Criteria

BioAPEX is succeeding when:

- users can rerun scientific work from saved artifacts
- important claims are linked to evidence
- workflows fail safely when required metadata is missing
- outputs are understandable by both humans and machines
- session history does not become the only source of truth
- the rigorous path becomes faster and easier than the ad hoc path

---

## Current Status

- In active architecture and feature-definition stage
- Core transparent agent foundation already exists
- Moving toward workflow-driven, evidence-backed, production-grade biology execution

---

**BioAPEX** — rigorous biological work, made faster, safer, and more traceable.
