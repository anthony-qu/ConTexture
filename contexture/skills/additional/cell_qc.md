# Cell QC Skill — choosing filtering thresholds that can say "nothing to remove"
use_for: quality-control filtering of cells, choosing QC thresholds, deciding how many cells to remove.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


## Why this matters

QC filtering is the one step where a *reasonable-looking* method can be guaranteed wrong
before you run it. If your threshold is defined relative to the data's own distribution, it
removes cells whether or not any cell deserves removal — and you will never notice, because
the output looks exactly like a successful filter.

---

## Step 1: Look at the floor before choosing anything

The single most informative number is the **minimum**, not the mean:

```python
import scanpy as sc
sc.pp.calculate_qc_metrics(adata, percent_top=None, log1p=False, inplace=True)

obs = adata.obs
print(f"cells: {adata.n_obs}")
print(f"genes/cell  min={obs['n_genes_by_counts'].min():.0f}  median={obs['n_genes_by_counts'].median():.0f}")
print(f"counts/cell min={obs['total_counts'].min():.0f}  median={obs['total_counts'].median():.0f}")
```

**If the minimum is already above the threshold you would have applied, the data has been
filtered upstream and your job is to remove nothing.** That is a real and common outcome —
public objects are frequently distributed post-QC. "Viable cells", "filtered", or a
suspiciously high minimum are all signals that the filtering already happened.

---

## Step 2: Use absolute thresholds, not percentiles

This is the critical decision.

```python
# WRONG — removes ~1% of cells no matter how clean the data is
threshold = np.percentile(adata.obs["n_genes_by_counts"], 1)

# RIGHT — an absolute criterion, which removes nothing when nothing is bad
sc.pp.filter_cells(adata, min_genes=200)
```

A percentile threshold **removes its quantile by construction**. The 1st percentile removes
1% of cells; that is what a percentile *is*. It cannot return "no cells need removing", because
the answer is fixed by the definition before the data is consulted. On an already-clean object
it removes ~1% of *perfectly good cells* and reports success.

The same trap in other clothing: "remove the bottom N%", "keep the top 99%", "drop the lowest
decile". All are the same thing.

**Rule: a QC threshold must be a statement about cell quality, not about rank.** Absolute
criteria (`min_genes=200`, `min_counts=500`, `pct_counts_mt < 10`) express what a bad cell *is*,
so they are free to match zero cells.

**Where MAD-based cutoffs sit.** `median ± k·MAD` is distribution-relative, but unlike a
percentile it does *not* fix the removal count in advance — on a tight distribution it can
select nothing. It is a reasonable choice for a heavy-tailed dataset. Use it only when you
have first shown the distribution has a tail worth cutting, and always report the count.

---

## Step 3: "Conservative" means few cells removed

When asked for conservative QC, target *clearly* dead cells only — the barcodes nobody would
defend. Prefer the standard permissive floors (`min_genes=200`, `min_counts=500`) and mito
limits at the loose end (10–20%, not 5%).

**Removing 0 cells is a valid, and sometimes the only correct, answer.** Do not reach for a
stricter threshold because a filter that removes nothing feels like a mistake.

---

## Step 4: Check that each criterion applies at all

A QC criterion computed over an absent feature is not conservative — it is undefined.

```python
adata.var["mt"] = adata.var_names.str.lower().str.startswith(("mt-", "mt."))
print(f"mitochondrial genes found: {int(adata.var['mt'].sum())}")
```

If the count is 0, mitochondrial genes were dropped upstream: `pct_counts_mt` will be
identically 0 for every cell, and **it cannot be used as a QC criterion**. Say so and drop it
rather than filtering on a column of zeros. Verify gene naming before concluding they are
absent — species differ in case (`mt-` vs `MT-`), and a naming mismatch looks identical to a
missing feature.

---

## Step 5: Report the count, and reconcile it against the floor

```python
n_before = adata.n_obs
sc.pp.filter_cells(adata, min_genes=200)
print(f"cells: {n_before} -> {adata.n_obs} (removed {n_before - adata.n_obs}, "
      f"{100*(n_before-adata.n_obs)/n_before:.2f}%)")
```

Sanity-check the number against Step 1: if the minimum was 500 genes/cell and a `min_genes=200`
filter removed cells, something is inconsistent — find out what before continuing. If a
conservative filter removes a large fraction of a dataset described as viable or pre-filtered,
your thresholds are wrong, not the data.
