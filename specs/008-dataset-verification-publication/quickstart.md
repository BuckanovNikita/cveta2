# Validation guide

Install with `uv sync --dev --extra clearml`. Use isolated fixture paths and valid
externally assigned train/val splits; live credentials come from existing runtime
configuration, never from the prepared bundle.

```bash
uv run cveta2 verify dataset.csv --profile cveta2
uv run cveta2 verify dataset.csv --profile clearml-yolo --clean --output-dir validation
uv run cveta2 verify fetch-output --bundle --project Inspection --dataset-name training \
  --api-url https://classes.example.org/api/classes --local-root /data/images \
  --s3-root s3://inspection/production --clean --output-dir prepared
uv run cveta2 upload-dataset prepared
```

Expect original files unchanged, source copies and diagnostics retained locally,
and exactly three files in a finalized child. Editing prepared payload/source files,
removing retained images or advancing the parent must block before child creation.
Use fake ports for unit scenarios and the repository integration lifecycle for live
checks. Follow [interfaces](contracts/interfaces.md) for exit codes and boundaries.
