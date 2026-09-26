# Differential Expression Skill — comparing gene expression across conditions or cell types
use_for: differential expression between groups or conditions, marker recovery, comparing conditions across donors/samples/replicates.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, test or value from this
skill, re-read the task. If it names one — a significance cutoff, a fold-change bound, a specific
test, a normalization — use exactly that and say in your trace that you followed the task. A
task-specified value overrides this skill without exception.

Fall back to the values here only where the task is silent. State which you used and why.

---

## Step 1: Identify what is being compared, and find the replicate column

Clarify before writing any code:
- **What groups?** (condition X vs Y, cell type A vs B, treated vs control)
- **Within what context?** (all cells, or within one cell type)
- **What is the unit of biological replication?** — this decides the test in Step 2.

Print the candidate columns and their values:
```python
print(adata.obs.columns.tolist())
print(adata.obs[["cell_type", "condition"]].value_counts())
```

The replicate column is whatever identifies an **independent biological source**: donor, patient,
subject, individual, sample, cell_line, animal, or replicate. Look for it explicitly — it is
often present and easy to miss.

---

## Step 2: MANDATORY — count replicates before choosing a test

You MUST run this and read the output BEFORE selecting any test. Do not skip it because the
comparison looks simple.

```python
rep_col = "donor"          # the biological replicate column found in Step 1
grp_col = "condition"      # the comparison you are making

census = adata_sub.obs.groupby(grp_col)[rep_col].nunique()
print("independent replicates per group:")
print(census)
print("cells per group:")
print(adata_sub.obs[grp_col].value_counts())
```

### The decision rule — apply it exactly

- **Every group has ≥ 3 independent replicates → use PSEUDOBULK (Step 3A). This is the default.**
- **Any group has < 3 replicates → use a cell-level test (Step 3B), and state the limitation
  explicitly in your trace.**
- **No replicate column exists at all** (e.g. comparing two cell types within one sample) → a
  cell-level test is correct; say so.

**Cells from the same donor are not independent replicates.** Treating thousands of cells from a
handful of donors as independent samples inflates significance dramatically — a few donors' worth
of biological variation gets counted as thousands of observations. This is the single most common
error in single-cell differential expression, and a cell-level test run on a replicated design
will be judged wrong even when the gene list looks plausible.

If you find yourself about to run `rank_genes_groups` on a comparison **between conditions** that
has 3+ donors per group, stop and go to Step 3A instead.

---

## Step 3A: Pseudobulk — the default for replicated designs

Aggregate **raw counts** per replicate (never normalized or log-transformed values), then run a
count-based test.

```python
import decoupler as dc
import numpy as np, pandas as pd
import scipy.sparse as sp

# adata_sub must carry RAW COUNTS — in .X or in a layer (commonly layers["counts"]).
pdata = dc.pp.pseudobulk(
    adata_sub,
    sample_col=rep_col,      # one profile per biological replicate
    groups_col=None,         # or a cell-type column for one profile per replicate x cell type
    layer="counts",          # None if .X already holds raw counts
    mode="sum",              # sum counts — do NOT average normalized values
)
print("pseudobulk matrix:", pdata.shape)
print(pdata.obs[grp_col].value_counts())
```

Then run DESeq2 (`pydeseq2`). Note the exact call signature — `DeseqStats` **requires** a
`contrast`:

```python
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

X = pdata.X.toarray() if sp.issparse(pdata.X) else np.asarray(pdata.X)
counts_df = pd.DataFrame(np.rint(X).astype(int), index=pdata.obs_names, columns=pdata.var_names)
meta_df = pdata.obs[[grp_col]].copy()

# Drop genes with almost no signal — DESeq2 is unstable on all-zero genes.
keep = counts_df.sum(axis=0) >= 10
counts_df = counts_df.loc[:, keep]
print(f"genes kept: {keep.sum()} of {len(keep)}")

# Set the REFERENCE LEVEL before fitting — it decides which coefficient exists, and
# therefore which direction shrinkage is available in. Reference level goes FIRST.
meta_df[grp_col] = pd.Categorical(meta_df[grp_col], categories=["control", "treated"])

dds = DeseqDataSet(counts=counts_df, metadata=meta_df, design=f"~{grp_col}")
dds.deseq2()

# contrast = [column, numerator/test level, denominator/reference level]
res = DeseqStats(dds, contrast=[grp_col, "treated", "control"])
res.summary()

# REQUIRED before log2FoldChange is used for anything.
# `coeff` must be one of the COLUMNS OF res.LFC. pydeseq2 shrinks a COEFFICIENT of the
# design, not a contrast, so the names are patsy-style ("condition[T.treated]") — NOT
# the R/DESeq2 form "condition_treated_vs_control", which raises KeyError here.
# Never guess the name; read it off the object:
print(res.LFC.columns.tolist())          # the ONLY valid values for coeff
res.lfc_shrink(coeff="%s[T.treated]" % grp_col)   # pick from the printed list

de_df = res.results_df.sort_values("padj")
print(de_df.head(20))
```

If the only available coefficient points the opposite way to the contrast you want,
shrink it and negate `log2FoldChange` — and say so in your trace. **Do not skip
shrinkage because the coefficient name did not match your first guess**; unshrunk fold
changes change every downstream number (see below).

`de_df` columns: `log2FoldChange`, `pvalue`, `padj`, `baseMean`.

### Shrink the fold changes — this is part of the workflow, not a refinement

An unshrunk log2FC of a gene with 3 counts in one group and 0 in the other is enormous and
meaningless. Shrinkage pulls low-information fold changes toward zero while leaving well-measured
ones intact.

It matters for **every** downstream use of `log2FoldChange`, not only ranking:

- **ranking** — without it, your top genes are sequencing noise rather than biology;
- **a |log2FC| threshold** — without it, low-count genes clear the bound and the number of genes
  you report as differentially expressed is inflated;
- **counting** — the same inflation, now expressed as a single wrong number.

A quick check that you did it: in a strong stimulation the significant genes should be
predominantly *up*, and the top ones should be recognisable biology. A roughly balanced or
down-skewed list whose top genes are unfamiliar is the classic signature of unshrunk fold changes.

**No shrinkage available?** Impose an expression floor instead — it addresses the same problem
more bluntly:

```python
de_df = de_df[de_df["baseMean"] > 10]      # drop genes with too little evidence to trust
```

If `pydeseq2` is unavailable or fails, a paired/unpaired t-test **on the pseudobulk profiles**
(one value per replicate, log-CPM transformed) is still far better than a cell-level test. Say
which you used.

---

## Step 3B: Cell-level test — only when Step 2 says so

Use when replicates are absent or fewer than 3 per group, or when comparing cell types within a
sample.

```python
sc.tl.rank_genes_groups(adata_sub, groupby=grp_col, method="wilcoxon")
de_df = sc.get.rank_genes_groups_df(adata_sub, group=None)
```

Requires already-normalized, log-transformed data (see the preprocessing skill). ≥ 20 cells per
group is a practical minimum.

**If you used this on a design that had replicates, say so as a limitation** — name the number of
replicates and state that significance is likely overestimated.

---

## Step 4: Multiple testing

`rank_genes_groups` returns `pvals_adj` (Benjamini–Hochberg) automatically; DESeq2 returns `padj`.
For a manual test, correct explicitly:

```python
from statsmodels.stats.multitest import multipletests
_, pvals_adj, _, _ = multipletests(pvals, method="fdr_bh")
```

---

## Step 5: Filter and report

```python
sig = de_df[(de_df["padj"] < 0.05) & (de_df["log2FoldChange"].abs() > 0.5)]   # DESeq2 columns
# cell-level: (de_df["pvals_adj"] < 0.05) & (de_df["logfoldchanges"].abs() > 0.5)
print(f"Significant DE genes: {len(sig)}")
print(sig.head(20))
```

Recommended defaults where the task is silent: adjusted p < 0.05; |log2FC| > 0.5 for subtle
condition effects, > 1.0 for cell-type-level differences. If nothing is significant, relax the
fold-change bound first (0.5, then 0.25) and never drop the adjusted p-value filter.

Any bound on `log2FoldChange` — including one the task specifies — assumes **shrunk** fold changes
(Step 3A). Applying a threshold to unshrunk values silently admits low-count noise and inflates
whatever you report, whether that is a gene list or a count.

**Report the direction and magnitude, not just gene names** — for each reported gene give its
fold change and adjusted p-value.

## If you are asked whether a gene set is enriched among the results

Do not answer from a proportion alone. "100% of these genes went up" is a description, not a
test. Run a formal test — Fisher's exact / hypergeometric for a gene list, or see the
pathway_enrichment skill for ranked enrichment.
