# Hydra


An autonomous agent for spatial multiomics analysis. Takes as input a data file and a
task goal; it writes and runs Python until the goal is met, then leaves behind the
result object, the figures and a full transcript of what it did.


---

## What it is for

**In scope**

- Single-cell and spatial transcriptomics: QC, normalization, feature selection, clustering,
  cell-type annotation, differential expression, pathway enrichment.
- Spatial-specific analysis: spatially variable genes, spatial domains, neighbourhood and niche
  composition.
- **Co-assayed multi-omics** — RNA + ATAC, RNA + protein/ADT, and objects with more modalities.
  Joint embeddings, cross-modal integration, per-modality preparation.
- Exploratory questions where you don't yet know which method you want.

**Out of scope**

- Fetching or downloading data. Point it at files you already have.
- Raw-read processing: alignment, demultiplexing, peak calling. Start from a count matrix.
- Anything needing a tool that isn't installed — it cannot install packages (except in
  `--discovery` mode).
- Clinical or diagnostic use.

---

## Setup

Requires [`uv`](https://docs.astral.sh/uv/) and Python ≥ 3.10.

```bash
cd omics-agent
uv sync
```

Put an API key in `omics-agent/.env`:

```
ANTHROPIC_API_KEY=sk-...
```

Models are addressed with [LiteLLM](https://docs.litellm.ai/) strings, so any supported provider
works — set the matching key (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, …).

---

## Usage

```bash
uv run python agent.py <data> "<goal>" [options]
```

```bash
# cluster and annotate
uv run python agent.py pbmc.h5ad "cluster the cells and annotate cell types"

# spatial
uv run python agent.py visium.h5ad \
  "find spatially variable genes and identify spatial domains" \
  --output-dir results/visium

# co-assayed RNA + ATAC
uv run python agent.py brain.h5mu \
  "build a joint embedding and identify spatial domains from both modalities"
```

Write the goal the way you would brief a colleague. Name the deliverables you want — "save the
result with cluster labels in `obs['domain']`" — and it will aim at them.

---

## Input

| | |
|---|---|
| **Formats** | `.h5ad` (AnnData) or `.h5mu` (MuData) |
| **Content** | A count or expression matrix, with whatever `obs`/`var`/`obsm` it carries. Spatial coordinates are read from `obsm['spatial']` by convention |
| **Modalities** | One or many. [xxx] inspects the object and adapts — see *Routing* below |

The path is handed to the agent as text and it reads the file itself, so a **directory** of files
also works: it will list the contents and decide what to load. Nothing validates the path first,
so a typo surfaces as a failed first turn rather than an error up front.

> **Work on a copy.** [xxx] runs generated Python in the same process with no sandbox, and
> nothing write-protects your input. An analysis that saves in place will overwrite it.

---

## Output

Everything lands in `--output-dir`, which defaults to `omics-agent/output` — next to the agent,
**not** your working directory. Pass `--output-dir` to keep runs separate.

| file | what |
|---|---|
| `<name>.h5ad` / `<name>.h5mu` | the analysed object, if you asked for one. Name it in the goal, or you get the agent's choice |
| `plots/` | figures the agent produced |
| `dialog_log.txt` | the full transcript — every code block, its output, and the object-state changes |

`dialog_log.txt` is the record worth keeping. It contains the exact code that produced the
result, so any step can be re-run or checked by hand.

---

## Options

| flag | default | what it does |
|---|---|---|
| `--output-dir DIR` | `omics-agent/output` | where results, plots and the transcript go |
| `--model STR` | `anthropic/claude-sonnet-4-6` | any LiteLLM model string |
| `--max-turns N` | `30` | turn budget for the whole run |
| `--topology MODE` | `adaptive` | `adaptive` \| `flat` \| `orchestrated` — see below |
| `--discovery` | off | find, read and install a published method before analysing |

### Routing

By default [xxx] inspects the data and routes itself:

- **one modality** → analyse inline, no delegation;
- **two or more** → an orchestrator prepares each modality, then reconvenes to integrate.

The decision is printed in the transcript as a `ROUTING:` line, so you can see which path it took
and why. `--topology flat` forces the single-agent path; `--topology orchestrated` always
dispatches per modality, which is wrong for single-modality input and is provided for comparison
only.

### Discovery mode

`--discovery` runs a scout before the analysis: it searches the literature and GitHub for a method
suited to your goal, reads the documentation, and installs its choice at a pinned commit. It ranks
candidates on whether the documentation says the method does the job and whether the project looks
maintained — never on predicted accuracy.

This runs the analysis in a throwaway conda environment, takes considerably longer, and is best
treated as an exploratory feature.

---

## How it works

**Pure CodeAct.** Two tools, no fixed pipeline:

- `execute_python` — runs code in a persistent session, so objects stay in memory between turns.
- `get_skill` — retrieves a methodology guide.

**Skills** are written guidance, not code. [xxx] chooses when to consult them, and they carry the
judgement calls that go wrong most often — which normalization a platform needs, what a fold change
means on spot-level data, when "no gene survives FDR" is the correct answer rather than a bug.

| | |
|---|---|
| **Preparation** | `preprocessing` · `cell_qc` · `feature_selection` · `matrix_state` · `batch_integration` |
| **Analysis** | `clustering_resolution` · `cell_typing` · `differential_expression` · `de_ranking` · `pathway_enrichment` |
| **Spatial & multi-omic** | `spatial_analysis` · `cross_modal_integration` · `mudata_conventions` · `atac` · `protein_adt` |

**Object-state tracking.** After each step, [xxx] is told what changed about the objects in memory
— shape, dtype, whether values are still integers, which annotations appeared. This reports facts
only; it never says whether a result is right. That distinction is deliberate: the agent has to
reach its own conclusions.

---

## Notes and limits

- **One run, one process.** Runs are independent; nothing carries over.
- **Cost scales with turns.** A short goal on a small object is a few turns; an open-ended one on a
  large multi-modal object can use the full budget. Raise `--max-turns` for genuinely large work.
- **It can be wrong.** Read `dialog_log.txt` before trusting a result — the code is all there.
- **Not production-hardened.** Local use, plain-text credentials in `.env`, no sandboxing.
