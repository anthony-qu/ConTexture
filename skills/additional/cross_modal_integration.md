# Cross-Modal Integration Skill — combining modalities measured on the same cells
use_for: co-assayed multi-omic data — joint embeddings, choosing an integration method, deciding which modality defines spatial domains.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


## Why this matters

In co-assayed data every modality was measured on the *same* cells or spots — the
correspondence is given, not inferred. That makes integration easier than the unpaired case
and makes two decisions load-bearing: **which method**, and **which modality should define the
answer**. Defaulting to "concatenate everything and cluster" or "RNA is the real data" is a
choice made by omission, and it is usually wrong.

---

## Step 0: Prepare each modality in its own idiom first

Integration cannot repair a badly prepared modality — it will faithfully propagate the damage
into the joint space, where it is harder to see.

- RNA → log-normalize → HVG (`feature_selection`) → PCA
- Protein/ADT → CLR per cell (`protein_adt`) — no HVG, no library-size normalization
- ATAC → TF-IDF → LSI, **first component dropped** (`atac`)

Each modality's embedding must be correct **on its own** before you combine anything. Verify
each one separately.

---

## Step 1: Decide which modality should define the answer

This is the decision most often skipped. Do not assume RNA.

Ask: **which modality carries the structure the question is about?** In some tissues,
architecture is borne by protein or by chromatin state, and the transcriptome is the *noisiest*
view of it. A joint embedding that averages a strong signal with a weak one can be worse than
the strong modality alone.

Evidence to gather before choosing — cluster each modality separately and compare:

```python
# per-modality clusterings on their OWN embeddings, matched cluster counts
for name, ad, rep in [("rna", rna, "X_pca"), ("prot", prot, "X_clr_or_pca"), ("atac", atac, "X_lsi")]:
    sc.pp.neighbors(ad, use_rep=rep, n_neighbors=15, random_state=0)
    sc.tl.leiden(ad, resolution=<res>, key_added="solo", random_state=0)
    print(f"{name}: {ad.obs['solo'].nunique()} clusters")
```

Then compare them to each other, and — for spatial data — check which produces the most
spatially coherent map (`spatial_analysis`, Step 2). A modality whose solo clustering is
speckled is not carrying the architecture; one whose solo clustering is contiguous and
anatomically plausible probably is.

**State your choice and your reason.** "Domains were defined on <modality> because <evidence>"
is a required part of the answer, not a footnote. If the task names the domain-defining
modality, follow the task.

---

## Step 2: Choose an integration method — what each one assumes

| Method | Assumes | Use when | Watch out for |
| --- | --- | --- | --- |
| **Concatenate embeddings** | components are comparable in scale | quick baseline; modalities of similar quality | scale imbalance — **must standardize first** |
| **WNN** (muon `pp.neighbors`) | paired cells; each modality has a usable graph | you want a per-cell modality weight | weights are an output worth reporting (**when the object has fewer than 200 cells, set `n_multineighbors` to less than the cell count — the default of 200 crashes the interpreter**) |
| **MOFA+** | shared latent factors, linear | interpretable factors; >2 modalities | linear; factors need interpretation |
| **totalVI** | RNA + protein, counts, deep generative | RNA+ADT with batch structure | needs raw counts, GPU-ish, slow |
| **MultiVI** | RNA + ATAC, counts, deep generative | RNA+ATAC, tolerates partial pairing | slow; needs raw counts |

**Concatenation without standardizing is a silent failure.** RNA PCs and ATAC LSI components
have different variances; whichever is larger dominates the joint distance, and you have
accidentally weighted the modalities by an implementation detail.

```python
from sklearn.preprocessing import StandardScaler
import numpy as np

joint = np.hstack([
    StandardScaler().fit_transform(rna.obsm["X_pca"][:, :30]),
    StandardScaler().fit_transform(atac.obsm["X_lsi"][:, :30]),
])
rna.obsm["X_joint"] = joint
```

Also decide how many components each modality contributes — equal counts is a defensible
default, but it *is* a weighting choice. Say what you chose.

**WNN** learns the weighting instead of assuming it, and the learned per-cell modality weight
is itself informative — it tells you which modality is more locally reliable (**when the object
has fewer than 200 cells, set `n_multineighbors` to less than the cell count**):

```python
import muon as mu
# n_multineighbors defaults to 200. If the object has fewer cells than that, the call walks off
# the end of an array and ABORTS THE INTERPRETER — no exception, no traceback, nothing written.
# It must be STRICTLY LESS than n_obs: measured on a 157-spot object, 156 works while 157, 158
# and the default 200 all dump core.
mu.pp.neighbors(mdata,                       # WNN across mdata.mod
                n_multineighbors=min(200, mdata.n_obs - 1))
# per-cell modality weights land in mdata.obs, e.g. 'prot:mod_weight'
print([c for c in mdata.obs.columns if "mod_weight" in c])
```

⚠ **This bites whenever you SUBSET before integrating** — a task that hands you a few hundred
cells, or any analysis restricted to one region, lands under the default without warning.
Guard the call rather than remembering the case.

---

## Step 3: Verify the alignment before trusting the joint space

```python
assert list(rna.obs_names) == list(atac.obs_names), "modalities are not aligned!"
```

Co-assayed modalities share a cell/spot index. If the order differs — after a subset, a copy,
a filter applied to one modality only — the joint embedding pairs the wrong cells and produces
confident nonsense. **Check the index identity explicitly, not the shape.** Matching `n_obs`
proves nothing.

If a QC step drops cells from one modality, apply the intersection to all modalities and
re-check.

---

## Step 4: Report the per-modality results alongside the joint one

Always produce the solo clusterings from Step 1 as well as the joint one. They are the only
way to say whether integration helped, and they are frequently what the task actually asks
for. Report cluster counts for all three.

**Integration is not automatically better.** If the joint result is worse than a single
modality — less coherent, less interpretable — say so. Forcing a joint embedding because
the pipeline has an integration step is how a weak modality contaminates a strong one.

---

## Step 5: Report

```python
print(f"integration: <method>; RNA <n> comps + <mod> <n> comps, standardized: <yes/no>")
print(f"domains defined on: <modality/joint> because <evidence>")
print(f"clusters — joint: <a>, rna: <b>, <mod>: <c>")
```
