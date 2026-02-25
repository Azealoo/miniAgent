---
name: normalization_advice
description: Advise on normalization for scRNA (library size, log, SCTransform, etc.).
category: bio/scRNA
version: 1.0
requires_tools: [search_knowledge_base]
requires_network: false
user_invocable: true
---

# Normalization Advice

## When to use
User asks how to normalize single-cell RNA data or which method to use.

## Inputs
- **platform**: Optional (10x, Smart-seq2, etc.); **downstream**: Optional (clustering, DE, etc.).

## Steps

1. **Local**: Use `search_knowledge_base` for lab preferences (e.g. Scanpy vs Seurat).

2. **Options**: Summarize: (1) Library-size normalize + log1p (Scanpy default); (2) SCTransform (Seurat); (3) Pearson residuals. Mention that log-normalization is common for clustering/DE.

3. **Recommend**: For 10x + Scanpy: normalize_total + log1p. For Seurat: SCTransform if preferred. Note HVG selection after normalization.

## Output format
- Short comparison of methods
- Recommended default for stated platform
- One-line downstream note
