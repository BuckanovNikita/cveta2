# CHANGELOG

<!-- version list -->

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
