# Documentation verification — 2026-10-20

## Scope and source state

cveta2 branch: `feat/dataset-verification-publication`, inspected base HEAD
`39bc958d20cc21a85beeaf238e411d815c66e678`. Documentation was checked against the
working feature implementation, not claimed as released behavior.

Changed cveta2 paths:

- `README.md`
- `docs/cli.md`
- `docs/configuration.md`
- `docs/images-and-cache.md`
- `docs/python-api.md`
- `.specify/memory/architecture.md`
- `specs/001-project-documentation/contracts/dataset-format.md`
- `tests/test_docs.py`

The added documentation guard rejects retired automatic-publication commands and
flags in executable shell examples while allowing migration prose to name them.
Existing signature, surface, configuration, environment and link checks remain.
Guides describe report-only validation, explicit cleanup, external split assignment,
reviewed preparation, local source copies/checksum, full upload revalidation,
exact-three-file publication, failure recovery and removed automatic controls.

Canonical portable source: `BuckanovNikita/corp-skills`, inspected HEAD
`740906249912671bb17f52edabacca247da27337`, collection version `0.2.9`.
Changed package paths:

- `skills/cveta2/SKILL.md`
- `skills/cveta2/references/usage.md`
- `skills/cveta2/references/evaluation.md`

New portable examples are explicitly labeled unreleased pending the tool release.
No companion commit, tag, push or installation was performed by this worker.
The parent owns companion release reconciliation and fresh behavioral evaluation.

Preserved unrelated source changes initially observed:
`skills/clearml-yolo/references/{usage,evaluation}.md` and untracked
`docs/plans/stable-clearml-cache/`. A later status check also showed untracked
`docs/plans/2026-10-20-opencode-model-routing/`; it was not edited. No corp-skills
AGENTS.md exists; its MAINTENANCE.md and RELEASE.md were inspected. Applied
skill-builder and skill-creator authoring/validation guidance.

## Executed checks

From the cveta2 feature checkout:

```bash
uv run pytest tests/test_docs.py -q --no-cov
uv run ruff check tests/test_docs.py
uv run ruff format --check tests/test_docs.py
git diff --check
uv run cveta2 verify --help
uv run cveta2 upload-dataset --help
uv run python -c 'import inspect,cveta2; print(inspect.signature(cveta2.verify)); print(inspect.signature(cveta2.prepare_dataset)); print(inspect.signature(cveta2.upload_dataset))'
uv run python "$skill_creator_root/scripts/quick_validate.py" "$corp_skills_root/skills/cveta2"
```

Results: documentation suite **230 passed** before this evidence file; the final
rerun including its parameterized document checks reported **232 passed**. Ruff
check and final Ruff format check passed. The initial
format check requested wrapping one added test line; `uv run ruff format
tests/test_docs.py` applied that formatting and Ruff check passed afterward.
Whitespace check passed. Both command helps and all three signatures matched the
documented interfaces. Skill quick validation reported `Skill is valid!`.
The validator command used variables resolved to the installed skill-creator
source and canonical corp-skills checkout; machine paths are intentionally omitted.

An additional executed `uv run python -` structural check used a duplicate-key
rejecting PyYAML SafeLoader, confirmed name/folder agreement and description
length, and resolved every packaged relative link and anchor within the cveta2
skill directory. It reported:
`Unique frontmatter, name/description and all packaged links/anchors pass.`

An isolated `uv run python -` example check used TemporaryDirectory and
`tests.verification.test_validation.row` to write a synthetic valid
clearml-yolo CSV, then executed:

```python
report = cveta2.verify(source, profile="clearml-yolo", output_dir=base / "api-report")
completed = subprocess.run(
    [
        "cveta2",
        "verify",
        str(source),
        "--profile",
        "clearml-yolo",
        "--output-dir",
        str(base / "cli-report"),
    ],
    capture_output=True,
    text=True,
    check=False,
)
cleaned = cveta2.verify(
    source,
    profile="clearml-yolo",
    output_dir=base / "cleaned",
    clean=True,
)
```

Assertions passed: report/cleaned results valid; CLI exit zero; report.json and
broken.csv exist; report-only writes no clean.csv; explicit cleanup writes
clean.csv; original CSV bytes unchanged throughout. TemporaryDirectory cleaned
all example outputs. No remote publication or target-model run was performed.

From the corp-skills collection root:

```bash
DISABLE_TELEMETRY=1 npx --yes skills@1.7.1 add . --list
npx --yes markdownlint-cli2@0.23.3 '*.md' 'skills/**/*.md' 'verification/**/*.md' 'docs/**/*.md'
git diff --check
```

Results: discovery found all four expected skills, including cveta2 with its
updated description; no skill installation occurred. Markdown lint examined
42 files and reported zero issues. Whitespace check passed.

## Limits and remaining acceptance

The optional default Markdown lint command below failed with **354 issues**,
primarily line length and table formatting in the cveta2 guides/contracts. It
used default lint settings, whereas these established files already contain
extensive long lines and compact table separators. No broad formatting rewrite
was made. This is not a passing check; required repository documentation tests
passed independently.

```bash
npx --yes markdownlint-cli2@0.23.3 README.md docs/cli.md docs/configuration.md docs/images-and-cache.md docs/python-api.md .specify/memory/architecture.md specs/001-project-documentation/contracts/dataset-format.md
```

Fresh skill routing/application evaluation and independent review remain parent
acceptance work. The added evaluation cases specify expected behavior; they do
not claim observed target-model passes. Bundle/publication examples were checked
against source and help; live remote verification belongs to the parent workflow.
Companion commit/version/tag and tool release must be recorded before claiming
released guidance. Reinstallation remains outside scope.
