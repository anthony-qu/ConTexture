# Transform -- dissociated single cell to imaging-based single-cell spatial
applies_when: moving a single-cell pipeline to a platform where each observation is a SEGMENTED cell with coordinates and a targeted probe panel -- Xenium, MERFISH, CosMx, seqFISH, ISS.

## What changes

- **Features are probes on a designed panel**, a few hundred to a few thousand, not the
  transcriptome. A panel names PROBES, not genes: one gene may ship as two isoform probes,
  another as a mutation-specific probe that measures an allele rather than expression, and
  the panel carries control codewords (negative controls, blanks, unassigned) that are not
  genes at all.
- **Counts per cell are small** -- tens to a few hundred transcripts -- so the matrix is
  much less sparse per feature but much shallower per cell than droplet data.
- **The observation is a segmentation.** Cell boundaries are estimated, so a cell can be
  partial, nuclear-only, or contain transcripts spilled over from a neighbour; segmentation
  method can vary cell by cell in one dataset and changes cell area several-fold.
- **Coordinates are in physical units** (micrometres) and each section is its own frame.
- **Mitochondrial genes are usually absent** from the panel, so mitochondrial-fraction QC
  is not available.

## Rules that carry over unchanged

- Library-size normalisation and log1p; the matrix-state checks; never densify.
- PCA, expression neighbour graph, Leiden; marker-based annotation logic; group
  differential tests.
- Batch correction across sections or slides when combined.

## Rules that change, and how

- **No highly variable feature selection.** Use every panel feature (after removing
  controls); the dispersion model assumes a transcriptome and the panel was already
  selected to be informative.
- **Normalisation target.** Use the median total count per cell (or a fixed small target
  such as 100), not 1e4; a 10,000 target on 100-count cells inflates every value.
- **QC by counts, feature count and cell area**, not mitochondrial fraction. Remove cells
  with very few transcripts and cells whose area is implausible for the segmentation
  method; record which segmentation method each cell came from if that column exists.
- **Annotation is bounded by the panel.** A cell type the panel cannot distinguish is
  "not resolvable", never forced. Say which requested types the panel can and cannot
  separate, in the panel's own probe vocabulary.
- **Enrichment against genome-wide gene sets is invalid** (the background is the panel).
  Use the panel as background, or report enrichment as not computable.
- **Ask "is this gene measured" in the panel's vocabulary**, never with a bare
  `gene in var_names`: check isoform and mutation probes and aliases.

## Rules that are new

- Remove control features from `X` before any normalisation; keep their counts as a
  per-cell background rate (negative-probe rate) and report it.
- Build the spatial graph per section in micrometres with a radius or k-nearest
  neighbours; neighbourhood composition is now cell-level and meaningful.
- Spillover check: a marker of type A appearing at low level in type B cells that are
  adjacent to A cells is segmentation leakage, not co-expression; look for it before
  interpreting double-positive cells.
- Cell area and segmentation method as covariates; a nuclear-size or area effect can be
  swamped by the segmentation method.

## Checks to add

- Feature types: how many genes, how many controls, any isoform or mutation probes.
- Counts and features per cell: median and range; negative-probe rate per cell.
- Coordinates present, units, extent per section; number of sections.
- Cell area distribution, and whether a segmentation-method column exists.
