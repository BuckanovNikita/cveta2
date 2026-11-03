# HTTPS docker.internal stands verification — 2026-11-03

## Process

The implementation (13 modified tracked files plus `tests/integration/stand_tls.py` and `tests/test_stand_tls.py`) preceded the Spec Kit artifacts in this change. The launching agent reported it as implemented, reviewed and tested. In the artifact pass, the feature directory was created with `.specify/scripts/bash/create-new-feature.sh --short-name docker-internal-stands`; later helpers selected it with `SPECIFY_FEATURE_DIRECTORY=specs/005-docker-internal-stands`, never with the branch name. The pass also added `tests/test_integration_tool_boundaries.py` (T009). It was written before the architecture record was validated with `--phase plan`.

## Local checks (worktree `feat/docker-internal-names`, base `main` a4fe54c)

Results before T009 was added:

- `env -u CVAT_INTEGRATION_HOST uv run pytest -q -m "not integration" -p no:cacheprovider`: 2792 passed in 7.59 s.
- Focused suite, 7 files (`tests/test_stand_tls.py tests/test_cvat_stand.py tests/test_seed_cvat.py tests/test_integration_env.py tests/test_clearml_run.py tests/test_architecture.py tests/test_docs.py`): 184 passed.

Results after T009 and the feature artifacts:

- `env -u CVAT_INTEGRATION_HOST uv run pytest -q -m "not integration" -p no:cacheprovider`: 2800 passed in 6.09 s. Integration tests were not collected because `CVAT_INTEGRATION_HOST` was unset.
- `uv run pytest tests/test_stand_tls.py tests/test_cvat_stand.py tests/test_seed_cvat.py tests/test_integration_env.py tests/test_clearml_run.py`: 114 passed.
- `uv run pytest tests/test_docs.py tests/test_integration_tool_boundaries.py tests/test_architecture.py`: 78 passed. The docs tests include the feature Markdown in this directory.
- `uv run pytest tests/test_integration_tool_boundaries.py`: 8 passed. This includes 6 parametrized negative fixtures: helper imports of cveta2, cvat_sdk, urllib3 (function-local) and botocore are rejected, and runtime imports of tests and scripts (function-local) are rejected.
- `uv run ruff format --check .`: 457 files already formatted. `uv run ruff check .`: no issues.
- `uv run mypy .`: no issues (strict).
- `uv run lint-imports`: 10 contracts kept, 0 broken. `uv run python scripts/check_architecture.py`: exit 0. `uv run vulture`: exit 0.
- Architecture record: `validate_architecture.py --phase plan` exit 0. The `--phase acceptance` result is recorded in the review evidence.

The configured pre-commit hooks (uv lock, ruff, lint-imports, architecture, mypy, vulture, pytest with coverage, mutmut fast profile, uv build) run again at commit time. Their outcome is visible in the commit result; it is not recorded here in advance.

## Not run

- **Live integration tests (SC-004, T013).** No live tests were run, by instruction. The HTTPS path has not been exercised against the real stands in this change. The CVAT/MinIO/ClearML access Secrets switch to the HTTPS names today, so a live run is needed before relying on the pre-push gate. That run uses the `running-integration-tests` skill with one owned tag and exact-tag cleanup.
- The pre-push full mutation profile and the version-drift check were not run, because nothing was pushed.

## Inspected no-change documentation

- A `grep -rln 'k8s\.localhost'` over the repository, excluding `.venv`, `.git` and feature directories 001–004, matches only the intentional "old names" sentences in CONTRIBUTING.md and the running-integration-tests skill.
- `specs/baseline.md`, `docs/`, `README.md` and `.specify/memory/architecture.md` contain no stand URLs or integration tooling.
- Companion corp-skills `skills/cveta2` at local checkout HEAD `670b0be` contains no stand, integration or TLS guidance, so no change is required. The checkout has unrelated uncommitted clearml-yolo work, which was left untouched.

## Ownership

The main checkout `/mnt/wsl/data/nkt/cveta2` was not touched. `.specify/feature.json` is ignored and is not committed.

## Release-resumption clarification

The "Not run" and ownership sections above describe the original artifact pass.
T013 subsequently completed the live run with 38 passed and exact-tag cleanup;
see [integration evidence](integration-2026-11-03.md). The user has now authorized
integration and the final gated main push after fresh checks and independent review.
Current preparation and delivery outcomes are recorded separately in
[release evidence](release-2026-11-03.md); earlier observations are preserved.
