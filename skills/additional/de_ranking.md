# DE Ranking Skill — turning a DE result into a defensible gene list
use_for: ranking or reporting top marker/DE genes from a differential-expression or group-contrast result; marker gene recovery. NOT for a plain descriptive ranking such as top genes by mean expression.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


**This skill EXTENDS the `differential_expression` skill.** That skill covers *running* the
test correctly. This one covers what happens after: how the list is ranked, filtered, and
reported. Most wrong gene lists come from a correct test ranked badly.

**It also SUPERSEDES the `preprocessing` skill's Step 3b for any DE workflow.** That step runs
`sc.pp.scale(adata, max_value=10)`, which overwrites `.X` in place. Follow Step 0 here before
ranking anything.

## Why this matters

A DE test can be statistically perfect and still hand you a top-20 that contains none of the
real biology. Ranking is a separate decision from testing, and the default ranking is rarely
the one the question asks for.

---

## Step 0: Test on log-normalized values — never on scaled values

`sc.pp.scale()` z-scores every gene to mean 0 / variance 1 and **overwrites `.X`**. If you
scaled for PCA (as the standard preprocessing pipeline does) and then run a DE test, the test
reads the scaled matrix, because `rank_genes_groups` uses `.X` by default.

This is silent and it is fatal:

- Every gene now has ~equal variance, so the between-group separation the test ranks on has
  been flattened toward a constant.
- Fold changes computed from centred values are meaningless — the sign of a "mean expression"
  is now an artifact of centring, not of biology.
- Ranks come back dominated by genes with no biological relationship to the contrast.

**Rule: DE and marker ranking MUST run on log-normalized values.** Check the state before you
test (see the `matrix_state` skill): **if `.X` contains negative values it is scaled, and it is
not valid input for a DE test.**

The fix is to keep the log-normalized values before scaling destroys them:

```python
adata.layers["lognorm"] = adata.X.copy()   # BEFORE sc.pp.scale
sc.pp.scale(adata, max_value=10)           # only PCA needs this
sc.tl.pca(adata, n_comps=50)
...
sc.tl.rank_genes_groups(adata, groupby="<group>", method="wilcoxon", layer="lognorm",
                        use_raw=False)
```

`rank_genes_groups` reads `.X` unless told otherwise. Be explicit every time:

- `layer="lognorm"` → test the stashed log-normalized matrix.
- `use_raw=True` → test `adata.raw` (only if `.raw` actually holds log-normalized values).

If you did not stash a layer and `.X` is already scaled, rebuild from the counts
(`matrix_state` Step 4). Do **not** proceed on the scaled matrix.

A cheap sanity check before you trust any ranking:

```python
import numpy as np, scipy.sparse as sp
Xd = adata.layers["lognorm"] if "lognorm" in adata.layers else adata.X
v = (Xd.data if sp.issparse(Xd) else np.asarray(Xd)).ravel()
assert (v >= 0).all(), "DE input contains negatives -> matrix is scaled, not log-normalized"
```

---

## Step 1: Decide what "top" means — p-value and fold change answer different questions

Before ranking, state which you want:

- **Ranked by significance** (p-value / padj) → "which genes am I most confident changed?"
  Biased toward highly expressed genes, where power is high.
- **Ranked by effect size** (log2FC) → "which genes changed the most?"
  Biased toward **low-count genes**, where fold changes are wildly unstable.

If the task says "top N upregulated genes ranked by fold change," it is asking for effect
size — which means you MUST address the low-count instability in Step 2. Never rank by raw
log2FC without doing so.

---

## Step 1b: SPOT-BASED SPATIAL DATA — fold change is compressed, and ranking by it fails

**Applies whenever a "sample" is a multi-cellular SPOT**, not a single cell: Visium, DBiT-seq,
Spatial-CITE-seq, Spatial-Mux-seq, spatial ATAC+RNA. Check this before choosing a ranking.

**Why the usual ranking breaks.** Every spot is a *mixture* of cell types. Comparing two groups
of spots compares two mixtures whose composition differs only by a fraction, so a gene that is
genuinely 50x enriched in one cell type shows up as a fold change near 1. Effect sizes are
compressed by construction — they measure how much the *composition* shifted, not how much the
*gene* shifted. Ranking on them ranks noise.

**What to do:**

1. **Do not rank by raw log2FC.** In a compositional contrast it is close to uninformative, and
   the top of the list will be sparsely-detected genes with unstable ratios.
2. **Prefer the test statistic** — scanpy's `rank_genes_groups` `scores` column (the rank-sum z)
   — which rewards a *consistent* shift across many spots rather than a large ratio in a few.
3. **But verify with detection rates before trusting it.** Pull `pct_in` / `pct_out` for your top
   genes. A gene detected in ~the same fraction of both groups is a consistency artefact, not a
   marker: with hundreds of spots per group the z statistic will happily rank a 98.4%-vs-97.2%
   gene near the top. Require a real gap in detection or mean level, not just a small p.
4. **"No gene survives FDR" is an expected outcome here, not evidence of no biology.** Do not
   conclude the contrast is empty and stop. Report the ranking with its effect sizes and say
   plainly that nothing reached significance.
5. **Ask whether a two-group spot test is the right instrument at all.** For a spatial question,
   a spatial statistic (Moran's I on the score), or deconvolution followed by a test on estimated
   proportions, is often the better answer than a Wilcoxon over spot groups.

**Worked evidence (Spatial-CITE-seq tonsil, 2000-gene panel, T-cell zone vs rest, 316 vs 2176
spots).** Canonical T-zone markers had log2FC 0.08–0.45 and *no* adjusted p below 0.73. Their
rank among 2000 genes:

| marker | raw log2FC | rank-sum z |
| ------ | ---------- | ---------- |
| TRAC   | 297        | **6**      |
| CCL21  | 426        | **14**     |
| LTB    | 582        | **23**     |
| CCL19  | 332        | 115        |

Ranking by raw log2FC put **none** of them in the top 50; ranking by z put three there. Note
also that LTB was detected in 98.4% of zone spots vs 97.2% elsewhere — exactly the artefact
point 3 warns about, so it should be reported with that caveat rather than as a headline marker.

*Scope note: this is measured on one tissue. The mechanism (mixture dilution) is general to spot
assays, but treat the specific ranking recommendation as a strong default to verify, not a law.*

---

## Step 2: Shrink fold changes before ranking by them

An unshrunk log2FC of a gene with 3 counts in one group and 0 in the other is enormous and
meaningless. Shrinkage pulls low-information fold changes toward zero while leaving
well-measured ones intact. This is a standard, expected part of the DESeq2 workflow — not an
optional refinement.

**With pydeseq2, you MUST call `lfc_shrink` before ranking by `log2FoldChange`:**

```python
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

dds = DeseqDataSet(counts=counts_df, metadata=meta_df, design_factors=[...])
dds.deseq2()

stat_res = DeseqStats(dds, contrast=[...])
stat_res.summary()

# REQUIRED before ranking by effect size.
# `coeff` must be one of the COLUMNS OF stat_res.LFC — pydeseq2 shrinks a COEFFICIENT of
# the design, not a contrast, and those are patsy-style names like "condition[T.treated]".
# Do NOT guess a name and do NOT use the R/DESeq2 form "<condition>_<test>_vs_<ref>";
# it is not a pydeseq2 coefficient and raises KeyError. Read the real names off the
# object:
print(stat_res.LFC.columns.tolist())        # the ONLY valid values for coeff
stat_res.lfc_shrink(coeff=stat_res.LFC.columns[-1])   # or the one you want, by name
de = stat_res.results_df
```

**Direction matters, and you set it BEFORE `deseq2()`.** The available coefficient is
whichever level pandas treats as non-reference, so make the reference explicit up front:

```python
meta_df[grp_col] = pd.Categorical(meta_df[grp_col], categories=["control", "treated"])
# -> coefficient "condition[T.treated]" = treated vs control
```

If the only coefficient available points the other way, shrink it and negate
`log2FoldChange`, and say in your trace that you did. Do not skip shrinkage because the
name did not match what you expected.

If you rank by `log2FoldChange` without this line, your top genes will be sequencing noise.

**No shrinkage available?** Impose an expression floor instead — it addresses the same
problem more bluntly:

```python
de = de[de["baseMean"] > 10]          # drop genes with too little evidence to rank
```

---

## Step 3: Filter before you rank

```python
sig = de[(de["padj"] < 0.05) & (de["log2FoldChange"] > 0)]      # direction as the task asks
sig = sig[sig["baseMean"] > 10]                                  # expression floor
top = sig.sort_values("log2FoldChange", ascending=False).head(20)
print(top[["baseMean", "log2FoldChange", "padj"]])
```

For single-cell Wilcoxon via `rank_genes_groups`, the equivalent guards are a detection floor
and reporting the detection fractions:

```python
sc.tl.rank_genes_groups(
    adata, groupby="<group>", method="wilcoxon",
    pts=True,                      # adds detection fractions
)
de = sc.get.rank_genes_groups_df(adata, group="<group of interest>")
de = de[(de["pvals_adj"] < 0.05) & (de["pct_nz_group"] > 0.10)]   # detected in >10% of the group
```

---

## Step 4: Sanity-check the list against expected biology

You MUST look at the list and ask whether it reflects the contrast you ran. Decide what you
expect **before** you look — a well-characterised perturbation or a well-defined cell state
has a known signature, and if none of it appears, the analysis is wrong, not the biology.

**Warning signs the list is not measuring your contrast:**

- **Ribosomal / translation / proteasome / chaperone genes dominate** (`Rpl…`, `Rps…`,
  `Eif…`, `Psm…`, `Hsp…`). These track cell size, stress, and capture efficiency. They
  surface when there is no expression floor, or when the groups differ in quality rather
  than biology. If your "cell-state markers" are ribosomes, you are looking at an artifact
  or you have selected the wrong group.
- **Mitochondrial genes dominate** (`mt-…`, `MT-…`) — usually a QC problem, not a result.
- **Unnamed clones or pseudogenes appear** (`RP23-…`, `AC……`, `…-ps1`) — no expression floor.
- **The expected signature is entirely absent.** A strong, well-characterised stimulus with
  zero canonical response genes in the top 20 means the pipeline is broken.

When a list looks like this, do NOT report it. Return to Steps 2–3.

---

## Step 5: Gene identifier hygiene

You MUST check what `var_names` actually contains before reporting gene names.

```python
import re
vn = adata.var_names.astype(str)
n_ens = sum(bool(re.match(r"ENS[A-Z]*G\d+", v)) for v in vn)
print(f"var_names: {len(vn)} total, {n_ens} Ensembl-style IDs")
print("sample:", list(vn[:5]))
print("var columns available:", adata.var.columns.tolist())
```

- **A mixture of Ensembl IDs and symbols in one reported list is always an error.** It means
  some genes had no symbol mapping and fell back to the ID.
- If `adata.var` has a symbol column (`gene_symbol`, `gene_name`, `feature_name`), map to it
  and report symbols consistently.
- Never report a list with raw IDs mixed into it — a grader, or a reader, cannot match them.

---

## Step 6: Report

State the ranking criterion, the filters, and the direction:

```python
print(f"Top {len(top)} genes: padj<0.05, baseMean>10, log2FC>0, LFC-shrunk, ranked by log2FoldChange")
print(list(top.index))
```
