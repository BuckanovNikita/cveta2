# Dataset preparation

Terms distinguish source evidence from reviewed training output.

## Language

**Standalone preparation**: Preparation of four supplied full-fetch CSVs with externally assigned splits for a separately reviewed publication.

**Managed preparation**: Preparation for a named shared dataset definition, combining captured sources and an optional external transformation with persistent split assignments.

**Source evidence**: Captured annotations and source identity before transformation, filtering or repair; it is distinct from the training rows selected for publication.

**Prepared bundle**: Local publication input binding source evidence, training payload, decisions and parent identity for review. Readiness means no unresolved publication blockers; it does not mean the user has reviewed or published it.

**Parent dataset**: The exact existing finalized, nonarchived dataset version from which a publication continues. A first publication has no parent.
