# CHANGELOG

<!-- version list -->

## v0.4.0 (2026-08-23)

### Bug Fixes

- Replace silent failures and leaking exception types with domain errors
  ([`6474b41`](https://github.com/BuckanovNikita/cveta2/commit/6474b41ae717e4f20736e6c02cd8c27c40d50bee))

- **client**: Stop a throttled size read from re-uploading task data
  ([`251c218`](https://github.com/BuckanovNikita/cveta2/commit/251c2181f8c963764047a6b5877f8607d4bee3e6))

- **commands**: Qualify echoed -p with the session organization
  ([`b0f9cc3`](https://github.com/BuckanovNikita/cveta2/commit/b0f9cc3397aa8196a7576ba337bc0d8d9761392d))

- **s3-sync**: Describe the projects it actually covers
  ([`22b47bd`](https://github.com/BuckanovNikita/cveta2/commit/22b47bdd43858b1f061c5e11e04176617339f89f))

- **scripts**: Put scripts/ under ruff and mypy, and prune dead suppressions
  ([`cdfe309`](https://github.com/BuckanovNikita/cveta2/commit/cdfe30938f2e98c4759e17780fd708384a483d33))

### Documentation

- Split the README reference into docs/ and correct what had drifted
  ([`f200948`](https://github.com/BuckanovNikita/cveta2/commit/f200948bbdcf4e0c6187e59a557626b5ae204fad))

### Features

- **upload**: Honour cache.images_root when resolving local images
  ([`340a027`](https://github.com/BuckanovNikita/cveta2/commit/340a0272a631330aaa50342e4dfeb0415fe4dbe0))

### Refactoring

- Collapse repeated parameter tuples and share duplicated orchestration
  ([`d52426d`](https://github.com/BuckanovNikita/cveta2/commit/d52426d3acb7aefecbe58918a33c35ba8cfdddb0))

### Testing

- Check the docs against the code
  ([`151a410`](https://github.com/BuckanovNikita/cveta2/commit/151a4103fe20155c2c2554f6ab05be8f13487876))

- Cover cveta2 ignore, make three tests able to fail, and dedup fixtures
  ([`392c27e`](https://github.com/BuckanovNikita/cveta2/commit/392c27ef7be615e1eb14ba0b4fc1f0056c457dc2))

- Split test_convert.py along the three modules it covers
  ([`4b21412`](https://github.com/BuckanovNikita/cveta2/commit/4b2141234b67e764099dd4205347380a2dad5e6d))


## v0.3.0 (2026-08-21)

### Bug Fixes

- **convert**: Emit job_stage/job_state instead of the removed task_status
  ([`f25b0f3`](https://github.com/BuckanovNikita/cveta2/commit/f25b0f3cc6bd40ea344c50cf42a41026be4cd780))

- **integration**: Make the stack work against CVAT v2.59.1
  ([`26471ad`](https://github.com/BuckanovNikita/cveta2/commit/26471adf23e6a5704c9a09cf7f5214e5fdc93fdd))

### Features

- Replace task_status with per-job job_stage and job_state
  ([`f50c5b1`](https://github.com/BuckanovNikita/cveta2/commit/f50c5b1bb388d10b1ba1ce26b90b69bb732f4552))

### Testing

- **integration**: Pin CVAT's finished-task rule against a live server
  ([`e865648`](https://github.com/BuckanovNikita/cveta2/commit/e865648efbc9e55f600eee76f1013ab88ba91665))

### Breaking Changes

- The `task_status` column is gone from dataset.csv, obsolete.csv, in_progress.csv and deleted.csv,
  replaced by `job_stage` and `job_state`. `whats_new` requires the new columns, so a CSV fetched
  before this change must be refetched.


## v0.2.1 (2026-08-21)

### Performance Improvements

- **fetch**: Make a single-task fetch cost the task, not the project
  ([`2c76e08`](https://github.com/BuckanovNikita/cveta2/commit/2c76e0883442b865b9884e0136614188176feb5c))

### Testing

- **fetch**: Close the mutation gaps the single-task fast path opened
  ([`2cf7582`](https://github.com/BuckanovNikita/cveta2/commit/2cf7582e193889cfeb241505efa2025ea7fe504e))


## v0.2.0 (2026-08-16)

### Bug Fixes

- **upload**: Report a task with no attached data as empty, not as an error
  ([`1652ce2`](https://github.com/BuckanovNikita/cveta2/commit/1652ce25a114153f7afe6db8677ef85c01bf35ab))

### Features

- **doctor**: Repair shared-cache permissions with `doctor --cache`
  ([`df85689`](https://github.com/BuckanovNikita/cveta2/commit/df85689f81d07e13dee05f3427a83e91d8069611))

- **retry**: Retry 429 and 5xx, and never repeat an ambiguous write
  ([`bcc8932`](https://github.com/BuckanovNikita/cveta2/commit/bcc8932dd200ffe0c8eaf456a1e1373399edc592))

- **transfer**: Run S3 and CVAT work concurrently
  ([`5eee206`](https://github.com/BuckanovNikita/cveta2/commit/5eee2069c0cea6526ee3390bce71c6221acc9032))

- **upload**: Continue an interrupted upload with --resume
  ([`f58d818`](https://github.com/BuckanovNikita/cveta2/commit/f58d8184345522322aac1927054479b9a1842086))

### Testing

- **integration**: Prove concurrency and resume against a live CVAT
  ([`873822a`](https://github.com/BuckanovNikita/cveta2/commit/873822a09e73457b132ec7095e2036bb1a1cf5b2))


## v0.1.1 (2026-08-15)

### Bug Fixes

- **integration**: Resolve the compose directory with dirname
  ([`6ae6bfb`](https://github.com/BuckanovNikita/cveta2/commit/6ae6bfb143e424f89db713362cc91cf8182e3828))

- **packaging**: Drop the vendored CVAT submodule
  ([`cf3d6c0`](https://github.com/BuckanovNikita/cveta2/commit/cf3d6c0336ca07164a53e37547a040a36c1e4151))

### Documentation

- Fix the commit skill's layer map and name the mutation gate
  ([`f2a8b6b`](https://github.com/BuckanovNikita/cveta2/commit/f2a8b6b3e3d769f0fac2d7bbab77e5efdec6c990))


## v0.1.0 (2026-08-13)

- Initial Release
