---
name: batch_integration_advisor
description: Recommend a batch-integration strategy and explain the tradeoffs for preserving biology versus removing technical effects.
category: bio/single_cell_rna
version: 1.0
requires_tools: [search_knowledge_base, python_repl]
requires_network: false
user_invocable: true
tags: [batch, integration, harmony, scanorama, seurat]
aliases: [integration_strategy_helper]
species: any
modality: single_cell_rna
stage: preprocess
stability: stable
safety_level: low
---

# Batch Integration Advisor

## Purpose

Help the user choose an integration strategy for single-cell datasets while preserving the biology they care about.

## When to use

Use this skill when the user asks how to integrate batches, donors, or experiments, or whether they should integrate at all.

## Required inputs

- **datasets or batches**: a short description
- **main goal**: clustering, annotation transfer, visualization, or DE
- **known biology to preserve**: condition, treatment, donor, timepoint, lineage, or unknown

## Steps

1. Search `knowledge/batch-integration-playbook.md` using `search_knowledge_base`.
2. Identify the likely technical sources of variation versus the biological signal the user wants to keep.
3. Recommend a strategy such as Harmony, Scanorama, Seurat integration, or no integration.
4. Use `python_repl` if it helps to structure options or decision criteria.
5. Include diagnostics the user should check after integration.

## Output format

- **Recommended strategy**
- **Why it fits the stated goal**
- **What could go wrong**
- **Suggested diagnostics**

## Failure modes

- Too little information: ask what the user wants to preserve.
- DE-focused question: warn that integrated embeddings are not always the right input for DE.
- Strongly non-overlapping cell states: warn that integration may over-correct.

## Examples

- "Should I use Harmony or Seurat integration for three donor batches?"
- "I want to integrate two conditions but preserve treatment response. What should I do?"
