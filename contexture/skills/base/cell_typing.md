# Cell Typing Skill — clustering, marker identification, and annotation

use_for: clustering, marker gene identification, cell type annotation, on ALREADY PREPROCESSED data from preprocessing.md.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.

## Expected Input

This skill assumes the `preprocessing` skill has already run. That skill produces
`adata.obsm["X_pca"]` (always) and `adata.obsm["X_pca_harmony"]` (when batch corrected).
Do NOT recompute HVGs, PCA, or Harmony here — ALWAYS use the existing embeddings.

## Standard Workflow

Cell typing follows three steps: cluster → find markers → annotate.

---

## Step 1: Select the correct embedding

```python
# Use batch-corrected embedding if available, otherwise uncorrected
use_rep = "X_pca_harmony" if "X_pca_harmony" in adata.obsm else "X_pca"
print(f"Using embedding: {use_rep}")
```

---

## Step 2: Clustering

```python
sc.pp.neighbors(adata, n_neighbors=15, use_rep=use_rep)
sc.tl.umap(adata)
sc.tl.leiden(adata, resolution=0.8)
```

**Resolution guidance:**

- At default, use **0.8**.
- Check marker separability. Ideally every cluster need some features that distinguish it from its neighbouring cluster.
- For targeted panels (MERFISH, ~300 genes): use smaller resolution as smaller feature space limits
  discriminatory power and high resolution creates uninformable noise clusters
- Change resolution if clusters cannot be annotated at all (no interpretable markers)
- ```python
  from sklearn.metrics import silhouette_score
  score = silhouette_score(
      adata.obsm[use_rep],          # use_rep defined in Step 1
      adata.obs["leiden"],
      metric="euclidean",
      sample_size=min(5000, adata.n_obs),
      random_state=0,
  )
  print(f"Silhouette score: {score:.3f}")
  ```

---

## Step 4: Marker gene identification

```python
sc.tl.rank_genes_groups(adata, groupby="leiden", method="wilcoxon")
sc.pl.rank_genes_groups(adata, n_genes=10, sharey=False)
```

Extract top markers per cluster:

```python
markers = sc.get.rank_genes_groups_df(adata, group=None)
top_markers = markers.groupby("group").head(10)
```

---

## Step 5: Annotation

Map clusters to cell types using canonical marker genes. The mapping is many-to-one —
multiple clusters sharing the same markers should get the same label:

For ambiguous clusters, check co-expression of multiple markers before assigning.
Flag clusters as "Unknown" rather than forcing an assignment with weak evidence.

**When merging multiple clusters into the same cell type**, do not rely only on positive markers
alone. For each candidate cluster, also check that it lacks markers associated with related
but distinct populations (negative markers). A cluster with strong positive marker expression
for cell type X but also high expression of a lineage-restricted marker for cell type Y should
be excluded from X or flagged as ambiguous rather than merged in.

---
