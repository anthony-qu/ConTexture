# Transform -- fresh or fresh-frozen tissue to formalin-fixed paraffin-embedded (FFPE) archival tissue
applies_when: the input was profiled from FFPE blocks (clinical archives, biobanks), by probe-based capture (Visium FFPE, CytAssist) or by random-primed / total-RNA capture on fixed sections (Patho-DBiT and similar).

## What changes

- **RNA is fragmented and chemically modified.** Fixation crosslinks and years of storage
  break RNA into short fragments; complexity per observation is lower and varies with
  block age and fixation time far more than with biology.
- **What is captured depends on the chemistry.** Probe-based kits hybridise to a designed
  probe set, so the feature space is the probe set (treat it as a large panel); total-RNA
  or random-primed capture reads whatever survived, so features can include introns,
  non-coding RNA, splice junctions and even variants, and there is no 3' bias.
- **Background is higher**: off-target hybridisation, diffusion between adjacent regions,
  and for total RNA a large ribosomal and mitochondrial fraction that reflects degradation
  and capture, not biology.
- **Blocks are batches.** Age, fixation protocol, storage and donor are confounded with
  each other and often with the condition of interest.

## Rules that carry over unchanged

- Count normalisation and log1p; clustering; marker-based annotation logic; the same
  differential-testing machinery with sample-level replication.
- Spatial rules from the spot or imaging transform, if the platform is spatial.

## Rules that change, and how

- **QC thresholds move down**, and the mitochondrial fraction changes meaning: with probe
  capture the mitochondrial genes may not be on the probe set at all; with total RNA a
  high fraction marks degradation, and the threshold should be set from the distribution,
  not copied from a fresh-tissue default.
- **Feature space.** For probe-based capture, ask whether a requested gene is on the
  probe set before reporting it absent. For total-RNA capture, SPLIT feature types
  (`var['feature_type']`: gene, intron, junction, ncRNA, ...) before normalising; a single
  matrix mixing them makes every normalisation wrong.
- **Batch correction by block is mandatory** when observations from several blocks are
  combined, and the batch-versus-biology check must include block age and fixation time
  as candidates.
- **Differential expression is confounded by RNA quality.** Include a quality covariate
  (fraction intronic, fraction ribosomal, counts per observation) or stratify; report how
  much of a contrast tracks quality.
- **Gene-length and GC effects are stronger**: long genes lose more fragments, so
  length-aware normalisation or a check of fold change against gene length is due before
  interpreting a list dominated by short or long genes.

## Rules that are new

- Compute RNA-quality metrics per observation and per block: counts, fraction intronic,
  fraction ribosomal, fraction mitochondrial, and if available DV200 or fragment length.
- Report the correlation of every QC metric with block and with condition BEFORE any
  contrast, because the answer decides whether the contrast can be made at all.
- For total-RNA capture, the extra readouts (splicing, non-coding RNA, variants) need
  their own primitive skills; do not analyse junction counts as if they were genes.
- Deduplication by UMI matters more (many fragments, low complexity); check for a
  duplication-rate column and report it.

## Checks to add

- Capture chemistry (probe set versus total RNA), read from the feature space and from
  any metadata; feature types present.
- Per-block: number of observations, median counts, quality metrics.
- Quality-metric correlation with block and with the condition of interest.
- Whether requested genes exist on the probe set, by name match in the probe vocabulary.
