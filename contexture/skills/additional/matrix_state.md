# Matrix State Skill — knowing what is actually in `.X` before you run anything
use_for: determining whether an expression matrix holds raw counts, normalized, log-normalized or scaled values, before choosing any method that assumes one of them.

## Parameters here are RECOMMENDATIONS, not requirements

**First priority is what the task specifies.** Before using any threshold, parameter, method or
gene set from this skill, re-read the task. If it names one — a normalization target, a cutoff, a
number of genes, a resolution, a specific method — use exactly that, and say in your trace that
you followed the task. A task-specified value overrides this skill without exception.

**Fall back to the values here only where the task is silent.** They are defaults for the common
case, chosen to be reasonable rather than universal. State which you used and why.


**This skill SUPERSEDES Step 0 of the `preprocessing` skill.** That check filters to
`X[X > 0]` before reporting the value range, which makes negative values — the one
signal that identifies scaled data — impossible to see. It also offers no "scaled"
category to land in. Use the procedure here instead.

## Why this matters

Almost every method in scanpy assumes a particular input state and **none of them check**.
Give a dispersion-based method z-scored input and it does not raise, does not warn, and
returns a plausible-looking answer that is wrong. The state of `.X` is invisible unless
you look, and it changes under you: `normalize_total`, `log1p` and `scale` all overwrite
`.X` in place.

If you get this wrong, everything downstream is wrong, and nothing will tell you.

---

## Step 1: Read the state from the values, not from metadata

```python
import numpy as np
import scipy.sparse as sp

X = adata.X
vals = (X.data if sp.issparse(X) else np.asarray(X)).ravel()
vals = vals[np.isfinite(vals)]

has_neg = bool((vals < 0).any())
is_int  = bool(np.all(vals == np.rint(vals)))
vmin, vmax = float(vals.min()), float(vals.max())

print(f"dtype={X.dtype}  min={vmin:.3f}  max={vmax:.3f}  negatives={has_neg}  all-integers={is_int}")
print("layers:", list(adata.layers.keys()), "| raw:", adata.raw is not None)
print("var cols:", list(adata.var.columns), "| uns keys:", list(adata.uns.keys()))
```

**Do NOT compute the minimum over `X[X > 0]`.** Masking to positives discards exactly the
evidence you need. Take the minimum over all values.

---

## Step 2: Map the values to a state

| negatives | all integers | typical max | state | what it means |
| --- | --- | --- | --- | --- |
| no | yes | large (100s–1000s) | **raw counts** | nothing applied yet |
| no | no | large, rows near-equal | **library-size normalized** | `normalize_total` ran; no `log1p` |
| no | no | small (usually < 15) | **log-normalized** | `normalize_total` + `log1p` ran |
| **yes** | no | ~2–10 (or a clip bound) | **scaled / z-scored** | `scale()` ran — mean-centred |

**Negative values mean the matrix is scaled.** Expression counts cannot be negative; only
centring makes them so. There is no other common reason for a negative in `.X`.

Corroborating structural tells, which you can read without touching values:

- `adata.var['mean']` and `adata.var['std']` present → `sc.pp.scale` wrote them.
- `adata.uns['log1p']` present → `log1p` ran **at some point**.

---

## Step 3: `uns['log1p']` does not mean the data is log-normalized now

This flag is **sticky**. `sc.pp.scale()` runs *after* `log1p` in every standard pipeline and
does not clear it. So a scaled matrix still advertises `uns['log1p']`.

**Rule: `uns['log1p']` records history, not current state.** It tells you `log1p` ran. It
does not tell you what `.X` holds now. Trust the values (Step 1); use the flag only to
confirm what the values already told you.

The same applies to any provenance key: it records that a step ran, not that its output is
still what is in `.X`.

---

## Step 4: If the state is wrong for what you need, recover it — do not re-derive it

**First: "wrong" is defined by what CONSUMES the matrix next — not by a canonical ideal.**
- If *your own* next step needs a different state (your HVG / DE / clustering needs counts or
  log-norm), re-derive it from the counts. ← the usual case.
- If a **provided** artifact consumes it — a fitted model, a saved scaler, a labelled reference
  embedding — that artifact fixes the input contract (feature order, normalization, gene set).
  **Conform to it; do not re-transform the matrix into your preferred form.** Re-normalizing or
  re-ordering the input to a fitted transform breaks the contract and its output collapses.
- Take the **smallest** action that unblocks the next step. Do not re-normalize, re-order, or
  re-cluster a matrix that is already in the state its next consumer wants.

Scaling is **not invertible** in practice. Never try to "un-scale". Find the counts instead:

```python
for cand in ("counts", "raw_counts", "raw", "umi_counts", "spliced"):
    if cand in adata.layers:
        print(f"raw counts available at adata.layers['{cand}']")
        break
else:
    print("no counts layer; check adata.raw:", adata.raw is not None)
```

Layer names are **not standardised** — check what is actually there rather than assuming
`counts`. Then either pass `layer=` to methods that accept it, or rebuild from the counts:

```python
adata.X = adata.layers["<the counts layer>"].copy()
sc.pp.normalize_total(adata, target_sum=1e4)   # see note below — 1e6 for bulk
sc.pp.log1p(adata)
```

**Choosing `target_sum`.** `1e4` is the scanpy convention for droplet single-cell data and is the
right default there. It is NOT universal:
- **bulk RNA-seq, 3'-end / Drug-seq style bulk libraries, or any per-sample expression matrix** →
  counts-per-million, `target_sum=1e6` (log-CPM). Reporting CPM as "1e4-normalized" is wrong.
- **if the task names a normalization** (CPM, TPM, logCPM, a specific target) → use exactly that;
  it overrides this default.
Say which you chose and why.

If no counts are recoverable anywhere, say so explicitly in your report rather than
proceeding on a matrix whose state does not match your method.

---

## Step 5: Preserve the state you will need later

`sc.pp.scale()` destroys the log-normalized values that differential expression and marker
ranking require. Scaling is needed for PCA, but PCA is usually the *only* consumer.

**Rule: before scaling, stash the log-normalized matrix.**

```python
adata.layers["lognorm"] = adata.X.copy()   # BEFORE sc.pp.scale
sc.pp.scale(adata, max_value=10)
sc.tl.pca(adata, n_comps=50)
```

Then any later step that needs log-normalized values reads `layer="lognorm"` instead of the
scaled `.X`. See the `de_ranking` skill.

---

## Step 6: State it before you use it

Every time you run a method that assumes an input state, say which state you believe the
matrix is in and why:

```python
print(f"Running <method> which expects <state>; matrix is <state> "
      f"(negatives={has_neg}, integers={is_int}).")
```

If those two do not match, stop and fix the input first.
