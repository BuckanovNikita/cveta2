---
name: mutation-testing
description: |
  Use when working with the cveta2 mutation-testing gate: a failing mutmut hook (pre-commit fast profile or pre-push full profile),
  a surviving mutant to triage, editing [tool.mutmut].only_mutate or [tool.cveta2.mutation.equivalent], adding a module to the gated
  scope, or deciding whether a module is worth gating at all.
  Trigger on: "mutmut", "mutation testing", "mutation gate", "survivor", "surviving mutant", "only_mutate", "equivalent mutant",
  "allowlist", "mutation_test.sh", "pre-push hook failed", "mutation score".
---

# The cveta2 mutation gate

`./scripts/mutation_test.sh` runs mutmut over the modules in
`[tool.mutmut].only_mutate` and fails if any mutant survives unexplained.

**Two profiles**, defined in `[tool.cveta2.mutation.profiles]`:

```bash
./scripts/mutation_test.sh --profile fast   # pre-commit subset
./scripts/mutation_test.sh --profile full   # whole gated scope (pre-push)
./scripts/mutation_test.sh                  # whole scope, no filter
uv run pre-commit install                   # required once; installs the pre-push gate too
```

`full` is an **empty glob list** on purpose. mutmut honours a cached verdict
only when no positional mutant name is given, so writing it as `"*"` would
re-execute every mutant on every push. `fast` accepts that cost for its subset
in exchange for skipping the rest.

## Rules

**Scope is a ratchet.** A module joins `only_mutate` in the *same commit* that
drives it to zero unexplained survivors, so the hook is never red on `main`.
There is no "measured but ungated" tier: `mutmut results` walks every file in
`only_mutate` regardless of what the run filtered on, so a parked module with
survivors reddens the full profile immediately. Measure a candidate by
temporarily adding it and reverting before committing.

**Two-stage entry criterion.** `mutate_only_covered_lines` is off, so every
mutant on an *uncovered* line is an automatic survivor that says nothing about
assertion quality. Close line coverage first, then triage mutants. The real
disqualifier is mutmut's own `no tests` status (exit code 33), not the
`[tool.coverage.run] omit` list — that is a reporting setting mutmut never
consults.

**When the hook fails**, inspect with `uv run mutmut show <name>` or
`uv run mutmut browse`, then: strengthen a test (the default), or — only when
the mutation genuinely cannot change behaviour — add it to
`[tool.cveta2.mutation.equivalent]` with a reason. The gate also fails on a
*stale* allowlist entry: mutmut renumbers mutants whenever a function changes,
so a justification cannot silently drift onto a different mutant. Keep the
allowlist small; at scale every refactor of a mutated function forces
re-triage.

**Never reshape working code to satisfy the gate.** A progress-bar caption
hoisted into a module-level constant does remove the mutant — mutmut only
mutates code inside a top-level function — but it buys a green gate by adding
indirection that every later feature has to carry, and it hides the caption
from the call site that owns it. Presentation surfaces are excluded once, by
pattern, in `[tool.mutmut].do_not_mutate_patterns`; a new one goes there. This
rule is the reason `_TASK_BAR` and `_LABEL_SCAN_BAR` no longer exist.

Two anti-patterns, both of which produce brittle change-detector tests:

- Do not assert exact `yaml.safe_dump` / `json.dumps` output when the only
  reader parses it back — `safe_load` is blind to escaping, key order and flow
  style, so such a test breaks on any unrelated field addition.
- Do not write a test whose only purpose is pinning the wording of a message.
  If the mutant only reaches text a person reads, it belongs behind a
  `do_not_mutate_patterns` entry, not behind an assertion on prose.

Before triaging a survivor whose diff looks unkillable — or before judging
whether a module is worth gating — read `mutation-internals.md` in this
directory: what mutmut actually mutates, the config settings that fail
silently, and where the runtime goes.

## Current scope

Every module in `only_mutate` sits at zero *unexplained* survivors; everything
still escaping is justified in `[tool.cveta2.mutation.equivalent]`. A new
module joining `cveta2/` should come with its own `only_mutate` entry rather
than being added to a to-do list.

One module is deliberately outside that ratchet and is **not** "nothing left to
do": **`_client/sdk_adapter.py`**, the SDK boundary, and the one module where
line coverage itself is the blocker, so the two-stage entry criterion says
close coverage first. Most of it is only reachable against a live CVAT, which
is why the integration suite exists.

`services/fetch.py` was the other one and is now gated. Its survivors were an
assertion-quality gap, not a coverage one — zero `no tests` mutants — and they
clustered in three places worth knowing about, because they are the parts of
the pipeline that end-to-end CSV assertions structurally cannot see:

- **the cache-hit vs live-fetch accounting** in `_retrieve_task`. Its counters
  and elapsed-time fields feed one summary line, and every assertion available
  on a real clock ("roughly zero") leaves `+=` and `=` indistinguishable.
  `TestRetrieveTaskAccounting` scripts the `time` module instead, which makes
  each field exactly predictable.
- **the arguments `_fetch_core` forwards** to `download_images` and
  `populate_record_paths`. Dropping one changes *where* images land or whether
  they land at all — never how many rows the CSV has, so nothing that reads
  `dataset.csv` reacts.
- **the S3 half of the task cache.** `FakeCvatApi.get_project_cloud_storage`
  returns `None`, so every service-level fetch test ran local-only and the
  whole shared-cache path was reachable only from direct `S3CacheBackend` unit
  tests. `_FakeApiWithStorage` in `tests/test_task_cache.py` closes that.

The group before it was the one the rollout plan called conditional:
`_client_ops/{base,images}.py` and the three command-layer exceptions
(`commands/_helpers.py`, `commands/interactive/primitives.py`,
`commands/upload.py`). None of them had a single `no tests` mutant in
`_client_ops`; the survivors sat on code every scenario test already ran and
none asserted — nothing constructed a client without `api=` and entered it, so
the whole `client_factory` → `ExitStack` → SDK-client lifecycle was
integration-only.

## Permanently out of scope

Two distinct reasons, which imply different things about whether the exclusion
could ever be lifted:

- **Zero mutable surface** — nothing to gate, ever: `_client/{ports,dtos,mapping}.py`,
  `_client_ops/{shared,session}.py`, `exceptions.py`, `client.py`, `_retry.py`,
  `_clearml/*`. `session.py` is a decorated dataclass whose four guards are all
  `@property`, so it generates no mutants at all.
- **Mutants exist but are low-signal plumbing already pinned by existing
  tests** — admission costs runtime for no new signal: `fs_utils.py` (its whole
  contract is the module-level `_DIR_MODE`/`_FILE_MODE`) and
  `_client/context.py`.
- **The rest of `commands/`** — prompts, arg mapping and `sys.exit`. The three
  that *are* gated (`_helpers.py`, `interactive/primitives.py`, `upload.py`)
  were selected on message density: they carry 0, 1 and 2 logger calls
  respectively, against 18–20 for `doctor.py`, `setup.py` and `labels.py`.
  `commands/upload.py` additionally encodes a contract `ARCHITECTURE.md` states
  as a guarantee — `--labels all` loses to a literal dataset label named `all` —
  which is worth pinning precisely.
- **Adapters** — `cli.py` is a wall of `add_argument()` calls whose mutable content
  is help text and arguments that restate argparse defaults; `commands/*` is
  prompts, arg mapping and `sys.exit`. Note the reason is prompt/wiring
  density, *not* log-message density: message text was never mutated.

`config.py` and `api.py` were the two undecided cases; both were measured
(179 and 274 unexplained survivors) and are now gated. `api.py` needed no
allowlist entries at all — every one of its 274 survivors was a real test gap,
107 of them on functions no test executed.
