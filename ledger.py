"""Object-aware provenance ledger (PLAN.md Phase 2b).

Reports what the agent's AnnData/MuData objects look like and what changed on the
last turn, appended to the `execute_python` result. This is the state-awareness a
CodeAct agent otherwise has to hold in its head across dozens of turns.

Two rules govern what goes in here:

**Report, never judge.** This module states facts. It never says a value is wrong,
because encoding a notion of "correct" would put grader criteria inside the agent
and turn the Phase-2 delta into leakage. Facts are safe; verdicts are not.

**Structure, dtype, and value DOMAIN — but never distribution statistics OF A MATRIX.**
The line is between *what kind of numbers are in here* (domain: dtype, sign,
integrality) and *how are they distributed* (statistics: mean, variance, row sums,
sparsity fraction). See the annotation-column carve-out below.

Domain is reported. It is the same question `dtype` already answers, merely finished:
`float32` alone cannot separate log-normalized data from z-scored data, because both
are `float32` of the same shape — so `sc.pp.scale()`, the single most consequential
in-place transition in a pipeline, would otherwise leave *no trace in a ledger whose
whole purpose is recording in-place modification*. `has_neg` + `is_int` + dtype
together determine which of {counts, log-normalized, scaled} an object is in, and
nothing else.

Statistics stay out, for the original reason: *choosing which statistic to display is
itself a judgement*. Per-cell sums on a CLR layer would smuggle in a bug detector
through statistic selection — that answers "is this **right**", which is the agent's
call, not the ledger's. Sign and integrality answer "what **is** this". The agent is
still the one who decides what a negative value means.

Structure records a great deal on its own — scanpy writes `uns['log1p']`, `uns['pca']`,
`uns['neighbors']`, so those keys appearing is the record that those steps ran. But
note `uns['log1p']` is *sticky*: it records that log1p ran at some point, not that `.X`
is log-normalized now. Domain is what disambiguates it.

Domain is read from a **subsample** (see `_DOMAIN_ROWS`) and labelled as such — a
500k-peak matrix cannot be fully scanned every turn.

**CARVE-OUT (2026-07-29): annotation columns get their distribution, matrices do not.**
For each `obs`/`var` column the ledger prints the whole column's distribution — a
category breakdown with percentages, or five-number-plus-mean/sd for a numeric one.

Why this is not the statistic-selection judgement the rule above forbids: for a matrix
there are many statistics one *could* pick and picking is the judgement. For an
annotation column there is one canonical summary and its identity is fixed by dtype —
categorical means the category table, numeric means quantiles. Nothing is selected, so
nothing is smuggled. It also remains a fact: it says what is in the column, never
whether that is right.

What it buys, measured on the 2026-07-28 sweeps, where every one of these failures had
written its call straight into `obs` and the ledger said only `category`/`bool`:
  * `leiden` at resolution 1.0 produced **837 categories** over 605k beads;
  * `cell_type` called 12.3% of an ovary section oocytes (~3x the truth);
  * `likely_doublet` was True for 14.2% of cells (~35x a random collision rate);
  * `granulosa_type` held 2240 cumulus cells in a sample whose true count is 0 — one
    turn after the agent itself wrote that they are not transcriptomically separable.
Each is visible at a glance in a category table and invisible in a dtype. The ledger
still does not say any of them is wrong; it prints the number and stops.
"""

# ── tunables ──────────────────────────────────────────────────────────────────
_MAX_LINES = 10                          # cap the per-turn diff; the rest is summarised
_RULE = "=" * 72

_DOMAIN_ROWS = 1000                      # rows sampled for the domain probe
_DOMAIN_VALS = 200_000                   # cap on sparse stored values inspected

_MAX_CATS = 12                           # categories listed in full before falling back
                                         # to a bare level count. 837 leiden clusters
                                         # must not print 837 lines; the count IS the
                                         # finding in that case.

# ── per-run state (reset by tools.configure) ──────────────────────────────────
_prev: dict[str, dict[str, str]] = {}   # var name -> {path -> descriptor}
_origin: dict[str, int] = {}            # path -> turn it was last set
_turn: int = 0
_legend_shown: bool = False             # the legend prints once per run

# Printed once, on the ledger's first emission. The [STATE] block has to be
# self-describing — that is precisely why Phase 2 ships no prompt fragment for it
# (see prompts.py:_FRAGMENTS). Facts only: it says what the notation means, not
# what any particular value implies.
_LEGEND = (
    "matrix descriptors read: <dtype> [sign,integrality], sampled from up to "
    f"{_DOMAIN_ROWS} rows (sparse: stored values).\n"
    "  neg/non-neg = whether any sampled value is negative;  int/frac = whether all "
    "sampled values are whole numbers.\n"
    "obs/var column descriptors read: <dtype> then the whole column's distribution — "
    f"a category table as percentages (bare level count above {_MAX_CATS} levels), or "
    "min/q1/med/q3/max plus mean and sd for a numeric column."
)


def reset() -> None:
    """Drop all per-run state. Called unconditionally by tools.configure()."""
    global _prev, _origin, _turn, _legend_shown
    _prev = {}
    _origin = {}
    _turn = 0
    _legend_shown = False


# ── duck-typed detection (no anndata/mudata import: keeps `ledger off` free) ──
#
# CLASSES ARE EXCLUDED, and that is load-bearing. `hasattr` is satisfied by the class
# just as well as by an instance — AnnData.obs/.var/.layers/.obsm are all descriptors
# present on the type — so `from pydeseq2.dds import DeseqDataSet` (or a bare
# `from anndata import AnnData`) puts an object in the REPL namespace that duck-types
# as data. Fingerprinting it then fails on `list(cls.layers)` with
# "'AlignedMappingProperty' object is not iterable", once per turn for the rest of the
# run. Observed 15 times in a single da-17-3 run on 2026-07-26, immediately after the
# differential-expression skill was rewritten to steer toward pydeseq2 — which made the
# import, and so the failure, routine rather than rare.

def _is_instance_like(o) -> bool:
    """Reject classes/types: only real objects carry data."""
    return not isinstance(o, type)


def _is_mudata(o) -> bool:
    return (_is_instance_like(o)
            and hasattr(o, "mod") and hasattr(o, "obs") and hasattr(o, "update"))


def _is_anndata(o) -> bool:
    return (_is_instance_like(o)
            and hasattr(o, "obs") and hasattr(o, "var") and hasattr(o, "layers")
            and hasattr(o, "obsm") and not hasattr(o, "mod"))


# ── descriptors ───────────────────────────────────────────────────────────────

def _domain(X) -> str:
    """Value-domain facts for a matrix: sign and integrality. Sampled.

    NOT a statistic: no mean, no variance, no row sums. Only "what kind of numbers
    are these", which is what dtype starts and cannot finish (log-normalized and
    z-scored data are both float32).

    Sparse matrices are probed through `.data` — the stored values — because the
    implicit zeros carry no sign or fractional information. A negative value is
    therefore still found if one is stored.

    Never raises: a domain probe that fails must not take the ledger down with it.
    """
    try:
        import numpy as np

        if hasattr(X, "nnz"):                       # sparse: stored values only
            data = X.data
            vals = np.asarray(data[:_DOMAIN_VALS] if data.shape[0] > _DOMAIN_VALS else data)
        else:
            vals = np.asarray(X[:_DOMAIN_ROWS]).ravel()

        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            return ""

        has_neg = bool((vals < 0).any())
        is_int = bool(np.all(vals == np.rint(vals)))
        return f"[{'neg' if has_neg else 'non-neg'},{'int' if is_int else 'frac'}]"
    except Exception:
        return ""


def _mat_desc(X) -> str:
    if X is None:
        return "None"
    dt = getattr(X, "dtype", "?")
    # Storage format is reported alongside dtype because it is a STRUCTURAL fact of the same
    # kind — not a statistic, and not a judgement about whether the layout is appropriate.
    # It matters: slicing a COLUMN out of a csr matrix walks the whole structure, so per-column
    # work on a wide csr matrix is orders of magnitude slower than the same work on csc.
    fmt = getattr(X, "format", "")            # scipy: 'csr' / 'csc' / 'coo' / ...
    if hasattr(X, "nnz"):
        base = f"{dt} sparse[{fmt}]" if fmt else f"{dt} sparse"
    else:
        base = f"{dt}"
    dom = _domain(X)
    return f"{base} {dom}" if dom else base


def _arr_desc(a) -> str:
    shape = tuple(getattr(a, "shape", ()))
    dt = getattr(a, "dtype", "?")
    return f"{shape} {dt}"


def _col_desc(s) -> str:
    """dtype + the column's distribution. See the CARVE-OUT note in the module docstring.

    Categorical / boolean / low-cardinality object -> the category table as percentages.
    Numeric -> min / q1 / median / q3 / max plus mean and sd.

    Whole column, not a sample: an annotation column is one vector, cheap even at 600k
    rows, and a sampled percentage that disagreed with the agent's own `value_counts()`
    would be worse than no percentage at all.

    Never raises. A column the ledger cannot summarise falls back to bare dtype, which
    is exactly the pre-2026-07-29 behaviour.
    """
    dt = str(getattr(s, "dtype", "?"))
    try:
        import numpy as np
        import pandas as pd

        n = len(s)
        if n == 0:
            return dt

        if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
            v = pd.to_numeric(s, errors="coerce").to_numpy(dtype="float64", copy=False)
            v = v[np.isfinite(v)]
            if v.size == 0:
                return f"{dt} all-NaN"
            q = np.quantile(v, [0.0, 0.25, 0.5, 0.75, 1.0])
            nan = n - v.size
            out = ("%s min %.4g q1 %.4g med %.4g q3 %.4g max %.4g | mean %.4g sd %.4g"
                   % (dt, q[0], q[1], q[2], q[3], q[4], v.mean(), v.std()))
            return out + (f" | {nan} NaN" if nan else "")

        # categorical / bool / object -> category table
        vc = s.value_counts(dropna=False)
        k = len(vc)
        if k > _MAX_CATS:
            top = vc.iloc[0]
            return (f"{dt} {k} levels | largest '{vc.index[0]}' "
                    f"{100.0 * top / n:.1f}%")
        parts = [f"{lab}={100.0 * cnt / n:.1f}%" for lab, cnt in vc.items()]
        return f"{dt} {k} levels | " + " ".join(parts)
    except Exception:
        return dt


def _ann_paths(ad, prefix: str) -> dict[str, str]:
    """Flatten one AnnData to {path -> descriptor}. Structure + dtype only."""
    out: dict[str, str] = {prefix: f"{ad.n_obs} x {ad.n_vars}"}
    out[f"{prefix}.X"] = _mat_desc(ad.X)
    for k in list(ad.layers):
        out[f"{prefix}.layers['{k}']"] = _mat_desc(ad.layers[k])
    for k in list(ad.obsm):
        out[f"{prefix}.obsm['{k}']"] = _arr_desc(ad.obsm[k])
    for k in list(getattr(ad, "obsp", {})):
        out[f"{prefix}.obsp['{k}']"] = _arr_desc(ad.obsp[k])
    for k in ad.obs.columns:
        out[f"{prefix}.obs['{k}']"] = _col_desc(ad.obs[k])
    for k in ad.var.columns:
        out[f"{prefix}.var['{k}']"] = _col_desc(ad.var[k])
    for k in list(ad.uns):
        out[f"{prefix}.uns['{k}']"] = type(ad.uns[k]).__name__
    return out


def _obj_paths(obj, name: str) -> dict[str, str]:
    """Flatten an AnnData or MuData (all modalities) to {path -> descriptor}."""
    if _is_mudata(obj):
        out: dict[str, str] = {name: f"MuData {obj.n_obs} obs, mods {list(obj.mod)}"}
        for m in list(obj.mod):
            out.update(_ann_paths(obj.mod[m], f"{name}.{m}"))
        for k in list(obj.obsm):
            out[f"{name}.obsm['{k}']"] = _arr_desc(obj.obsm[k])
        for k in obj.obs.columns:
            out[f"{name}.obs['{k}']"] = _col_desc(obj.obs[k])
        for k in list(obj.uns):
            out[f"{name}.uns['{k}']"] = type(obj.uns[k]).__name__
        return out
    return _ann_paths(obj, name)


# ── scanning ──────────────────────────────────────────────────────────────────

def _scan(ns: dict) -> tuple[dict[str, dict[str, str]], list[str]]:
    """{var name -> paths} for every AnnData/MuData in the namespace, plus errors.

    MuData is scanned first and its modalities are marked covered, so
    `rna = mdata['rna']` is not reported twice under two names.
    """
    found: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    covered: set[int] = set()

    items = [(k, v) for k, v in ns.items() if not k.startswith("_")]

    for name, obj in items:
        if not _is_mudata(obj):
            continue
        try:
            found[name] = _obj_paths(obj, name)
            covered.add(id(obj))
            for m in list(obj.mod):
                covered.add(id(obj.mod[m]))
        except Exception as e:                      # surface, never swallow
            errors.append(f"{name}: {type(e).__name__}: {e}")

    for name, obj in items:
        if not _is_anndata(obj) or id(obj) in covered:
            continue
        try:
            found[name] = _obj_paths(obj, name)
            covered.add(id(obj))
        except Exception as e:
            errors.append(f"{name}: {type(e).__name__}: {e}")

    return found, errors


# ── rendering ─────────────────────────────────────────────────────────────────

def _first_seen_block(name: str, paths: dict[str, str]) -> list[str]:
    """A compact structure summary the first time an object appears.

    Listing thirty '+' lines when the agent loads its data is noise; one line per
    modality is the same information.
    """
    lines = [f"{name}  first seen — {paths[name]}"]
    mods: dict[str, list[str]] = {}
    for p in paths:
        parts = p[len(name) + 1:].split(".", 1)
        if len(parts) == 2 and "[" not in parts[0]:
            mods.setdefault(parts[0], []).append(p)

    def _slots(prefix: str) -> str:
        def keys(kind):
            pre = f"{prefix}.{kind}['"
            return [p[len(pre):-2] for p in paths if p.startswith(pre)]
        out = []
        if f"{prefix}.X" in paths:
            out.append(f"X {paths[f'{prefix}.X']}")
        for kind in ("layers", "obsm", "obs", "var", "uns"):
            k = keys(kind)
            if k:
                out.append(f"{kind}[{','.join(k)}]")
        return "  ".join(out)

    if mods:
        for m, _ in mods.items():
            lines.append(f"  {m:<6} {paths.get(f'{name}.{m}', '')}   {_slots(f'{name}.{m}')}")
    else:
        lines.append(f"  {_slots(name)}")
    return lines


def observe(ns: dict) -> str:
    """Fingerprint the namespace, diff against last turn, render the changes.

    Returns "" when nothing changed — most turns only print or plot, and those
    should cost the agent nothing.
    """
    global _prev, _turn, _legend_shown
    _turn += 1

    try:
        found, errors = _scan(ns)
    except Exception as e:                          # a broken ledger must be visible
        return f"{_RULE}\n[STATE] turn {_turn} — ledger failed: {type(e).__name__}: {e}\n{_RULE}"

    body: list[str] = []

    for name, paths in found.items():
        if name not in _prev:
            body += _first_seen_block(name, paths)
            for p in paths:
                _origin[p] = _turn
            continue

        old, changes = _prev[name], []
        for p, d in paths.items():
            if p not in old:
                changes.append(f"  + {p} {d}")
                _origin[p] = _turn
            elif old[p] != d:
                changes.append(f"  ~ {p} {d}  (was {old[p]})")
                _origin[p] = _turn
        for p in old:
            if p not in paths:
                changes.append(f"  - {p} removed")
                _origin.pop(p, None)

        if changes:
            body.append(f"{name}: {paths[name]}")
            body += changes[:_MAX_LINES]
            if len(changes) > _MAX_LINES:
                body.append(f"  … and {len(changes) - _MAX_LINES} more changes")

    for name in list(_prev):
        if name not in found:
            body.append(f"{name}: no longer in the session")

    if errors:
        body += [f"  ! could not read {e}" for e in errors]

    _prev = found

    if not body:
        return ""

    head = [_RULE, f"[STATE] turn {_turn}"]
    if not _legend_shown:
        head.append(_LEGEND)
        _legend_shown = True
    return "\n".join([*head, *body, _RULE])
