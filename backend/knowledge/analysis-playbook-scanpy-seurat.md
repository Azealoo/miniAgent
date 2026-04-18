# Analysis Playbook: Scanpy and Seurat

## Common pipeline steps (Scanpy)
1. **QC**: Calculate and filter by genes, counts, mito% (see scRNA-QC-SOP).
2. **Normalize**: `sc.pp.normalize_total` then `sc.pp.log1p`.
3. **HVGs**: `sc.pp.highly_variable_genes` (flavor='seurat' or 'cell_ranger').
4. **Scale**: `sc.pp.scale` (optional; often skipped for clustering and used for DE).
5. **PCA**: `sc.tl.pca`, then `sc.pl.pca_variance_ratio` to choose n_comps.
6. **Neighbors**: `sc.pp.neighbors` (use_dim=15–30).
7. **Clustering**: `sc.tl.leiden` or `sc.tl.louvain`.
8. **UMAP**: `sc.tl.umap`.
9. **DE**: `sc.tl.rank_genes_groups` (groupby=cluster or condition).
10. **Annotation**: Use marker genes and references to label clusters (cell type or state).

## Common pipeline steps (Seurat)
1. **QC**: Filter by nFeature_RNA, nCount_RNA, percent.mito.
2. **Normalize**: `NormalizeData`.
3. **HVGs**: `FindVariableFeatures`.
4. **Scale**: `ScaleData` (optional).
5. **PCA**: `RunPCA`, inspect with `ElbowPlot`.
6. **Neighbors and cluster**: `FindNeighbors`, `FindClusters` (resolution tune).
7. **UMAP**: `RunUMAP`.
8. **DE**: `FindMarkers` or `FindAllMarkers`.
9. **Annotation**: Assign identity with marker knowledge.

## Pitfalls
- **Batch**: If multiple batches, run integration (e.g. Harmony, scanorama, or Seurat integration) before clustering.
- **Over-filtering**: Too strict QC can remove rare populations.
- **Doublets**: Can inflate “mixed” clusters; run doublet detection and remove or regress.
- **Resolution**: Cluster resolution (Leiden/Seurat) affects number of clusters; try 0.5–2.0 and compare.
