# Session Memory Upgrade Spec

## Overview

Upgrade session compression from a generic summary into a scientific continuity structure. The current system already compresses chat history, but later biology workflows will need decisions, evidence, results, compliance outcomes, and next steps preserved separately. This phase should keep the current session model working while making summaries much more useful and testable.

## Requirements

- Preserve the current session file format and existing `compressed_context` behavior for backward compatibility.
- Introduce a structured internal summary model with at least these logical sections:
  - decisions and rationale
  - results register
  - evidence register
  - compliance register
  - open questions and next actions
- Ensure automatic compression still triggers based on message count unless later explicitly reconfigured.
- Define how structured summaries are serialized into session files without breaking `load_session_for_agent()`.
- Keep compressed context readable by the LLM and separable by code.
- Update the compression prompt logic so the model must retain:
  - PMIDs and stable IDs
  - file paths and run IDs
  - claims and evidence links
  - blocked or approved risky actions
- Ensure tool calls tied to important results are represented in the compressed output, not discarded.
- Add tests for:
  - migration from old summaries
  - multiple compression passes
  - loading summarized context back into the agent
- Define whether a separate artifact should be emitted for high-value compression summaries once artifact schemas are available.

## References

- @backend/graph/session_manager.py
- @backend/api/chat.py
- @backend/api/compress.py
- @backend/tests/test_session_manager.py
- @frontend/src/lib/store.tsx
- @context/features/03-core-schema-pack-v1-spec.md
- @context/features/18-report-bundle-v1-spec.md
- @context/features/21-evidence-retrieval-mvp-spec.md

## Implementation Notes

- Structured summaries serialize into the existing `compressed_context` string as readable sectioned text blocks headed by `[Scientific Continuity Summary v1]`.
- Multiple compression passes continue to append into `compressed_context` using the current `---` block separator so existing session loading behavior remains compatible.
- Manual and automatic compression share the same structured-summary prompt and normalization logic.
- Compression input now includes archived assistant `tool_calls` so important tool-derived results can survive summarization.
- Normalized summaries enforce a hard 2000-character ceiling while preserving the sectioned continuity format.
- Long archived messages are condensed with head-and-tail preservation plus extracted salient references (for example PMIDs, file paths, run IDs, URLs, and blocked/approved action lines) before they are sent to the summarization model.
- Structured summary parsing accepts common section-heading variants so code can recover sections even when the model uses slightly different labels.

## Deferred Decision

- Do not emit a separate artifact for compression summaries in this phase. Revisit once artifact schemas exist for durable high-value memory summaries.
