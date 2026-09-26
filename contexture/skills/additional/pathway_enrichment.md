# Pathway Enrichment Skill — gene set enrichment, over-representation, pathway activity
use_for: pathway or gene-set enrichment, GSEA, over-representation of a gene list, MSigDB/Hallmark/GO/KEGG pathways, pathway-level interpretation of differential expression.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** If the task names a gene set collection (e.g.
MSigDB Hallmark), specific pathways, a significance cutoff, or a method, use exactly those and say
in your trace that you followed the task. A task-specified value overrides this skill without
exception. Fall back to the values here only where the task is silent.

**If the task names specific pathways, report every one of them by name** — including the ones
that are not significant. "Not enriched (NES = 0.4, FDR = 0.8)" is a result; omitting the pathway
is a missing answer.

---

## Step 1: Choose the method — ranked GSEA or over-representation

| You have | Use | Why |
| --- | --- | --- |
| A full differential-expression result (all genes, with a statistic) | **Ranked GSEA** (Step 2A) | Uses the whole ranking; no arbitrary cutoff; detects coordinated shifts |
| Only a gene list (e.g. "the 200 significant genes") | **Over-representation / ORA** (Step 2B) | All you can do without a ranking |
| An expression matrix and want per-sample or per-cell scores | **Pathway activity** (Step 2C) | Gives a score per observation, not one p-value |

**Prefer ranked GSEA whenever you have run differential expression** — you already have the
ranking, and it is what "GSEA" means when a task asks for it. Do not substitute an
over-representation test on a thresholded list and call it GSEA; they answer different questions
and a task asking for GSEA will not accept ORA.

---

## Step 2A: Ranked GSEA

Rank **every** gene by a signed statistic — not by p-value alone (unsigned), and not by
fold-change alone when a test statistic is available.

```python
import gseapy as gp
import numpy as np, pandas as pd

# de_df: one row per gene. Signed ranking metric.
rnk = de_df.copy()
rnk["metric"] = rnk["log2FoldChange"] * -np.log10(rnk["pvalue"].clip(lower=1e-300))
rnk = rnk[["metric"]].dropna().sort_values("metric", ascending=False)
print(f"ranked genes: {len(rnk)}   top: {rnk.index[:5].tolist()}")

pre = gp.prerank(
    rnk=rnk,
    gene_sets="MSigDB_Hallmark_2020",   # or a local .gmt path, or a dict {name: [genes]}
    permutation_num=1000,
    min_size=10,
    max_size=500,
    seed=0,
    outdir=None,
)
res = pre.res2d.sort_values("NES", ascending=False)
print(res[["Term", "NES", "NOM p-val", "FDR q-val"]].head(20))
```

A simpler ranking metric — the signed test statistic, or just `log2FoldChange` — is acceptable;
say which you used. Gene symbols must match the collection's namespace (Hallmark uses uppercase
human symbols; convert mouse symbols or use a mouse collection).

**Offline alternative** — `gp.prerank` downloads the named collection. If there is no network,
get Hallmark through decoupler and pass it as a dict:

```python
import decoupler as dc
hm = dc.op.hallmark(organism="human")          # DataFrame: source (pathway), target (gene)
gene_sets = hm.groupby("source")["target"].apply(list).to_dict()
pre = gp.prerank(rnk=rnk, gene_sets=gene_sets, permutation_num=1000, seed=0, outdir=None)
```

---

## Step 2B: Over-representation (ORA)

For a gene list with no ranking. The **background matters** — it is the set of genes that could
have been detected, not all genes in the genome.

```python
import gseapy as gp
enr = gp.enrichr(
    gene_list=sig_genes,                       # list of gene symbols
    gene_sets=["MSigDB_Hallmark_2020"],
    background=adata.var_names.tolist(),       # genes actually tested
    organism="human",
    outdir=None,
)
print(enr.results[["Term", "Overlap", "Adjusted P-value", "Genes"]].head(20))
```

Offline equivalent with decoupler:
```python
import decoupler as dc
ora = dc.mt.ora(...)      # see dc.mt.ora signature; needs the net DataFrame from dc.op.hallmark()
```

---

## Step 2C: Pathway activity per sample or per cell

When you want a score per observation rather than one enrichment p-value:

```python
import decoupler as dc
net = dc.op.hallmark(organism="human")
dc.mt.gsea(data=adata, net=net)          # or dc.mt.ulm / dc.mt.aucell / dc.mt.ora
# scores land in adata.obsm — inspect keys with adata.obsm.keys()
```

Useful for "is this pathway suppressed in a dose-dependent way" — score each sample, then relate
the score to the dose.

---

## Step 3: Report what enrichment actually says

For every pathway you report, give:
- **NES** (normalised enrichment score) — sign gives direction: positive = enriched in the
  up-ranked end, negative = the down end.
- **FDR q-value** — recommended significance bar where the task is silent: FDR < 0.25 for
  exploratory GSEA (the GSEA convention), FDR < 0.05 for a strict claim. Say which you applied.
- **Leading-edge genes** — the genes driving the signal, which is what makes the result
  interpretable.

Common mistakes to avoid:
- Reporting only significant pathways when the task named specific ones to examine.
- Reporting a pathway direction without the NES sign.
- Running enrichment on a gene list you thresholded, then calling it GSEA.
- Using all genes in the annotation as background for ORA instead of the tested genes.
- Concluding "pathway X is active" from enrichment alone — enrichment is about coordinated
  ranking of member genes, not about pathway activity in any mechanistic sense.
