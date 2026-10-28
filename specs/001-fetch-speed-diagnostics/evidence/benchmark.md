# Fetch benchmark evidence — 2026-10-28

## Scope and method

The harness [benchmark_fetch.py](../../../scripts/benchmark_fetch.py) runs the
production application fetch, annotation extraction, local annotation cache,
image downloader, path enrichment, partition and four CSV writers. Only remote
CVAT/S3 responses are fixtures. Each simulated remote call sleeps 2 ms; image
bodies contain deterministic opaque bytes and are written to real local files.
There is no JPEG decoding or bandwidth simulation. Listing fixtures return a
whole page, so the large-batch case measures the listing-first branch, not real
S3 pagination throughput. The shared annotation cache mirror is disabled; local
annotation cache IO remains real.

Both revisions use CVAT=2 and S3=4 workers and three independent temporary
workspaces per workload. Warm runs first complete an unmeasured full fetch in
that workspace, then measure the second fetch. Timings include the full fetch
call (selection through final CSV writes), excluding fixture creation and the
post-run checks. `Path.resolve` counting adds the same lock/counter instrumentation
to both revisions. All cases verify output rows, local image count and total
image bytes. CSV hashes normalize only the temporary root path before comparing
all four output files, retaining row/column order and every data value.

These controlled measurements isolate removed work. They do not predict live
latency, remote filesystem performance or a universal percentage improvement.
Python import/startup cost, network bandwidth, S3 throttling, CVAT pagination and
real server load are outside the timed scope. Concurrent repository verification
may add scheduling noise; raw samples are retained alongside medians.

## Reproduction

From a configured checkout, run:

```bash
uv run python -m scripts.benchmark_fetch --label working-tree --output after.json
```

Extract base revision `13ffec2` using `git archive` into an owned temporary
directory. Set `PYTHONPATH` to that extracted directory and run the same harness
by its absolute path through the current `uv run python`, with
`--label 13ffec2 --output before.json`. The JSON fingerprints the imported fetch
module to distinguish the source revision without storing machine paths.
Both runs use the same dependency environment; neither contacts a real service.
The harness supports selected `--workload` values, repetitions, delay and worker
counts for further experiments. Do not compare reports with different settings.

## Baseline

Base is v0.11.1 commit `13ffec2`; [raw samples](benchmark-before.json).

| Workload | Images | Tasks | Boxes/image | Bytes/image | Baseline median, s |
| --- | ---: | ---: | ---: | ---: | ---: |
| cold | 80 | 8 | 3 | 32 KiB | 0.2104 |
| warm | 80 | 8 | 3 | 32 KiB | 0.0821 |
| fallback | 80 | 8 | 3 | 32 KiB | 0.2197 |
| large-image | 12 | 4 | 3 | 8 MiB | 0.0729 |
| annotation-heavy | 80 | 8 | 150 | 32 KiB | 0.9885 |
| large-batch | 2,048 | 8 | 1 | 4 KiB | 2.4396 |

Baseline cold requests are 80 GET + 80 HEAD, without a listing. Warm image cache
requests are zero. Fallback is 80 HEAD + 80 GET + two listing calls (prefix and
legacy subfolder). Large-batch lists once and sends 2,048 GETs, with zero HEAD.
Every baseline run lists tasks twice; ordinary fetch writes one debug CSV per
task and prepares/removes `.tasks`. Annotation-heavy enrichment contributes to
24,400 total `Path.resolve` calls during the fetch.

## After implementation

Integrated feature working tree; [raw samples](benchmark-after.json). Configuration
is identical to the baseline. All four normalized CSV hashes are identical across
both revisions and all three repetitions for every workload. All image counts,
byte totals and dataset row counts match the fixture contract.

| Workload | Before median, s | After median, s | Difference, s |
| --- | ---: | ---: | ---: |
| cold | 0.2104 | 0.1444 | -0.0660 |
| warm | 0.0821 | 0.0572 | -0.0249 |
| fallback | 0.2197 | 0.2012 | -0.0185 |
| large-image | 0.0729 | 0.0561 | -0.0168 |
| annotation-heavy | 0.9885 | 0.4084 | -0.5801 |
| large-batch | 2.4396 | 2.3853 | -0.0543 |

The cold case removes 80 HEAD calls while retaining 80 GETs and no list calls.
The warm case still sends zero S3 calls. Missing-key fallback sends 80 failed
canonical GETs plus 80 successful alternate-key GETs and two listings, replacing
80 HEADs plus 80 GETs without reducing its total object-request count. Large-batch
still lists first: 2,048 GETs, no HEAD, one listing in this fixture.

Every measured updated fetch lists project tasks once and performs zero `.tasks`
prepare/write/cleanup calls. Annotation-heavy total `Path.resolve` calls drop from
24,400 to 560, matching the 80-image cold case despite 50 times as many rows.
Large-batch has one row per image, so its resolution count remains 14,336; that
workload shows little timing change. The measurements support removed redundant
work, not a universal throughput claim.

## Harness verification

`uv run ruff check scripts/benchmark_fetch.py`,
`uv run mypy scripts/benchmark_fetch.py`, and
`uv run vulture scripts/benchmark_fetch.py` passed. Both revisions completed all six workloads and all row/image/byte checks across
three repetitions each. A separate comparison asserted identical configuration,
workload definitions and normalized CSV hashes for every sample.

Source audit confirmed the imported fetch fingerprints match base/current code,
and all three shared fixture modules are byte-identical to baseline. No runtime
or fixture files were changed by the benchmark workstream.
