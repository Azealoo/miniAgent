# Batch Integration Playbook

## Goal

Choose a batch-integration strategy that removes technical variation without erasing true biology.

## Typical options

- Harmony
  - Good when the workflow is PCA-based and the user wants a lightweight correction layer.
- Scanorama
  - Useful for partially overlapping datasets and non-identical compositions.
- Seurat integration
  - Common in mixed-R or Seurat-native workflows.

## Decision points

- Are cell states expected to overlap strongly across batches?
- Is the task clustering, visualization, annotation transfer, or DE?
- Are there donor or condition effects that should be preserved?
- Are replicates balanced across conditions?

## Practical warnings

- Over-integration can remove real condition biology.
- Use unintegrated counts or carefully justified models for DE.
- Evaluate both technical mixing and biological preservation.

## Useful diagnostics

- UMAP split by batch and condition
- kBET or LISI-like mixing diagnostics
- Marker preservation checks
- Neighbor composition by batch
