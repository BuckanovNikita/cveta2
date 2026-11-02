# Validation scenarios

1. Attach a shared project file with `cveta2 setup --project-config project-config.yaml`; inspect `cveta2 dataset list --json` without changing shared bytes.
2. Preview legacy configuration migration; cancel and verify original bytes, then approve and inspect separate personal/shared ownership.
3. Fetch a configured dataset combining two CVAT projects and one S3 CSV. Run an external script to produce transformed.csv.
4. Prepare with `cveta2 dataset prepare NAME transformed.csv --source fetched --output-dir prepared`; inspect reports; repeat with explicit `--clean` into a fresh directory when accepting rejected-image removal.
5. Report errors, retry, and verify issue counts remain stable. Publish and inspect exact three-file remote inventory.
6. Fetch again with unchanged tasks and verify zero annotation downloads; edit a task, labels, S3 CSV or relevant shared definition and verify invalidation/stale preparation rejection.
