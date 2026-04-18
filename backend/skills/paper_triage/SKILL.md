---
name: paper_triage
description: Triage a paper for biological relevance, extract the main claims, and separate evidence-backed takeaways from abstract-only impressions.
category: bio/literature
version: 1.0
requires_tools: [ncbi_eutils, evidence_retrieval, evidence_review, python_repl]
requires_network: true
user_invocable: true
tags: [paper-triage, abstract, literature, relevance]
aliases: [abstract_triage, paper_relevance_check]
species: any
modality: literature
stage: interpretation
stability: stable
safety_level: low
---

# Paper Triage

## Purpose

Decide whether a paper is worth deeper follow-up and summarize the strongest claims, methods, and limitations with clear provenance.

## When to use

Use this skill when the user pastes an abstract, provides a title or PMID, or asks whether a paper is relevant to perturb-seq, single-cell RNA-seq, or a related biology question.

## Required inputs

- **paper details**: abstract text, title, DOI, PMID, or citation fragment
- **research question** (optional): the biological question the user wants the paper judged against

## Steps

1. Normalize what the user supplied: abstract-only, title-plus-question, or PMID/citation-backed request.
2. If a title, citation, or PMID is available, use `ncbi_eutils` or `evidence_retrieval` to ground the paper metadata before judging relevance.
3. If the user is asking a question about what the paper supports, use `evidence_review` to distinguish supported conclusions from unresolved claims whenever enough source material is available.
4. Use `python_repl` if helpful to organize the paper into a compact table covering relevance, methods, claims, and limitations.
5. If only abstract text is available, say explicitly that the triage is abstract-only and lower confidence than a metadata-backed or evidence-reviewed pass.
6. Return the triage result with provenance, caveats, and the most useful follow-up action.

## Output format

- **Biological context or assumptions**: the disease, system, assay, or research question used to judge relevance.
- **Evidence or source basis**: whether the triage came from `ncbi_eutils`, `evidence_retrieval`, `evidence_review`, or abstract-only text.
- **Relevance and claims**: High / Medium / Low fit plus the main claims and key methods.
- **Caveats or ambiguity**: missing full text, abstract-only limitations, or unclear alignment with the user's question.
- **Recommended next step**: retrieve full evidence, compare with a second paper, or move into a deeper evidence review.

## Failure modes

- No usable citation details: say the triage is provisional and based only on the pasted text.
- Metadata mismatch: call out title, PMID, or abstract inconsistencies before summarizing.
- Over-broad relevance question: ask what assay, disease, or mechanism the user cares about most.

## Examples

- "Is this paper relevant to Perturb-seq in T cells?"
- "Triage this abstract and tell me whether it is worth reading in full."
