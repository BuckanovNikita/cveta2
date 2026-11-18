# Issue template

This file is the body of every cveta2 issue. A Linear template for cveta2 issues, if one
exists, must match it; where they differ, this file wins. Select the Verification lines
with [check selection](../development.md#check-selection):

| Change | Selected checks |
| --- | --- |
| Any commit | Commit hook: staging guard, verify (static checks + affected unit tests), Conventional Commit message |
| PR whose commits bump the version (feat, fix, perf, breaking) | acceptance on the clean committed tip |
| Non-bumping change to cveta2/adapters/{cvat,s3,clearml}, fetch/upload/managed orchestration, tests/integration/, its Kubernetes manifests, or dependencies | integration (preflight + live tests) |
| Changed functions under cveta2/ | Mutation report (mutation -- --base main) |
| pyproject.toml build settings or sdist contents, or adding, removing or renaming a file the sdist ships (README.md, CHANGELOG.md, GLOSSARY.md) | build |
| Property tests or Hypothesis settings | properties |
| Inputs that testmon selection cannot represent | test-full |
| Behavior, interface, dependency, security or operational-policy change | Fresh independent review after integrated verification |
| Documentation and instructions only | Commit hook only |

````markdown
## Outcome

## Scope
In:
Out:

## Compatibility

## Acceptance criteria
- [ ]

## Verification
Base: <merge-base SHA with main>  Tip: <tip SHA>

Delete the lines that do not apply. After each kept line write one status when it has
run: passed, failed, deferred, waived or error. Tick a box only for passed or waived. A
deferred required check blocks acceptance, merge readiness and release until it passes
or the user waives it.
Each stage below runs as `uv run --locked task --exit-code <stage>`.

### Commit gates
- [ ] Staging guard (commit hook)
- [ ] Development verification (`verify`: `check` and affected unit tests)
- [ ] Commit messages (Conventional Commits hook)

### Offline checks
- [ ] Full unit suite (`test-full`)
- [ ] Randomized properties (`properties`)
- [ ] Packaging (`build`)
- [ ] Mutation report (`mutation -- --base main`)

### Live checks
- [ ] Infrastructure preflight (`infra-check`)
- [ ] Live tests (`integration`)
- [ ] Acceptance on the clean committed tip (`acceptance`)

### Review and delivery
- [ ] Feature file and Russian guide updated
- [ ] Documentation consistency review
- [ ] Fresh independent review after integrated verification
- [ ] Release workflow result after merge

## Evidence
Commands, source and environment identities, exclusions, reuse reasons, limitations, links.
````
