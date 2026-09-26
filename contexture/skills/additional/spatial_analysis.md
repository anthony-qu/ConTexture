# Spatial Analysis Skill — using coordinates as evidence, not decoration

use_for: spatial datasets, spatially variable genes / spatial autocorrelation, spatial domains/clustering, neighborhood/niche composition, spatially-defined cell typing, tissue structure counting.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.

## Why this matters

Spatial data is routinely analysed as if it were dissociated single-cell data with a picture
attached — cluster the expression, plot the clusters on the coordinates, done. That answers
expression questions, not spatial ones. Coordinates are measurements. Some questions cannot
be answered without them, and some identities do not exist in expression space at all.

---

## Step 1: Confirm the coordinates and their geometry

```python
print("obsm keys:", list(adata.obsm.keys()))
xy = adata.obsm["spatial"]
print(f"spatial shape: {xy.shape}")
print(f"x range: [{xy[:,0].min():.1f}, {xy[:,0].max():.1f}]  y range: [{xy[:,1].min():.1f}, {xy[:,1].max():.1f}]")
```

Check whether the object holds **multiple sections/samples** sharing one coordinate frame:

```python
# if a section/sample key exists, coordinates may overlap or be offset between sections
for s in adata.obs["<section_key>"].unique():
    sub = adata[adata.obs["<section_key>"] == s].obsm["spatial"]
    print(f"  {s}: x[{sub[:,0].min():.0f},{sub[:,0].max():.0f}] y[{sub[:,1].min():.0f},{sub[:,1].max():.0f}]")
```

**A spatial graph built across sections is meaningless** — it will connect cells that are
centimetres and a microtome apart. Build graphs per section and concatenate the results.

---

## Step 1b: Spatially variable genes (a property of a GENE, not a spot)

"Spatially variable" is **not** "highly variable" — a gene can vary a lot across spots with no
spatial structure at all. Score it with a spatial-autocorrelation statistic on the spatial
graph, not with dispersion HVG:

```python
import squidpy as sq
sq.gr.spatial_neighbors(adata, coord_type="generic", n_neighs=6)
sq.gr.spatial_autocorr(adata, mode="moran", genes=adata.var_names.tolist())
mi = adata.uns["moranI"]          # a DataFrame INDEXED BY GENE, and SORTED BY the statistic
```

**Index hygiene — the trap that silently zeroes this out.** `uns['moranI']` comes back **sorted
by I**, so its row order is *not* `var_names` order. Assigning it back by position pairs every
value with the wrong gene, and the result correlates with nothing. **Align by NAME and verify:**

```python
adata.var["svg_score"] = mi["I"].reindex(adata.var_names)   # align by name — never by position
assert adata.var["svg_score"].notna().mean() > 0.5          # sanity: most genes got a score
```

This rule is general: **any** per-feature or per-cell result you write into `var`/`obs` — a table
keyed by name, or one computed on a filtered subset — must be reindexed to the object's own index
before assignment. Position-based assignment is a silent corruption, not an error.

## Step 3: Making clustering spatially aware

Two standard approaches, in increasing commitment:

**(a) Smooth features over the spatial graph before clustering** — each spot borrows from its
neighbours, so domains become contiguous:

```python
import numpy as np
from sklearn.preprocessing import normalize

A = adata.obsp["spatial_connectivities"]
W = normalize(A + sp.eye(A.shape[0]), norm="l1", axis=1)     # row-stochastic, includes self
adata.obsm["X_pca_smooth"] = W @ adata.obsm["X_pca"]
sc.pp.neighbors(adata, use_rep="X_pca_smooth")
```

**(b) Purpose-built spatial-domain methods** (SpaGCN, STAGATE, and similar) jointly model
expression and location. Use when available and when the task is explicitly about domains.

**Smoothing trades resolution for contiguity, so let the KIND OF LABEL decide.** Cell or spot
identity ("what is this cell") needs the resolution — do NOT smooth, or a rare cell is averaged
into its neighbours and disappears. An anatomical region or spatial domain ("where in the tissue
is this") is contiguous by definition.

**⚠ If you smooth, smooth the FEATURES BEFORE clustering — never the labels afterwards.** A
majority vote over each spot's neighbours only reassigns spots inside a partition that is already
fixed, so it cannot recover a boundary the clustering never found. One pass is usually enough;
repeated passes erase real boundaries.

```python
adata.obsm["X_pca_smooth"] = W @ adata.obsm["X_pca"]
sc.pp.neighbors(adata, use_rep="X_pca_smooth")
sc.tl.leiden(adata, resolution=r, flavor="igraph", n_iterations=2, directed=False)
```

**On clustering resolution**

- Decide how many groups you expect BEFORE you sweep, and say why. Then pick the resolution
  whose cluster count is closest to that number.
- With no expectation to go on, use **0.8** and prefer the coarser end — over-splitting
  collapses agreement with any reference labelling.
- Check marker separability. Ideally every cluster need some features that distinguish it from its neighbouring cluster.
- For targeted panels with less genes: use smaller resolution as smaller feature space limits
  discriminatory power and high resolution creates uninformable noise clusters.
- Change resolution if clusters cannot be annotated at all or no distinguishing markers.

## Step 4: Neighborhood / niche composition

A niche is defined by *what surrounds a cell*, not by the cell itself:

```python
sq.gr.spatial_neighbors(adata, coord_type="generic", n_neighs=15)
A = adata.obsp["spatial_connectivities"]

import pandas as pd
types = pd.get_dummies(adata.obs["<cell_type>"]).values.astype(float)
comp = A @ types                                     # neighbour counts per type
comp = comp / comp.sum(axis=1, keepdims=True)        # fractions
neigh = pd.DataFrame(comp, columns=pd.get_dummies(adata.obs["<cell_type>"]).columns,
                     index=adata.obs_names)
```

Clustering `neigh` gives **cellular neighborhoods** — recurrent tissue microenvironments. To
ask "what fraction of neighborhood X is cell type Y", aggregate `neigh` by the neighborhood
label. Always report the neighbour count (`n_neighs`) — composition numbers are meaningless
without it.

---

## Step 5: Identity that only exists spatially

Some cell states are transcriptomically near-identical to a sibling state and are defined by
**where they are** — by contact with, or proximity to, another structure. Expression
clustering cannot separate them at any resolution, and raising resolution will not help.

The pattern to recognise: the task distinguishes two populations of the same lineage by their
position relative to a third thing.

```python
from scipy.spatial import cKDTree

anchor = adata.obs["<cell_type>"] == "<anchor type>"
tree = cKDTree(adata.obsm["spatial"][anchor.values])
d, _ = tree.query(adata.obsm["spatial"], k=1)
adata.obs["dist_to_anchor"] = d

candidate = adata.obs["<cell_type>"] == "<candidate lineage>"
adata.obs["<subtype>"] = candidate & (adata.obs["dist_to_anchor"] < <radius>)
```

Choose the radius from the tissue's geometry (typical spot spacing, structure size), and
state it. If you cannot justify a radius, say the identity is not confidently resolvable
rather than inventing a cutoff.

---

## Step 6: Counting contiguous structures

"How many structures are there" is a connected-components question on the spatial graph,
restricted to the relevant cells — not a clustering question:

```python
from scipy.sparse.csgraph import connected_components

mask = adata.obs["<cell_type>"].isin(["<type A>", "<type B>"]).values
sub = adata[mask].copy()
sq.gr.spatial_neighbors(sub, coord_type="generic", radius=<r>)     # radius, not kNN
n, labels = connected_components(sub.obsp["spatial_connectivities"], directed=False)
sub.obs["structure_id"] = labels

sizes = pd.Series(labels).value_counts()
n_real = (sizes >= <min_size>).sum()      # drop single-spot specks
print(f"{n} components, {n_real} with >= <min_size> spots")
```

Use **radius**-based neighbours here, not kNN — kNN always connects every cell to k others
regardless of distance, which merges structures that are far apart. State the radius and the
minimum size; both change the count, so both must be reported.

---

## Step 7: Always plot the result on the coordinates

```python
fig, ax = plt.subplots(figsize=(6, 6))
for g in sorted(adata.obs["<key>"].unique()):
    m = (adata.obs["<key>"] == g).values
    ax.scatter(xy[m, 0], xy[m, 1], s=6, label=str(g))
ax.set_aspect("equal"); ax.legend(fontsize=7, markerscale=2)
plt.savefig(f"{plots_dir}/spatial_<key>.png", dpi=150, bbox_inches="tight"); plt.close()
```

Then look at it. Salt-and-pepper where the tissue has structure, or a domain map that ignores
obvious anatomy, is a result you should not report without investigating.
