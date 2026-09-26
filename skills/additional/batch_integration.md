# Batch Integration Skill — detecting and correcting batch-driven structure
use_for: multi-sample or multi-timepoint datasets, deciding whether clusters reflect biology or batch, integration decisions.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


**This skill EXTENDS the `preprocessing` skill's Step 3c.** That skill tells you to run Harmony
when a batch key exists. This one covers how to *detect* that batch is driving your result,
and when correcting is the wrong move.

## Why this matters

Datasets are routinely distributed as several samples concatenated together with no
integration. Nothing about the object announces this. If you cluster it as-is, your clusters
may be sample labels wearing a biological costume — and every downstream statement you make
will be about the sequencing run, not the tissue.

---

## Step 1: Find the candidate batch keys

```python
print(adata.obs.columns.tolist())
for c in adata.obs.columns:
    n = adata.obs[c].nunique()
    if 1 < n <= 30 and adata.obs[c].dtype.name in ("category", "object"):
        print(f"  {c}: {n} levels -> {list(adata.obs[c].unique()[:8])}")
```

Look for sample, donor, run, library, slide, timepoint, condition, or replicate identity.

**A key can be both batch and biology.** Timepoint, condition, and treatment are technical
batches *and* the variable of interest when samples were processed separately. Note these —
they need Step 4's judgement, not automatic correction.

---

## Step 2: Measure whether batch is driving the clustering

Do NOT eyeball a UMAP. Cluster first, then cross-tabulate against the candidate key.

```python
import pandas as pd

ct = pd.crosstab(adata.obs["<cluster_key>"], adata.obs["<batch_key>"])
frac = ct.div(ct.sum(axis=1), axis=0)          # per cluster: fraction from each batch
dominant = frac.max(axis=1)                    # per cluster: the most-represented batch

print(frac.round(2).to_string())
print(f"\nmax single-batch fraction: {dominant.max():.3f}")
print(f"median single-batch fraction: {dominant.median():.3f}")
print(f"clusters >90% one batch: {(dominant > 0.9).sum()} / {len(dominant)}")
```

**Interpretation:**

- Fractions near `1 / n_batches` → batches are mixed; clustering reflects shared structure.
- Many clusters at >0.9 from a single batch → **clustering is batch-driven**.
- A few pure clusters among mixed ones → could be a genuinely sample-specific population.
  Do not assume artifact; check its markers before deciding.

With `n` equally-sized batches, a fully mixed cluster sits near `1/n`, so calibrate against
that rather than against zero.

---

## Step 3: Correct, then re-check

```python
import harmonypy as hm
ho = hm.run_harmony(adata.obsm["X_pca"], adata.obs, "<batch_key>")
adata.obsm["X_pca_harmony"] = ho.Z_corr.T          # note the transpose

sc.pp.neighbors(adata, use_rep="X_pca_harmony", n_neighbors=15)
sc.tl.leiden(adata, resolution=<res>, key_added="cluster_corrected", random_state=0)
```

`run_harmony` returns components × cells; `obsm` needs cells × components. **Check the shape**
— a silently transposed embedding produces plausible nonsense:

```python
assert adata.obsm["X_pca_harmony"].shape[0] == adata.n_obs, "harmony embedding is transposed"
```

Then repeat Step 2 on the corrected clustering. Integration that did not change the
batch-fraction profile did not work — report that rather than assuming it did.

---

## Step 4: When NOT to integrate

Batch correction removes variation. If the variation you remove is the answer, you have
destroyed the experiment.

- **The batch key IS the biological question** (treatment, timepoint, genotype). Integrating
  on it can erase the effect you were asked to measure. If samples were processed separately
  and condition is confounded with batch, the two are not separable by any correction — say
  so explicitly rather than silently correcting.
- **A single sample / single run.** No batch, nothing to correct.
- **The task asks what the uncorrected data shows.** Some questions are specifically about the
  presence of batch structure. Answer the question that was asked.

When batch and biology are confounded, the honest output is a statement of the confound plus
the uncorrected result — not a corrected number presented as clean.

---

## Step 5: Report

State the key, the evidence, the decision, and the effect:

```python
print(f"batch_key = <key> ({adata.obs['<key>'].nunique()} levels)")
print(f"before: max single-batch fraction = <x>; after Harmony: <y>")
print(f"decision: <integrated / not integrated> because <reason>")
```
