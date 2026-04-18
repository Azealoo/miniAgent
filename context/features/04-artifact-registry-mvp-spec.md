# Artifact Registry MVP Spec

## Overview

Build a file-first registry that indexes structured artifacts without introducing a database dependency. The registry should make prior runs, evidence cards, compliance reports, and figures discoverable by both semantic search and structured filters. This becomes the backbone for artifact retrieval, auditability, and cross-run reuse.

## Requirements

- Define the registry storage location and format under the project directory.
- Index all artifacts created under the approved artifact layout from the naming standard.
- At minimum, record for each artifact:
  - artifact ID
  - artifact type
  - path
  - hash
  - creation time
  - run ID
  - workflow or tool origin
  - related dataset ID if present
- Support initial artifact classes:
  - workflow runs
  - evidence cards
  - compliance reports
  - protocol runs
  - QA reports
- Support registry refresh on demand and incremental update when a new artifact is written.
- Support simple structured lookup by:
  - run ID
  - artifact type
  - workflow
  - date
  - dataset ID
- Plan for future semantic retrieval, but MVP can start with exact metadata filters plus optional text indexing.
- Ensure the registry does not break if an artifact file is missing, malformed, or partially written; it should mark the record as invalid instead of crashing.
- Add one backend access path for artifact lookup that can be reused later by the agent and frontend.
- Define a registry rebuild command or function so testing can recreate the registry from files alone.

## References

- @backend/api/files.py
- @backend/tools/search_knowledge_tool.py
- @backend/tools/write_file_tool.py
- @backend/config.py
- @backend/graph/memory_indexer.py
- @context/features/02-artifact-naming-standard-spec.md
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/21-evidence-retrieval-mvp-spec.md
- @context/features/24-claim-graph-mvp-spec.md
