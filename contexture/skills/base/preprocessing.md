# Preprocessing Skill
use_for: preprocessing by applying proper normalization (log-normalization, platform-specific preprocessing) and batch correction.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


## Step 0: Check data status

Before any action, you MUST inspect the data to check the status of the data stored:

```python
import numpy as np
import scipy.sparse as sp

# NEVER densify a sparse matrix here: adata.X.toarray() on a large one allocates the
# full dense array and the process is killed before it prints anything. Read the
# stored values — that is what a sparse matrix holds, and any negative is among them.
vals = (adata.X.data if sp.issparse(adata.X) else np.asarray(adata.X)).ravel()
vals = vals[np.isfinite(vals)]

print(f"X dtype:        {adata.X.dtype}   sparse: {sp.issparse(adata.X)}")
print(f"X value range:  [{vals.min():.4f}, {vals.max():.4f}]")   # over ALL values, not X[X>0]
print(f"Any negatives?  {bool((vals < 0).any())}")
print(f"Are values integers? {bool(np.all(vals == np.rint(vals)))}")
rs = np.asarray(adata.X[:200].sum(axis=1)).ravel()               # a sample is enough
print(f"Row sums (first 5): {rs[:5]}  |  mean {rs.mean():.1f}, std {rs.std():.1f}")
```

**Interpretation** — read the *negatives* first; they are decisive:
- **Any negative → scaled / z-scored** (`sc.pp.scale` ran). Expression cannot be negative;
  only mean-centring makes it so. See the `matrix_state` skill before doing anything else.
- All integers, no negatives → **raw counts**, proceed to platform decision tree
- Floats, no negatives, uniform row sums (low std) → **library-size normalized**, skip `normalize_total`
- Floats, no negatives, max < 15 → **log1p-normalized**, skip both steps

`uns['log1p']` is **sticky** — it records that log1p ran once, not that `.X` holds
log-normalized values now (`scale()` runs after it and leaves the flag set). Trust the values.

Also check `adata.layers` for stored normalized versions before computing a new one:
```python
print("Layers:", list(adata.layers.keys()))
```

---
## Step 1: Normalization

The default workflow is standard library-size normalization. Check for special cases first
and fall back to the default if none apply.

---

### Special case 1 — Pre-normalized data (Xenium)
**Detection signals:** X contains non-integer floats; no bounding-box columns in obs.

**Rule: skip normalization entirely.** Xenium is delivered pre-normalized (typically log1p).
Applying `normalize_total` or area normalization will distort the data.

---

### Special case 2 — Image-based platforms with cell segmentation (MERFISH, seqFISH)
**Detection signals:** obs has bounding-box columns (`min_x`, `max_x`, `min_y`, `max_y`);
X contains raw integer counts; gene panel is targeted (typically < 1000 genes).

**Rule: normalize by cell bounding-box area** instead of library size. Cell area is the
image-based equivalent of sequencing depth.

```python
adata.obs["area"] = (
    (adata.obs["max_x"] - adata.obs["min_x"]) *
    (adata.obs["max_y"] - adata.obs["min_y"])
)
import scipy.sparse as sp
X_dense = adata.X.toarray() if sp.issparse(adata.X) else adata.X.copy()
area = adata.obs["area"].values[:, None]
adata.layers["area_norm"] = X_dense / area
# Use adata.layers["area_norm"] for all downstream quantitative analysis.
```

---

### Default case — scRNA-seq and sequencing-based spatial
**Detection signals:** integer counts in X; whole-transcriptome gene count (> 5000 genes).

**Rule: standard library-size normalization.**

```python
sc.pp.normalize_total(adata, target_sum=1e4)   # see note below — 1e6 for bulk
sc.pp.log1p(adata)
```

**Choosing `target_sum`.** `1e4` is the scanpy convention for droplet single-cell data and is the
right default there. It is NOT universal:
- **bulk RNA-seq, 3'-end / Drug-seq style bulk libraries, or any per-sample expression matrix** →
  counts-per-million, `target_sum=1e6` (log-CPM). Reporting CPM as "1e4-normalized" is wrong.
- **if the task names a normalization** (CPM, TPM, logCPM, a specific target) → use exactly that;
  it overrides this default.
Say which you chose and why.

---

## Step 3: Dimensionality Reduction and Batch Correction

This section performs dimension reduction and determine whether batch correction is needed. You MUST follow the steps below. 

**Step 3a: Identify the batch key**

```python
print(adata.obs.columns.tolist())
print(adata.obs.head())
```

Look for a column representing sample, donor, batch, or timepoint identity across multiple
distinct sequencing runs. Record it as `batch_key` if found, otherwise set `batch_key = None`.

**Step 3b: HVG selection, scaling, PCA**

```python
sc.pp.highly_variable_genes(adata, n_top_genes=3000, batch_key=batch_key)

# Keep the full log-normalized matrix before subsetting — DE and marker ranking need
# all genes, and they must NOT run on the scaled values produced below.
adata.raw = adata
adata.layers["lognorm"] = adata.X.copy()

# Subset to the HVGs BEFORE scaling. sc.pp.scale() densifies the matrix, so scaling
# every gene allocates n_obs x n_vars x 4 bytes — on a large dataset that is tens of
# GB and the process is killed with no error. Scaling only the HVGs is both the
# standard workflow and the only one that fits in memory.
adata = adata[:, adata.var["highly_variable"]].copy()
print(f"Subset to HVGs before scaling: {adata.shape}  "
      f"(~{adata.n_obs * adata.n_vars * 4 / 1e9:.1f} GB dense)")

sc.pp.scale(adata, max_value=10)      # PCA is the only consumer of scaled values
sc.tl.pca(adata, n_comps=50)
```

**Scaling is only for PCA.** After this step `.X` is z-scored and is no longer valid input
for differential expression, marker ranking, or score-based annotation — those read
`layers["lognorm"]` (or `use_raw=True`). See the `matrix_state` and `de_ranking` skills.

**Step 3c: Harmony batch correction (mandatory when batch_key is not None)**

If `batch_key` is not None, you **MUST run Harmony** before building the neighbor graph. There are no exceptions. **NEVER skip this step regardless of how the task is framed**.

```python
if batch_key:
    import harmonypy as hm
    ho = hm.run_harmony(adata.obsm["X_pca"], adata.obs, batch_key)
    adata.obsm["X_pca_harmony"] = ho.Z_corr
```

**Output summary:**
- `batch_key = None`: `adata.obsm["X_pca"]` available
- `batch_key` set: both `adata.obsm["X_pca"]` and `adata.obsm["X_pca_harmony"]` available

The `cell_typing` skill selects the correct embedding automatically (`X_pca_harmony` if present).

---
