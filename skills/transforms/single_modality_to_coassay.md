# Transform -- one modality to several measured on the same observations
applies_when: two or more measurement types were taken from the SAME cells, nuclei or spots and share one observation axis -- co-assayed multiome (RNA+ATAC), CITE-seq style RNA+protein, spatial RNA+protein, RNA+histone, or any same-spot co-assay.

## What changes

- **One observation, several matrices.** The observations are shared and aligned; the
  features are not. Each modality has its own distribution, noise model, sparsity and
  correct preprocessing, and applying one modality's recipe to another is the commonest
  error on this kind of data.
- **New questions exist only here**: do the modalities agree; which one defines groups;
  can a joint embedding be built; does a feature in one modality predict its counterpart
  in the other (a gene and its protein, a peak and its gene).
- **The container is MuData** (`.h5mu`), with per-modality `obs`/`var`/`obsm` and a global
  `obs` that pulls per-modality columns up with a `<mod>:` prefix.
- **Feature names can collide across modalities** (a protein name is often also a gene
  symbol), so the global `var_names` are not unique.

## Rules that carry over unchanged

- Inside each modality, that modality's own primitive rules apply exactly as written:
  preprocess RNA as RNA, ATAC as ATAC (TF-IDF, not library normalisation), protein tag
  counts as protein (CLR, not log1p of CP10K). Do this per modality BEFORE anything joint.
- Matrix-state checks, per modality, before any method.
- Batch correction, per modality, by the same rules.

## Rules that change, and how

- **Grouping.** Decide, and state, one of: (a) one modality defines the groups and the
  other is read within them; (b) a joint embedding (weighted nearest neighbours, MOFA,
  concatenated per-modality components after scaling) defines them. The task text usually
  decides; if it is silent, the modality with the richer feature space usually leads and
  the other validates.
- **QC.** An observation must pass EVERY modality's QC to be kept; filter once on the
  intersection and subset all modalities together so they stay aligned.
- **Annotation.** May use both modalities; say which evidence supported each label.
- **Differential testing** is per modality, within groups defined once; never test a
  concatenated matrix.
- **Where results live.** Per-modality results (normalised layers, per-modality
  embeddings, per-modality clusters) go inside that modality; shared results (a joint
  embedding, the final labels) go at the top level AND are copied into every modality's
  `obs` if the task asks for them there. Save with `write_h5mu`, never one modality alone.

## Rules that are new

- Alignment check first: identical `obs_names` in identical order across modalities; if
  one modality has fewer observations, decide whether the task wants the intersection.
- Slice per modality (`md['rna'][:, gene]`), never on the global object by name.
- Cross-modal agreement: adjusted Rand index between per-modality clusterings; per-cell
  correlation between matched features (gene versus its protein; gene versus its promoter
  accessibility). Report it as a fact, then interpret.
- Joint embedding, if built: report what each modality contributed (weights or variance),
  and check that the joint partition is at least as spatially or biologically coherent as
  the leading modality's own.
- One modality can validate the other: a group called on modality A should show the
  expected signal on modality B; where it does not, say so rather than smoothing over it.

## Checks to add

- `md.mod` keys; shape per modality; `obs_names` identity and order across modalities.
- State of `X` per modality, separately.
- Feature-name collisions between modalities.
- Which modality is designated as leading, and why, printed before clustering.
