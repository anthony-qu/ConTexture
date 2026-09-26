# Transform -- whole transcriptome to a designed targeted panel
applies_when: the feature set was chosen by a designer -- a few dozen to a few thousand features -- rather than measured genome-wide: gene panels (Xenium, CosMx, MERFISH, targeted sequencing), antibody panels, probe sets, PCR panels.

## What changes

- **The feature set is a choice, not a census.** Every gene-level summary (total counts,
  fraction of a type's markers present, "highly expressed") now reflects the panel's
  composition as much as the biology.
- **Features are probes.** A gene may be present as an isoform-specific probe, a mutation
  probe measuring an allele, or under an alias; the panel also carries controls that are
  not biological features.
- **There is no genome-wide background.** Any statistic that compares to "all genes"
  (enrichment, over-representation, expected fraction of markers) has lost its
  denominator.
- **Depth per observation is small and sparsity per feature is low**, because the panel
  was designed to be informative.

## Rules that carry over unchanged

- Normalisation to a per-observation size factor and log1p (with a corrected target,
  below); PCA; neighbour graph; clustering; marker-based annotation logic; group tests.

## Rules that change, and how

- **Do not select highly variable features.** Use every non-control feature.
- **Normalisation target.** Use the median total count, not 1e4.
- **Scaling** over-weights features in a small panel; if `scale` is used, clip, and state it.
- **Annotation is bounded by the panel.** A type whose distinguishing markers are not on
  the panel is "not resolvable"; say which requested types are and are not, using the
  panel's own vocabulary.
- **Signature scoring** must restrict each signature to the features present, and report
  how many of the signature's genes survived; a signature with two of thirty genes present
  is not a signature.
- **Enrichment and over-representation** must use the panel as background, or be reported
  as not computable. Never test a panel-derived gene list against a genome-wide set.
- **QC** by counts, feature count and controls, not by mitochondrial fraction (usually not
  on the panel).

## Rules that are new

- Separate control features from measured features before anything else; keep the control
  rate per observation as a background estimate.
- Ask "is gene G measured" in the panel's vocabulary: exact name, aliases, isoform probes,
  mutation probes. `G in var_names` alone puts false absences into the record.
- Report the panel size and the fraction of any requested gene set that is on the panel,
  by name, before analysing it.

## Checks to add

- Number of features; number and names of controls; any isoform or mutation probes.
- For every gene the task names: present, and under which probe name.
- Counts per observation: median and range.
