# MuData Conventions Skill — working with multi-modal objects without corrupting them
use_for: MuData / .h5mu objects — per-modality vs joint state, obs alignment, layers, saving multi-modal results.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


## Why this matters

A MuData is several AnnData objects plus a shared index. The failure mode is not a crash — it
is writing to the wrong place, or silently breaking the alignment that makes the object
co-assayed at all.

---

## Step 1: Inspect before touching

```python
import mudata as md
mdata = md.read_h5mu("<path>.h5mu")
print(mdata)

for name, ad in mdata.mod.items():
    print(f"\n--- {name}: {ad.n_obs} x {ad.n_vars}")
    print("  layers :", list(ad.layers.keys()))
    print("  obsm   :", list(ad.obsm.keys()))
    print("  obs    :", ad.obs.columns.tolist())
    X = ad.layers.get("counts", ad.X)
    sub = X[:100].toarray() if hasattr(X, "toarray") else X[:100]
    print(f"  X: dtype={X.dtype}, max={sub.max():.2f}, integer-valued={np.allclose(sub, sub.astype(int))}")
```

Check the alignment that defines a co-assay object:

```python
names = list(mdata.mod)
ref = mdata[names[0]].obs_names
for n in names[1:]:
    same = list(mdata[n].obs_names) == list(ref)
    print(f"{n} index identical to {names[0]}: {same}")
```

**Identical order, not just identical length.** Equal `n_obs` across modalities proves
nothing — the rows can still be permuted, and every cross-modal statement would then be
comparing unrelated cells.

---

## Step 2: Per-modality obs vs joint obs

Two different places, and they are not synced automatically:

- `mdata["rna"].obs` — belongs to the RNA modality.
- `mdata.obs` — the joint table. Modality columns appear here prefixed (`rna:n_genes`).

`mdata.update()` propagates modality obs/var up into the joint object. It does **not** push
joint columns down into modalities.

```python
mdata["rna"].obs["domain"] = labels
mdata.update()                       # now visible as mdata.obs['rna:domain']
```

**If a task specifies where a column must live, write it exactly there.** Writing `domain` to
`mdata.obs` when the contract asks for `mdata['rna'].obs['domain']` produces an object that
looks complete and reads as missing.

**Align computed vectors by NAME, not position.** When you assign a per-cell or per-gene result
(a Series, an array, or a table sorted by its own value — many scanpy/squidpy outputs are) into
`obs`/`var`, it must line up with the object's index. A result produced on a filtered subset, or
returned in sorted order, is silently misaligned if assigned positionally. Reindex to
`obs_names`/`var_names` first, and assert the index matches before saving.

---

## Step 3: Preserve raw counts in a layer

Several methods need counts after you have overwritten `.X` with normalized values. Keep them
before you normalize:

```python
for name, ad in mdata.mod.items():
    if "counts" not in ad.layers:
        ad.layers["counts"] = ad.X.copy()
```

Then normalize into a named layer *and* `.X` if downstream scanpy calls expect `.X`:

```python
rna.layers["lognorm"] = rna.X.copy()     # after normalize_total + log1p
```

Being explicit about which layer holds which state is what stops the double-normalization
class of bug — the one where `normalize_total` runs twice and nothing complains.

---

## Step 4: Subsetting keeps the modalities aligned

Filtering one modality alone breaks the co-assay property. Apply the intersection:

```python
keep = rna.obs_names[(rna.obs["n_genes_by_counts"] > 200)]
for n in list(mdata.mod):
    keep = keep.intersection(mdata[n].obs_names)

mdata = mdata[keep].copy()
mdata.update()
for n in list(mdata.mod):
    assert list(mdata[n].obs_names) == list(keep), f"{n} lost alignment"
```

---

## Step 5: Saving

```python
mdata.update()
mdata.write("<output_dir>/result.h5mu")

# verify by reading it back — writing succeeds on objects that are missing what you meant to save
chk = md.read_h5mu("<output_dir>/result.h5mu")
for n, ad in chk.mod.items():
    print(f"{n}: layers={list(ad.layers)}, obsm={list(ad.obsm)}, obs={ad.obs.columns.tolist()}")
```

**Save as soon as the required contents exist**, then continue with plots and extras. A result
that exists on disk and is imperfect beats a perfect one that was never written because the
session ended first.

Common write failures worth knowing:

- Objects in `uns` that are not serializable (custom classes, fitted models) — store arrays,
  scalars, and plain dicts.
- A `var`/`obs` column of mixed types — cast to `str` or a proper `category` first.
- Dense conversion of a huge sparse matrix — keep sparse matrices sparse.

---

## Step 6: Report what you wrote

```python
print("saved:", "<output_dir>/result.h5mu")
for n, ad in chk.mod.items():
    print(f"  {n}: {ad.n_obs} x {ad.n_vars} | layers {list(ad.layers)} | obs {ad.obs.columns.tolist()}")
```
