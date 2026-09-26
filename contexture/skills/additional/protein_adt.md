# Protein / ADT Skill — antibody-derived tags are not a small transcriptome
use_for: protein / ADT / antibody-capture modality — CLR normalization, panel interpretation, isotype controls.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


## Why this matters

An ADT panel is tens of features, not thousands, and every one was deliberately chosen. The
matrix is dense, background is a property of the assay rather than a nuisance, and the RNA
recipe is wrong at every step: there are no "highly variable" proteins worth selecting, and
library-size normalization is not the right correction for antibody data.

---

## Step 1: Inspect the panel

```python
prot = mdata["prot"]
print(f"{prot.n_obs} cells x {prot.n_vars} proteins")
print("panel:", list(prot.var_names))
X = prot.layers.get("counts", prot.X)
Xd = X.toarray() if hasattr(X, "toarray") else X
print(f"nonzero fraction: {(Xd > 0).mean():.3f}   (ADT is dense — expect most entries > 0)")
print(f"per-cell totals: median {np.median(Xd.sum(1)):.0f}")
```

Read the panel before analysing it. The antibodies tell you what the experiment is *about* —
which lineages, which structures, which states the designers cared about — and that should
inform what you look for.

**Every protein in the panel is informative by construction. NEVER run
`sc.pp.highly_variable_genes` on an ADT matrix.**

---

## Step 2: CLR — and the axis is the whole decision

The standard normalization for antibody-derived tags is the **centered log-ratio**, applied
**within each cell, across that cell's proteins**. Antibody data is compositional: what a
count means depends on the other counts in the same cell.

CLR of cell *i*, protein *j*:

```
clr[i, j] = log1p(x[i, j]) - mean_j( log1p(x[i, :]) )
```

The mean is taken **over the proteins of one cell**. Applied this way, **each cell's CLR
values sum to approximately zero**. That is the definition, and it is the check.

```python
import numpy as np

counts = prot.layers["counts"] if "counts" in prot.layers else prot.X
Xd = counts.toarray() if hasattr(counts, "toarray") else np.asarray(counts)

L = np.log1p(Xd)
clr = L - L.mean(axis=1, keepdims=True)      # axis=1 -> per CELL, across proteins
prot.layers["clr"] = clr
prot.X = clr

# VERIFY the axis — this is not optional
print(f"per-cell sums   (should be ~0): {np.abs(clr.sum(axis=1)).max():.2e}")
print(f"per-protein sums (should NOT be ~0): {np.abs(clr.sum(axis=0)).max():.2e}")
```

**The trap:** library implementations differ in their default axis, and some default to
normalizing *across cells within each protein* — the transpose of what you want. It does not
error. The values look like plausible CLR values. Everything downstream is subtly wrong.

If you use a library's CLR function, **run the check above afterwards regardless**. If the
per-cell sums are not ~0 and the per-protein sums are, the axis was wrong — transpose your
call or compute it directly as above.

---

## Step 3: No HVG, no library-size normalization

- **Do not** call `sc.pp.normalize_total` on ADT. Cell-level antibody totals reflect staining
  and size as much as biology; CLR already handles the compositional part.
- **Do not** select variable proteins. With tens of features, use them all.
- Scaling before PCA is optional and panel-dependent; with a small panel, PCA on CLR values
  is often unnecessary — the features are already interpretable and few enough to cluster on
  directly.

---

## Step 4: Isotype and background controls

```python
iso = [p for p in prot.var_names if any(k in p.lower() for k in ("isotype", "igg", "ctrl", "control"))]
print("control features:", iso)
```

Isotype controls measure non-specific binding. If present:

- They should be low and unstructured. An isotype control that is high, or that varies by
  cluster, indicates background that is confounded with your biology.
- Exclude controls from clustering and from marker interpretation — they are QC, not signal.

---

## Step 5: Interpreting protein vs RNA for the same target

Protein and mRNA for the same gene disagree, and the disagreement is biology, not error:

- Protein is longer-lived — surface protein persists after transcription stops.
- Secreted and internalised proteins are detected where they act, not where transcribed.
- Antibody background raises the floor; low mRNA and moderate protein is common and expected.
- **Direction of correlation is more trustworthy than its magnitude.** Report both signals
  rather than reconciling them into one number.

When you are asked to compare a protein readout with its mRNA, compute both from the data and
state both — do not assume they agree, and do not report one as a proxy for the other.

---

## Step 6: Report

```python
print(f"ADT: {prot.n_vars} proteins, CLR per-cell (max |row sum| = {np.abs(clr.sum(1)).max():.2e}), "
      f"controls excluded: {iso}")
```
