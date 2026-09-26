# Feature Selection Skill — choosing highly variable genes correctly
use_for: selecting highly variable genes / features before PCA or clustering, on any expression matrix. NOT for spatially variable genes — spatial variability is a different analysis (see spatial_analysis), and NOT for a plain top-genes-by-expression readout.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


**This skill SUPERSEDES the HVG line in the `preprocessing` skill's Step 3b.** That snippet
(`sc.pp.highly_variable_genes(adata, n_top_genes=3000, batch_key=batch_key)`) omits both the
gene filter and the `flavor` argument. Follow the steps here instead.

## Why this matters

HVG selection is silent when it goes wrong. It does not raise, it does not warn — it returns
a gene list. A broken HVG list poisons PCA, the neighbor graph, clustering, and every marker
you report downstream, and the only visible symptom is that your results are subtly bad.

---

## Step 1: Remove genes that cannot be informative

You MUST filter genes before HVG selection.

```python
n_before = adata.n_vars
sc.pp.filter_genes(adata, min_cells=3)
print(f"Genes: {n_before} -> {adata.n_vars} (removed {n_before - adata.n_vars})")
```

Genes detected in almost no cells have unstable, meaningless dispersion estimates, and
dispersion-based HVG methods rank them highly precisely *because* the estimate is unstable.
Skipping this step is the most common way an HVG list fills with noise.

---

## Step 2: Match `flavor` to the state of the data — this is the critical decision

The scanpy HVG flavors expect **different input states**. Passing the wrong state does not
error; it returns garbage.

| flavor | expects | notes |
| --- | --- | --- |
| `seurat` (**scanpy's default**) | **log-normalized** | dispersion-based |
| `cell_ranger` | **log-normalized** | dispersion-based |
| `seurat_v3` | **raw counts** | variance-stabilizing; pass counts via `layer=` |
| *(none)* | **scaled / z-scored** | **no flavor is valid — see below** |

**You MUST pass `flavor` explicitly.** Never rely on the default — if the data is not
log-normalized, the default silently does the wrong thing.

**Determine the state first — use the `matrix_state` skill.** Do not assume, and do not read
the state off `uns['log1p']`: that flag records that `log1p` ran at some point, not that `.X`
holds log-normalized values now (`scale()` runs afterwards and leaves the flag set). Read the
values: **any negative value means the matrix is scaled.**

```python
# Data is CP10K + log1p normalized:
sc.pp.highly_variable_genes(adata, n_top_genes=2000, flavor="seurat", batch_key=batch_key)

# Data is raw integer counts and you want seurat_v3 (layer name is NOT standardised —
# check adata.layers for what is actually there):
sc.pp.highly_variable_genes(
    adata, n_top_genes=2000, flavor="seurat_v3", layer="<the counts layer>", batch_key=batch_key
)
```

If you keep raw counts in a layer, `seurat_v3` with `layer=` pointed at it is safe regardless
of what `.X` currently holds — it reads the layer, not `.X`.

### If the matrix is scaled (z-scored)

**No HVG flavor may be run on it.** Every flavor here is dispersion- or variance-based, and
scaling sets every gene's variance to ~1 by construction — the quantity being ranked has been
erased. `seurat` additionally applies `expm1` internally, which on negative values is not
merely inaccurate but meaningless.

Recover the counts and select from those (`matrix_state` Step 4):

```python
# counts live in a layer -> read them directly, .X can stay scaled
sc.pp.highly_variable_genes(adata, n_top_genes=2000, flavor="seurat_v3",
                            layer="<the counts layer>", batch_key=batch_key)
```

If no counts are recoverable, report that HVG selection is not possible on this matrix rather
than running a flavor anyway.

---

## Step 3: Verify the list before using it

You MUST inspect the selected genes. A correct HVG list on a whole-transcriptome dataset is
dominated by genes with recognisable biology — cell-type markers, structural genes, immune
and stromal programs.

```python
hvg = adata.var_names[adata.var["highly_variable"]]
print(f"n HVG: {len(hvg)}")
print("first 30:", list(hvg[:30]))
```

**Warning signs that the list is broken** — if you see these, go back to Steps 1–2:

- Unnamed clone/contig identifiers dominate (`RP23-…`, `RP24-…`, `AC……`, `AL……`).
- Pseudogenes dominate (names ending `-ps`, `-ps1`, or `Rpl…-ps…`).
- Almost no recognisable marker genes for the tissue you are analysing.
- The list looks like a random sample of the transcriptome.

A useful positive control: name three or four genes you *expect* to vary in this tissue
before you look, then check whether they are present.

```python
expected = ["<marker1>", "<marker2>", "<marker3>"]   # decide these BEFORE looking
print({g: (g in set(hvg)) for g in expected})
```

If none of your expected markers survive HVG selection, the selection is wrong — not the
biology.

---

## Step 4: When to skip HVG entirely

**Targeted panels** (typically < 1000 genes — MERFISH, Xenium, most image-based platforms):
the panel was already curated by the assay designers. Every gene was chosen because it is
informative. Selecting "variable" genes from a targeted panel discards deliberate signal.

**Rule: on a targeted panel, use all genes.** Skip HVG and go straight to scaling/PCA.

```python
if adata.n_vars < 1000:
    print(f"Targeted panel ({adata.n_vars} genes) — skipping HVG, using all genes.")
    # proceed directly to sc.pp.scale / sc.tl.pca
```

**Non-RNA modalities:** dispersion-based HVG is designed for count-based expression data.
For protein/ADT panels see the `protein_adt` skill; for chromatin see the `atac` skill.
Do NOT apply `sc.pp.highly_variable_genes` to those matrices.

**Spatially variable ≠ highly variable.** If the task asks for *spatially* variable genes, that
is a spatial-autocorrelation question (Moran's I / Geary's C on the spatial graph — see the
`spatial_analysis` skill), not dispersion HVG. A highly variable gene can have no spatial
structure, and a spatially structured gene need not top the dispersion ranking. Do not answer a
spatial-variability question with `highly_variable_genes`.

---

## Step 5: Report what you did

State the flavor, the input state it assumed, the gene filter, and the resulting count:

```python
print(f"HVG: flavor=<flavor> on <state>, min_cells=3 filter, n_top_genes=<n> -> {adata.var['highly_variable'].sum()} genes")
```
