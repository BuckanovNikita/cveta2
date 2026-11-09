# Task verification feasibility — 2026-11-09

These are manual tooling experiments in disposable repositories, not repository
product tests. No production hooks were changed during these experiments.
The project environment supplied CPython 3.12 and pytest-testmon 2.3.0; an
isolated `uv tool run --from go-task-bin task` supplied Task 3.54.0+pypi.
Experiments used one serial pytest process, with plugin autoload disabled and
only testmon explicitly enabled. pcboard could not resolve the `codex` session
without an exact key; work was limited to these tiny CPU-only fixtures.

## Selection

A disposable Git repository contained `src/calc.py` with independent `one()` and
`two()` functions, two tests accepting `one() in (1, 3)` and `two() == 2`, a
static text fixture, and a live directory whose conftest raised immediately if
loaded. Each command was launched through `uv run python` using that
interpreter's `-m pytest` entry point in the disposable working directory:

```text
python -m pytest -p testmon.pytest_testmon --testmon \
  --ignore=tests/integration --testmon-env=<namespace> -v
```

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `PYTHONDONTWRITEBYTECODE=1` were set.
The first two invocations also supplied `-m 'not integration'`.

| Observation/change | Executed tests | Result | Exit |
|---|---:|---|---:|
| First marker-filtered run | 2 | 2 passed; baseline collected | 0 |
| Unchanged marker-filtered repeat | 2 | 2 passed again | 0 |
| Same tree, directory exclusion alone | 0 | no tests ran | 0 |
| `one()` changed from 1 to 3 | 1 | 1 passed, 1 deselected | 0 |
| `one()` changed from 3 to 4 | 1 | 1 failed, 1 deselected | 1 |
| Unchanged repeat of failing tree | 1 | 1 failed again, 1 deselected | 1 |
| Repair `one()` to 1 | 1 | 1 passed, 1 deselected | 0 |
| Change pytest configuration | 2 | 2 passed | 0 |
| Change static fixture bytes | 2 | 2 passed | 0 |
| Add a Python member | 2 | 2 passed | 0 |
| Move that member between directories, retaining basename | 2 | 2 passed | 0 |
| Remove a different, originally present Python member | 2 | 2 passed | 0 |
| Unchanged repeat after removal | 0 | no tests ran | 0 |

Each executed pytest case took approximately 0.03 seconds within pytest
(0.04 seconds for the addition); these tiny-fixture timings are not a prediction
for repository verification. The live conftest was never loaded.

Installed `testmon/configure.py` checks `options['markexpr']`; installed option
help says marker selection forces `--testmon-noselect`. The
[official testmon options](https://www.testmon.org/) document both that behavior
and the supported `--testmon-env` namespace, and identify static assets as
untracked inputs. This reproduces the current unit hook's redundant execution.

An initial rapid-write draft exposed Python's timestamp/size `.pyc` reuse:
same-size edits made within one timestamp interval could execute old bytecode.
That draft's behavior-change results were discarded. The measured table uses a
fresh directory with bytecode generation disabled. This is a Python runtime
limitation, not evidence that testmon detected old-code execution.

## Namespace evaluated inside Task

The experiment hashed interpreter identity (`sys.version`, executable path,
implementation cache tag and platform), sorted full relative member paths, and
SHA-256 contents of non-Python inputs. Python member contents were left to
testmon. Configuration included the Taskfile itself, pytest configuration and a
fixture lockfile; assets included all non-Python files in source/test trees.
Generated cache paths were excluded. The real workflow must enumerate the
actual project's verification configuration and package/test assets.

Task's dynamic variable executed this inline Python (with `uv run ... python`):

```python
import hashlib
import json
import platform
import sys
from pathlib import Path

paths = sorted(
    path
    for base in ("src", "tests")
    for path in Path(base).rglob("*")
    if path.is_file() and "__pycache__" not in path.parts
)
paths += [Path("pytest.ini"), Path("uv.lock"), Path("Taskfile.yml")]
rows = [("interpreter", sys.version, sys.implementation.cache_tag, sys.executable, platform.platform())]
rows += [
    (path.as_posix(), "" if path.suffix == ".py" else hashlib.sha256(path.read_bytes()).hexdigest())
    for path in sorted(paths)
]
print(hashlib.sha256(json.dumps(rows).encode()).hexdigest())
```

The Task command passed `--testmon-env={{.TESTMON_ENV}}` and used no freshness
fields. With a third test present, observed Task runs were: baseline 3 passed;
unchanged 0 executed; configuration change 3 passed; static fixture change 3
passed; file removal 3 passed. All exited 0. This validates evaluating the
namespace through Task rather than an external result store.

A deterministic namespace may return to an earlier namespace when an exact
configuration/member set is restored. It can reuse that environment's valid
history; testmon still checks Python dependencies. New combinations above
received full baselines. No persisted success receipt or Task freshness was used.

## Interruption

A separate fixture test wrote a readiness file, slept, then asserted success.
The driver waited for readiness and sent SIGINT to the owned pytest process.
Pytest exited 2. Repeating the exact unchanged test and namespace (the sleep
was controlled only for the experiment through `PROBE_DELAY`) executed it and
passed, exit 0. A third unchanged run executed zero tests, exit 0. Thus an
interrupted, unfinished test did not become a successful completion record.
All driver-owned processes exited; no fixture server existed.

## Task ordering and exit status

Commands used `uv tool run --from go-task-bin task --exit-code --dir <fixture>
<task>`. Tasks with `exit 0`, `exit 3`, and `exit 1` returned 0, 3, and 1
respectively. A task calling the exit-3 task before a completion-marker command
returned 3 and never wrote the marker. This agrees with
[Task's documented `--exit-code`](https://taskfile.dev/docs/reference/cli).

Two sequential `verify` invocations each appended `check`, `test`, `build` in
that order, yielding precisely two executions of each command. There were no
`sources`, `generates`, `status` or other freshness declarations. Static commands
therefore still run each time; avoiding repeated pytest bodies is tool-native
selection, not skipped verification orchestration.

## Worktree isolation

The fixture was committed and a detached linked worktree was created. Invoking
the identical Taskfile in the linked worktree executed all three tests, exit 0,
although the original worktree had populated testmon history. Both worktrees
created separate `.testmondata` files. This establishes testmon's default
working-directory isolation; production environment and other cache placement
still require integrated validation.

## Staging guard experiment

The parent implementer independently exercised the proposed shell guard in a
disposable repository before production hook edits. A mock prek logged calls:

| Input | Exit | Cumulative prek calls |
|---|---:|---:|
| Clean | 0 | 1 |
| Unstaged tracked modification | 1 | 1 |
| Partially staged modification | 1 | 1 |
| Nonignored untracked file | 1 | 1 |
| Fully staged, prek configured to exit 7 | 7 | 2 |

The guard did not stage, stash, delete or otherwise mutate inputs. Compatibility
with actual shared hooks and old worktrees remains an integrated rollout check.

## Limits and disposition

The requested core selection, conservative namespace, failure replay,
interruption, Task exit propagation, sequencing and preliminary staging guard
cases succeeded. Proceed to implementation. These measurements do not establish
live service availability, repository-wide test correctness, hook installation
compatibility, or final acceptance. Those remain explicit later checks.

Disposable fixture repositories, linked worktree, raw logs and experiment scripts
were removed after this report was written. No task-owned process remains.
