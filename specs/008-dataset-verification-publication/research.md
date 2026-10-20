# Research and inspected decisions

- Decision: Port ed-killer v0.6.0 (tag commit 8448478bdd982b8b1b7e628e38fe40cd7278aac7)
  into one package. Its checkout HEAD 051eb39325cd6d2aacc8ed5089e30f174e5599b7 adds
  release evidence. Rationale: consolidation requested; dependency/workspace would
  retain two public lifecycles. Source remains unchanged.
- Decision: Separate pure validation from filesystem/image facts. Upstream
  validation.py imports media/os and upload validation directly opens PIL files;
  direct copying would violate existing cveta2 import/effect contracts.
- Decision: Explicit preparation and later publication replace upstream combined
  upload interaction. Copy four CSVs, bind payload/source hashes, rerun validation,
  refuse new parents and publish stable bytes. Reference-only evidence and implicit
  cleanup were rejected in clarification.
- Decision: Support bucket-relative S3 keys and absolute S3 URIs. cveta2's current
  dataset contract uses keys whereas upstream upload expects URIs. Resolve only
  against a unique approved bucket, never infer local/S3 mirror relationships.
- Decision: Retain optional ClearML, add Pandera base dependency using upstream
  compatible ranges. Existing pandas/Pillow/Pydantic/YAML dependencies cover the
  remainder; Python 3.12 and 3.13 stay supported.
- Decision: Replace obsolete publication tests with explicit publication coverage;
  retain fetch/CVAT upload regressions. Upstream mock evidence does not establish
  live publication, so tagged integration acceptance is required here.
