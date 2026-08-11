# mutmut internals: what it mutates, what silently misconfigures, what it costs

Read this when a survivor's diff looks unkillable, when a config change to the
gate behaves oddly, or when judging whether a candidate module is worth gating.

## What actually gets mutated

Verified against the installed mutmut 3.7 source; several of these are
counter-intuitive and decide whether a module is worth gating at all.

- **Only code inside a top-level `FunctionDef`.** Module-level constants
  (`CSV_COLUMNS`, `_DIR_MODE`, `_HTTP_5XX_MIN`) produce no mutants. Note this
  as a fact about the tool, not as a technique: hoist a literal when the
  *code* wants it hoisted (it is shared, or it names something), never to
  silence the gate — see the "never reshape working code" rule in `SKILL.md`.
- **Decorated functions and classes are skipped entirely, body included**
  (`file_mutation.py:281-293`), except a single bare
  `@staticmethod`/`@classmethod`. So `@property`, `@contextmanager`,
  `@dataclass`, `@field_validator` and `@s3_retry` yield nothing. Pydantic
  models declared by inheritance are *not* skipped, so plain validator
  functions wired by class-body assignment still get mutated.
- **f-strings are never mutated** — the string operator fires only on
  `cst.SimpleString`, and triple-quoted strings are skipped as docs. Since this
  project logs exclusively via f-strings, log message text was never mutated;
  the patterns remove the remaining whole-argument-to-`None` mutant per call
  site.
- **`do_not_mutate_patterns` is `re.search` per line, not anchored**, and a
  matched line skips every *expression* starting on it plus its children — so
  `\btqdm\(` suppresses `for x in tqdm(items, desc=...)` without touching the
  loop body. It cannot single out one argument of a *multi-line* call, because
  the argument starts on a different line than the call; that residue is what
  the two `run_s3_transfers` caption entries in the allowlist are.
- **`# pragma: no mutate` only registers** on a standalone comment line or a
  simple statement's trailing comment, and marks the statement's *start* line.
  A trailing pragma on an argument line inside a multi-line call is silently
  ignored.
- **Parameter defaults are mutated** when they are a name, number or string
  (other expressions are skipped, since they run at definition time). A line
  pattern matches call sites, not `def` signatures, so a user-facing string
  used as a default has no pattern-level escape — which is why
  `interactive/primitives.py` keeps `_CANCELLED` and friends as names.
- **A glob matching no mutant crashes the run** (`assert filtered_mutants`), so
  never name a zero-mutant module in a profile.

## Config notes that are easy to get wrong

- `pytest_add_cli_args` must keep `-n 0`; mutmut runs `pytest.main()` in each
  forked child and the global `addopts = [..., "-n", "auto"]` would otherwise
  spawn an xdist pool per mutant, which looks like a hang.
- `cache_invalidation_files` + `on_dependency_change = "rerun"` are
  load-bearing: mutmut keys a cached verdict on the *source* function's text,
  so without them a weakened test leaves the gate green on stale results. The
  corollary is that editing any file under `tests/` re-runs the entire scope.
  A changed non-Python file that mutmut tracks (`pyproject.toml`, `uv.lock`)
  does the same — it reports `N non-Python file(s) changed; rerunning all
  mutants`, so a one-line allowlist edit costs a full-scope run.
- `mutate_only_covered_lines` must stay off — its coverage pre-pass leaves a
  half-imported numpy in `sys.modules` and the stats run then dies.
- **`only_mutate` and `do_not_mutate_patterns` are excluded from mutmut's own
  config fingerprint**, which hashes only pytest args, timeouts and the
  type-check command. Changing either therefore leaves a stale mutant tree:
  adding five modules to `only_mutate` once reported `0 files mutated, 6
  unmodified` and re-gated the old mutants as if nothing had changed.
  `scripts/mutation_config.py sync-scope` fingerprints those fields itself and
  wipes `mutants/` when they move, so this is handled automatically — but if
  you ever bypass `mutation_test.sh`, wipe `mutants/` by hand.
- **`cache_invalidation_files` re-runs mutants but does not re-derive which
  tests cover which mutant.** Add a *new* test aimed at a specific survivor and
  the gate can still report it as surviving, because the stats pass that
  associates tests with mutants is itself cached. The fix is `rm -rf mutants`
  and re-run. This one fails in the safe direction — a false red, not a false
  green — but it will make you doubt a correct test. Suspect it whenever a
  mutant survives whose diff you can show, by hand, that the new test rejects.
- `mutants/` is mutmut's working copy: gitignored, and excluded from mypy (two
  `cveta2` packages otherwise collide) and ruff.
- `mutation_test.sh` exports `PYTEST_DEBUG_TEMPROOT` into `mutants/`. By
  default every pytest run on the machine shares `/tmp/pytest-of-$USER`, and a
  concurrent session's cleanup can delete the `pytest-current` symlink out from
  under a mutant's forked child. The child then dies for reasons unrelated to
  the mutation and mutmut records it as *killed* — the gate lying in the unsafe
  direction. Observed while running several gates in parallel worktrees.

## Cost

Each run pays a fixed setup cost, then a throughput that is several times
higher over modules whose tests stay in memory than over ones that round-trip
CSVs through `tmp_path`. A fully cached run reports `0.00 mutations/second`.

`mutation_test.sh` prints the mutant count, the score and the elapsed time on
every run — read them from there rather than from this file. Profile
membership exists to keep `fast` meaningfully quicker than `full`: putting
*every* gated module in `fast` once measured the same as `full`, i.e. the
split bought nothing. When a newly gated module erases that gap again, leave
it to `full`.

Triage, not runtime, is the real cost: each survivor needs a diff read and a
judgement call.
