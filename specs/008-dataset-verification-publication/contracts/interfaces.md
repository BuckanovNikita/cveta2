# CLI and Python contracts

- `cveta2 verify INPUT --profile {cveta2,clearml-yolo}` reports findings; `--clean`
  and `--output-dir DIR` explicitly export accepted corrections to a new location.
- `cveta2 verify FETCH_DIR --bundle --project PROJECT --dataset-name NAME
  --api-url URL --local-root DIR --s3-root URI --clean --output-dir PREPARED`
  prepares a reviewable bundle. Root options repeat; parent metadata can supply
  existing decisions. Missing decisions are structured for API callers and CLI
  interaction occurs outside application code.
- `cveta2 upload-dataset PREPARED` revalidates and publishes only the three payload
  files. It does not accept cleanup overrides or mutable source input.
- Public functions: `verify`, `verify_dataframe`, `schema_for`, `prepare_dataset`,
  `upload_dataset`; typed options/results are exported. APIs never prompt or exit.
- CLI verification status: 0 passed/explicit valid cleanup, 1 unresolved findings
  or cancellation, 2 malformed input/config/operational failure. Upload status:
  0 finalized, 1 cancellation, 2 blocked/error.
- Remove `fetch(..., publish_clearml=...)`, `--no-clearml`, `setup-clearml` and
  automatic ClearML settings/mappings. CVAT `upload` remains distinct and supported.

Payload: dataset.csv, dataset.yaml and tasks.yaml only. Local preparation record,
source CSVs, validation diagnostics and broken-image reports never enter ClearML.
Existing prepared directories and source files are never overwritten.
