# Transform -- whole cell to nucleus
applies_when: the observations are nuclei (single-nucleus RNA, single-nucleus multiome, any snRNA-based reference) rather than whole cells.

## What changes

- **Nuclear RNA is a different pool.** It is enriched for unspliced, intron-containing
  transcripts and for nuclear-retained RNAs (`MALAT1`, `NEAT1`, `XIST`), which dominate
  the top of any mean-expression ranking; cytoplasmic mRNAs are depleted, so many
  secretory and immune markers read lower than in cells.
- **Mitochondrial transcripts are nearly absent** from an intact nucleus; their presence
  marks cytoplasmic contamination, not cell stress.
- **Counts per nucleus are lower** than per cell, and ambient RNA is cytoplasmic in
  origin (mitochondrial and ribosomal reads in every droplet).
- **Cell-type proportions differ**: nuclei capture fragile or large cells (neurons,
  adipocytes, cardiomyocytes) that dissociation loses, and lose some others.
- **Introns must have been counted.** A matrix built without intronic reads has lost
  around half the signal; check the pipeline that made it.

## Rules that carry over unchanged

- Normalisation and log1p; highly variable feature selection; PCA; neighbour graph;
  Leiden; doublet detection (clumped nuclei are real doublets).
- Differential expression with replicate-level pseudobulk.
- Batch correction across samples.

## Rules that change, and how

- **Invert the mitochondrial rule.** Set a LOW mitochondrial-fraction cap (a few percent);
  a high-mito nucleus is a contaminated droplet, not a stressed cell. Never copy a
  whole-cell 20% threshold.
- **Lower the minimum genes and counts** thresholds; set them from the distribution.
- **Choose nuclear-abundant markers.** Prefer transcription factors and long genes over
  cytoplasmic effector genes when annotating; a marker list written for cells will
  under-call some types.
- **Reference-based annotation transfers imperfectly** from whole-cell references;
  expect a systematic shift and say so.
- **Ambient removal** is worth considering before clustering when the mitochondrial or
  ribosomal background is high.

## Rules that are new

- Report the intronic fraction if spliced/unspliced layers or an `intronic` column exist;
  RNA velocity is possible on the spliced/unspliced split.
- Report `MALAT1` fraction per nucleus; extreme values mark empty nuclei or debris.
- Check whether the counting pipeline included introns (metadata, or the intronic
  fraction itself); if it did not, state it as a limitation.

## Checks to add

- Mitochondrial fraction distribution (expect near zero; a wide tail is contamination).
- Top genes by mean (nuclear-retained RNAs should top the list; if not, ask why).
- Presence of spliced/unspliced layers.
- Counts and genes per nucleus, per sample.
