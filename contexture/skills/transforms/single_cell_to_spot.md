# Transform -- dissociated single cell to spot-based spatial
applies_when: moving any single-cell pipeline (RNA, ATAC, protein) to a capture-area platform where one observation is a spot or bin holding several cells -- Visium (55 um), Visium HD bins, Slide-seq beads, Stereo-seq bins, DBiT-seq pixels.

## What changes

- **The observation is a mixture, not a cell.** A 55 um Visium spot holds roughly 1-10
  cells of possibly different types. Every value is a weighted sum over that mixture.
  Nothing downstream is single-cell, however cell-like the matrix looks.
- **Coordinates are measurements.** `obsm['spatial']` is data, not a picture. Some
  questions (domains, gradients, neighbourhoods, spatially variable features) cannot be
  answered without it, and some structures do not exist in expression space at all.
- **Sections are separate coordinate frames.** Two sections never share a frame unless
  they were registered. A spatial graph built across sections connects spots that are
  centimetres apart.
- **Depth tracks cell density.** Total counts per spot rise with the number of cells under
  it, so a low-count spot may be sparse tissue rather than a failed spot.
- **A cluster is a domain.** Clustering spot profiles groups recurring tissue COMPOSITIONS
  (a germinal centre, a crypt base, a fibrotic scar), not cell types.

## Rules that carry over unchanged

- Library-size normalisation followed by log1p as the default for count matrices; the
  same matrix-state checks before any method; the same warning never to densify.
- Highly variable feature selection, PCA, the expression neighbour graph and Leiden as the
  route to an embedding and a partition. The partition is then read as domains.
- Batch correction across sections or donors, by the same integration rules, when
  sections are combined. Check biology-versus-batch the same way.
- Differential testing machinery (rank-sum, pseudobulk by section) is the same code; the
  interpretation is not (below).

## Rules that change, and how

- **Cell typing becomes domain annotation or deconvolution.** Assigning one cell type to a
  spot is wrong by construction. Either annotate DOMAINS by their enriched genes, or
  estimate per-spot cell-type PROPORTIONS with a reference (see the reference-based
  annotation skill). Say which of the two the task asks for.
- **Marker genes become domain-enriched genes.** A gene enriched in a domain marks the
  mixture, not a cell; several cell types' markers appear together and that is expected.
- **Group contrasts are compositional.** Comparing two spot groups compares two mixtures
  whose composition differs by a fraction, so fold changes are compressed toward 1 BY
  CONSTRUCTION. Rank by a test statistic, not by raw log2 fold change; check the fraction
  of spots expressing on each side; and treat "no gene survives FDR" as an expected
  outcome, not as evidence of no biology.
- **QC thresholds move.** Minimum counts per observation are far higher than per cell
  (thousands, not hundreds), mitochondrial fraction is much less informative, and the
  first filter is `in_tissue == 1`. Doublet detection is meaningless and must be skipped.
- **Rare populations cannot be sub-clustered** from spot profiles. If the task needs a
  rare cell type, it needs deconvolution or a single-cell reference, and the answer should
  say so.
- **Two neighbour graphs, kept apart.** The expression kNN graph drives clustering; the
  SPATIAL graph drives spatial statistics. Never use one for the other's job. Spatial
  smoothing of expression before clustering is optional and must be declared.

## Rules that are new

- Build the spatial graph PER SECTION (`sq.gr.spatial_neighbors`, `coord_type="grid"` for
  Visium's hexagonal array, `"generic"` otherwise), then concatenate results.
- Spatially variable features are a property of a FEATURE, scored by spatial
  autocorrelation (Moran's I) on the spatial graph. This is not the same as highly
  variable, and the two lists differ.
- Neighbourhood or niche composition: for each spot, the domain (or proportion) profile of
  its spatial neighbours.
- A domain partition can be checked for spatial coherence: a real domain is contiguous.
  Compare the observed fraction of same-label spatial neighbours to that of a permutation
  of the same labels; a single cluster trivially scores 1, so report the ratio.
- Plot every partition on the tissue coordinates and look at it; a partition that forms
  no structure on the tissue is a warning.

## Checks to add

- `obsm['spatial']` present in every object and every modality; extent and units per section.
- Number of sections, and whether their coordinates overlap (a shared frame is a mistake
  unless registered).
- `in_tissue` present and applied; spots per section before and after.
- Counts per spot: median and range, per section.
- After clustering: spatial coherence of the labels, and a tissue plot per section.
