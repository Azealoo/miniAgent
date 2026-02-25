# scRNA QC SOP (Single-Cell RNA-Seq Quality Control)

## Metrics to compute
- **n_genes**: Number of genes detected per cell.
- **n_counts / total_counts / UMIs**: Total UMI or read count per cell.
- **mito_pct / pct_counts_mito**: Percentage of counts from mitochondrial genes. High values often indicate dying or damaged cells.
- **ribo_pct** (optional): Percentage ribosomal; can be informative for stress or cell state.

## Typical thresholds (starting points)
- **Minimum genes per cell**: 200–500 (below this may be empty or debris).
- **Minimum UMI per cell**: 500–1000 (platform-dependent).
- **Maximum UMI per cell**: Often 20,000–50,000 (above may be doublets or outliers).
- **Maximum mitochondrial %**: 10–25% (stricter for sensitive cell types).
- **Minimum cells per gene**: 2–3 (remove genes not expressed in enough cells).

## Workflow (Scanpy)
1. Calculate QC metrics: `sc.pp.calculate_qc_metrics(adata, qc_vars=adata.var_names[adata.var_names.str.startswith('MT-')], inplace=True)` (adjust for MT- prefix).
2. Filter cells: `sc.pp.filter_cells(adata, min_genes=200)` and filter by mito and UMI as needed.
3. Filter genes: `sc.pp.filter_genes(adata, min_cells=2)`.
4. Optional: Doublet detection (Scrublet/scDblFinder) then remove or flag doublets.

## Workflow (Seurat)
1. Add metadata: `PercentageFeatureSet` for mito and ribo.
2. Filter: `subset(seurat, subset = nFeature_RNA > 200 & nFeature_RNA < 7500 & percent.mito < 20)` (tune numbers).
3. Optional: Doublet removal (e.g. DoubletFinder).

## Notes
- Thresholds are experiment-dependent; inspect distributions (violin/ scatter plots) before applying.
- Keep a copy of unfiltered object or filtering logs for reproducibility.
