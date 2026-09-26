# Reference-Based Annotation Skill — when a reference profile is provided, it governs
use_for: a reference / signature / marker-profile dataset is supplied alongside the data — label transfer, scoring spots or cells against reference cell types, deconvolution, and choosing how many groups to make when a reference exists.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
label set from this skill, re-read the task. If it names one — a number of groups, a specific
method, a label vocabulary — use exactly that, and say in your trace that the task specified it.

## Why this matters

A provided reference is not a convenience. It is the task telling you what the answer is made
of. Clustering the data on its own and then glancing at the reference afterwards produces
groups that do not correspond to it, and the result is scored against the reference.

The failure is quiet: every step looks reasonable, the clusters are clean, the markers are
plausible, and the partition still does not match. The usual cause is granularity — the data
supports many clusters, the reference names few, and nothing forced the two to agree.

**If you find yourself about to run de novo clustering to produce the final groups when a
reference profile was provided, stop and use Step 3 instead.** De novo clustering is
still fine as an intermediate step; it is the final answer that must be tied to the reference.

## Step 1: Read the reference before touching the data

```python
ref = sc.read_h5ad(reference_path)
print("reference:", ref.shape)                    # usually rows = labels, cols = genes
print("labels:", list(ref.obs_names))             # THIS IS THE LABEL VOCABULARY
print("n labels:", ref.n_obs)
shared = [g for g in ref.var_names if g in adata.var_names]
print("shared genes:", len(shared), "of", ref.n_vars)
```

Three things to record in your trace before continuing:

- **the label list** — these are the names your output must use;
- **the number of labels** — this bounds your granularity (Step 2);
- **the shared gene count** — everything downstream runs on this intersection, and if it is
  small the reference cannot support fine distinctions.

Do not assume rows are labels. Check: if the reference has thousands of rows it is a cell-level
reference, not a signature matrix, and you should aggregate it to labels first.

## Step 2: The reference bounds your granularity

**Do not produce more groups than the reference supports without saying why.**

This is the rule that most often decides whether the answer matches. If the reference names 5
cell types, a 9-cluster partition cannot align with it, however well-separated those 9 clusters
are. Going finer than the reference needs an explicit reason stated in your trace.

The reference's label list is your label set, and its count is your count. This holds whether an
observation is one cell or a spot covering several: you are naming each observation after the
reference type that best describes it, so there is nothing to name outside that list.

Where the task asks for regions rather than per-observation labels, the number of regions is **at
most** the number of reference labels and usually fewer, because a region is somewhere a
particular mixture recurs. Eleven reference cell types do not imply eleven regions.

When the task says something like "at whatever granularity the data supports" and a reference is
present, the reference is what the data supports. Start at or below its label count.

## Step 3: Score, then assign — the route for BOTH cells and spots

Score every observation against every reference profile on the shared genes and take the best
match. **Use this whether the data is single cells or spots.** A spot does contain several cells,
but naming it after the type that best matches it recovers the dominant type directly, and it
avoids the ways a mixture fit goes wrong (see the note after the code).

```python
import numpy as np
from scipy.stats import zscore

X = adata[:, shared].X
X = np.asarray(X.todense()) if hasattr(X, "todense") else np.asarray(X)
R = np.asarray(ref[:, shared].X)

# correlate each cell with each reference profile, on standardized genes
Xz, Rz = zscore(X, axis=1, nan_policy="omit"), zscore(R, axis=1, nan_policy="omit")
corr = np.nan_to_num(Xz) @ np.nan_to_num(Rz).T / len(shared)

adata.obs["ref_label"] = [ref.obs_names[i] for i in corr.argmax(1)]
adata.obs["ref_score"] = corr.max(1)
print(adata.obs["ref_label"].value_counts())
print("median best-match score:", float(np.median(adata.obs["ref_score"])))
```

Check two things and report both: whether any reference label went unused, and the median best
match score. A label with zero cells is usually real (that type is absent) but a *low* median
score means the reference does not describe this data and you should say so rather than proceed.

`sc.tl.score_genes` per label is an acceptable alternative when the reference is a marker list
rather than a profile matrix.

### Do not reach for mixture deconvolution instead

It is natural to think a spot needs a mixture fit — estimate what share of the spot each type
occupies, then take the largest. Do not do that here. Scoring is the route for both cells and
spots.

The mixture fit fails in ways that are hard to notice from inside the analysis. It is decided by
whichever genes carry the largest values, so where one cell type expresses far more than the
others, the fit collapses onto that type and returns a near-constant answer. Reference profiles
also resemble each other — often correlating above 0.85 — and a fit cannot separate profiles that
are nearly the same, so it silently drops the types that look like everything else. Scoring
compares each observation to each profile independently and does neither of those things.

If a task explicitly asks for the proportions themselves rather than a label, then estimate
proportions — that is a different question and it needs a mixture fit. This section is about
producing a **label**.

**Whatever you fit or score, use the matrix as it is stored — normally the log-normalized one.
Do not undo the log first.** Reversing it with `expm1` is tempting, because cells mix additively
in linear space and a log matrix does not. But once the log is undone, the handful of genes with
the largest values dominates every distance and correlation you compute, and where one cell type
is very highly expressing those genes all belong to it.

## Step 4: Use the reference's names

Write the reference's label strings verbatim into your output column. Do not invent
`cluster_0`-style names when the reference supplies names, do not re-spell them, and do not
merge two reference labels into one of your own unless the task asks for it.

Where the deliverable asks for a region label rather than a per-observation cell type, name each
region after the reference type most common within it, so the mapping is legible, unless the task
specifies a different naming scheme.

## Step 5: Report the correspondence, not just the labels

Before writing the deliverable, print how your labels relate to the reference:

```python
import pandas as pd
print(adata.obs["ref_label"].value_counts())
print("median best-match score:", float(adata.obs["ref_score"].median()))
```

Two things make an answer suspect and are worth checking rather than assuming. If one label takes
almost every observation, the scoring has been dominated by a single profile — go back and check
which genes are driving it. If several reference labels are unused, decide whether those types
really are absent or whether their profiles were too similar to others to ever win; say which,
rather than leaving it unremarked.

Where the deliverable is a set of regions, cross-tabulate region against the per-observation
label. If a region has no dominant type, or two regions are dominated by the same type, your
granularity is wrong — go back to Step 2 rather than reporting the partition.
