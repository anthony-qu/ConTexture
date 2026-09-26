# ATAC Skill — chromatin accessibility is not expression
use_for: ATAC / chromatin accessibility modality — normalization, dimensionality reduction, clustering, peaks vs bins.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


## Why this matters

An accessibility matrix looks like an expression matrix: cells × features, sparse, integer.
Every RNA idiom will run on it without error and give you a wrong answer. Accessibility is
near-binary, far sparser, and its dominant source of variance is sequencing depth — so the
RNA pipeline (CP10K → log1p → HVG → PCA) produces an embedding whose main axis is how deeply
each cell was sequenced.

---

## Step 1: Understand what the features are

```python
atac = mdata["atac"]           # or your AnnData
print(atac.shape)
print("var:", atac.var.columns.tolist())
print("first features:", list(atac.var_names[:5]))
X = atac.layers.get("counts", atac.X)
sub = X[:200].toarray() if hasattr(X, "toarray") else X[:200]
print(f"nonzero fraction: {(sub > 0).mean():.4f}")
print(f"max value: {sub.max():.1f}  |  values in (0,1]: {((sub > 0) & (sub <= 1)).mean():.4f}")
```

- **Peaks** (`chr1:12345-12800`-style names) — called regions, tens to hundreds of thousands.
- **Genome bins** (fixed-width tiles) — hundreds of thousands to millions, coarser and noisier.
- Nonzero fraction of a few percent or less is normal. Do not "fix" it.

Feature count in the hundreds of thousands is expected — do NOT filter to a few thousand
"highly variable" features with `sc.pp.highly_variable_genes`. That function is designed for
count-based expression and its dispersion model does not apply here.

---

## Step 2: TF-IDF, not library-size normalization

**You MUST NOT use `sc.pp.normalize_total` + `sc.pp.log1p` on accessibility data.** That is
the RNA recipe. It weights every feature equally, and in a near-binary matrix that means
ubiquitously-open regions (promoters of housekeeping genes, open in every cell) dominate the
variance while the cell-type-specific distal regions that actually separate cell types
contribute almost nothing.

TF-IDF up-weights features by how *informative* they are — rare accessibility carries more
signal than universal accessibility:

```python
from sklearn.feature_extraction.text import TfidfTransformer

counts = atac.layers["counts"] if "counts" in atac.layers else atac.X
atac.layers["norm"] = TfidfTransformer().fit_transform(counts)   # stays sparse
```

Some workflows binarize first (`X = (X > 0)`), since a fragment count of 3 vs 1 in one region
of one cell is mostly noise. Binarizing is defensible and common; state which you did.

---

## Step 3: LSI — and you MUST drop the first component

Dimensionality reduction on TF-IDF data is **LSI**: truncated SVD on the TF-IDF matrix. Not
PCA on log-normalized counts.

```python
from sklearn.decomposition import TruncatedSVD

n_comp = min(51, atac.layers["norm"].shape[1] - 1, atac.n_obs - 1)
svd = TruncatedSVD(n_components=n_comp, random_state=0)
lsi = svd.fit_transform(atac.layers["norm"])

atac.obsm["X_lsi"] = lsi[:, 1:]        # DROP COMPONENT 1 — see below
```

**The first LSI component captures sequencing depth, not biology.** This is a structural
property of TF-IDF + SVD on sparse near-binary data, not a quirk of one dataset: the strongest
axis of variation is how many total fragments each cell has. Keep it, and depth becomes the
dominant direction of your embedding — your neighbor graph, clusters, and domains will track
library size. This is the single most consequential ATAC mistake, and it is completely silent:
the clusters look fine, they are just wrong.

**Verify it rather than trusting it.** Component 1 should correlate strongly with depth, and
the components you keep should not:

```python
import numpy as np
depth = np.asarray(counts.sum(axis=1)).ravel()
for i in range(4):
    r = np.corrcoef(lsi[:, i], depth)[0, 1]
    print(f"  LSI{i+1} vs depth: r = {r:+.3f}{'   <- depth component' if abs(r) > 0.7 else ''}")
```

If `|r| > 0.7` for component 1, dropping it was correct. If a *later* component is also
depth-correlated, drop that too. If component 1 is *not* depth-correlated, say so and keep it
— but check, don't assume.

---

## Step 4: Graph and clustering on the LSI embedding

```python
sc.pp.neighbors(atac, use_rep="X_lsi", n_neighbors=15, random_state=0)
print("neighbors built on:", atac.uns["neighbors"]["params"].get("use_rep", "X_pca (DEFAULT — WRONG)"))
sc.tl.leiden(atac, resolution=<res>, key_added="<key>", random_state=0)
```

You MUST pass `use_rep="X_lsi"` explicitly. `sc.pp.neighbors` defaults to `X_pca`, and if any
earlier step left an `X_pca` on the object, the default silently uses it — you will cluster
the RNA-style embedding while believing you clustered LSI. **Print the resolved `use_rep` and
check it against your plan.** Writing "cluster ATAC on LSI" in a plan and then calling
`sc.pp.neighbors` without `use_rep` is a real and invisible failure.

---

## Step 5: Linking chromatin to genes

Accessibility features are genomic intervals; genes are not. To relate them:

- **Gene activity scores** — sum accessibility over each gene body ± a promoter flank. A
  coarse proxy for expression; useful for annotation, not a substitute for RNA.
- **Peak–gene links** — correlate peak accessibility with gene expression across cells, for
  peaks within a window of the gene.
- **Motif / TF enrichment** — test motif over-representation in the peaks that mark a cluster
  to nominate the TFs driving it.

The promoter-proximal signal tracks expression far better than distal signal; a distal peak
may regulate a gene hundreds of kilobases away, or nothing at all. Do not claim regulation
from correlation alone.

---

## Step 6: Report

State every choice — each one changes the answer:

```python
print(f"ATAC: {atac.n_vars} features (<peaks|bins>), TF-IDF<+binarized>, "
      f"LSI {atac.obsm['X_lsi'].shape[1]} comps (component 1 dropped, r_depth=<r>), "
      f"leiden res=<res> -> {atac.obs['<key>'].nunique()} clusters")
```
