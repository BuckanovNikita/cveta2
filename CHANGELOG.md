# CHANGELOG

<!-- version list -->

## v0.5.4 (2026-09-05)

### Bug Fixes

- Close the verified defects from the fetch, upload and convert audit
  ([`5eaf98f`](https://github.com/BuckanovNikita/cveta2/commit/5eaf98f29ec3c365e198be55cc3262613901546b))

### Documentation

- **skills**: Clarify CVAT task workflows
  ([`512e0e0`](https://github.com/BuckanovNikita/cveta2/commit/512e0e03063af3132fc8047f920c48eadf544cdd))


## v0.5.3 (2026-09-04)

### Bug Fixes

- Isolate network settings between parallel callers
  ([`547756b`](https://github.com/BuckanovNikita/cveta2/commit/547756b31a61adccee227a265b1500e9f408c234))

### Testing

- Align integration cache freshness contract
  ([`ca2f0a8`](https://github.com/BuckanovNikita/cveta2/commit/ca2f0a8ad72934130beabbba1409b130f030d449))

- Run integration tests against the cluster CVAT stand
  ([`13371d2`](https://github.com/BuckanovNikita/cveta2/commit/13371d2993e5ef808032f93ca38537d3e315e9f3))

- Stop unit runs from spending the stand's anonymous request budget
  ([`6e34697`](https://github.com/BuckanovNikita/cveta2/commit/6e34697bac4e81a3a57744ec1e934599c14600ad))

- Strengthen path conversion mutation coverage
  ([`40c0038`](https://github.com/BuckanovNikita/cveta2/commit/40c00381a0ecef40674d0b2c997ec4b1815eb632))


## v0.5.2 (2026-09-04)

### Bug Fixes

- Harden dataset and configuration workflows
  ([`62cad9d`](https://github.com/BuckanovNikita/cveta2/commit/62cad9dd7c385ab1380b0672f4a77f2c83c2538e))


## v0.5.1 (2026-09-02)

### Bug Fixes

- Close the remaining verified defects in resolution, config paths and I/O
  ([`33c55bb`](https://github.com/BuckanovNikita/cveta2/commit/33c55bbca2630e301eb7b5aa0a7946c5068120a7))

- Correct ten verified defects found by the project-wide review
  ([`c63853f`](https://github.com/BuckanovNikita/cveta2/commit/c63853f0a61abbbd29aa25c7bf6ef283bed08b50))

- **scripts**: Let the integration stack honour INTEGRATION_USER and port env overrides
  ([`f54e21d`](https://github.com/BuckanovNikita/cveta2/commit/f54e21d6b8cda5b8c74182313b2e996fe5965624))

### Documentation

- Describe the upload refusal of unreachable images and list-form names
  ([`f501542`](https://github.com/BuckanovNikita/cveta2/commit/f50154240efb904ba04464945293e89995960be6))

- Fix the miscounted out-of-scope list in the mutation-testing skill
  ([`341131b`](https://github.com/BuckanovNikita/cveta2/commit/341131bbf144acf0a1e97168f32eeabf8e137018))

- Remove restated prose and collapse cross-document duplication
  ([`a2cf8ca`](https://github.com/BuckanovNikita/cveta2/commit/a2cf8ca749ae7151b0ddac8a0ad8730f7395097e))

### Refactoring

- Remove duplicated logic and needless indirection found by the review
  ([`a63f8bc`](https://github.com/BuckanovNikita/cveta2/commit/a63f8bce4bbd145528c11636726c5a67177186ee))

### Testing

- Kill the two survivors the full mutation profile found
  ([`0e47759`](https://github.com/BuckanovNikita/cveta2/commit/0e4775993bdb1b6c6c255c19bcc7ffe443df0ad6))


## v0.5.0 (2026-08-28)

### Documentation

- Describe task_id ordering and the cache's status-only freshness
  ([`6742b71`](https://github.com/BuckanovNikita/cveta2/commit/6742b710a38b424d824ae6b075ea5337a8864baa))

### Features

- Order tasks by task_id instead of task_updated_date
  ([`8e3ba4f`](https://github.com/BuckanovNikita/cveta2/commit/8e3ba4fb48d1c12f01f82dfcf5d807062c16ae2d))

### Testing

- Close the sibling-CSV gaps and re-triage the mutation allowlist
  ([`c79916e`](https://github.com/BuckanovNikita/cveta2/commit/c79916ebf25439b8e90d91c045d85be1620f0ef5))

- **integration**: Expect Cveta2Error from drop_label_annotations
  ([`7acea36`](https://github.com/BuckanovNikita/cveta2/commit/7acea365bc4c002d4575f9d4af96da08bb95c729))

- **integration**: Pin the label-edit premise against a live CVAT
  ([`b2a6b57`](https://github.com/BuckanovNikita/cveta2/commit/b2a6b57db36b1bf29ae1af7ddeb346f21301a659))

### Breaking Changes

- `merge --by-time` is renamed to `--by-task` and now resolves conflicts by task_id rather than
  task_updated_date; the Python API's `cveta2.merge(by_time=)` becomes `by_task=`.
  `WhatsNewResult.cutoff` changes from an ISO date string to an int task id and `updated_task_ids`
  is gone, as is the client's `list_tasks_completed_after` (replaced by `list_new_completed_tasks`).


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
