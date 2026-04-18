---
name: feature
description: Manage the BioAPEX current-feature workflow from scoping through review and completion
argument-hint: load|start|review|explain|test|complete
---

# Feature Workflow

Manages the BioAPEX feature lifecycle using the current feature file as the working contract.

## Working File

@context/current-feature.md

### File Structure

current-feature.md has these sections:

- `# Current Feature` - keep this heading as-is
- `## Status` - must be exactly one of: Not Started | In Progress | Completed
- `## Goals` - direct, implementation-oriented goals with enough detail to build without guessing
- `## Notes` - structure, constraints, file paths, assumptions, and decisions that matter during implementation
- `## History` - concise completed work entries, appended over time

## Task

Execute the requested action: $ARGUMENTS

| Action | Description |
|--------|-------------|
| `load` | Load a feature spec or inline description |
| `start` | Begin implementation and set the feature in motion |
| `review` | Run the BioAPEX-specific review flow |
| `explain` | Document what changed and why |
| `test` | Run the relevant verification flow for this repo |
| `complete` | Finalize the feature state and prepare it for commit/merge |

See [actions/](actions/) for detailed instructions.

If no action provided, explain the available options.
