# Fetch interface contract

CLI: cveta2 fetch -p PROJECT -o OUTPUT --skip-validation. Boolean store_true;
false when omitted. Echo retains the flag when enabled. fetch-task rejects it.
API: cveta2.fetch(project, output_dir, *, skip_validation=False, ...), returning
the existing PartitionResult. fetch_task has no new parameter.

The option writes eligible jobs in CVAT before fetching annotations. It combines
with completed_only, raw, cache modes and normal output/image configuration.
Eligibility and errors follow [the specification](../spec.md). Existing schemas,
deletions, ordering and outputs follow the
[dataset contract](../../001-project-documentation/contracts/dataset-format.md).

Read/write errors identify task and job when available; listing errors identify
the project. No new annotation fetching/output publication occurs on failure.
Successful writes persist; rerun skips accepted jobs. Cache invalidation failure
aborts before updating that task; default fetch cache errors stay best effort.
