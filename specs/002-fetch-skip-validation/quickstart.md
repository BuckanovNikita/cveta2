# Validation guide

Use an authorized disposable CVAT project with completed annotation jobs and an
unfinished task. Follow the repository running-integration-tests skill for shared
stand setup, one owned run tag and cleanup; do not place credentials here.

```bash
uv run cveta2 fetch -p PROJECT -o OUTPUT --skip-validation --completed-only --no-images --no-clearml
uv run pytest tests/test_fetch_skip_validation.py tests/test_api.py tests/test_cli_parsing.py tests/test_docs.py
```

The eligible task's jobs become acceptance/completed, task completion is refreshed
and its rows enter dataset.csv. The unfinished task is untouched. Repeat the fetch:
no further job updates are necessary. Omit --skip-validation to preserve current
CVAT state. The live test is tests/integration/test_fetch_skip_validation.py;
run it serially under the integration lifecycle skill, then clean the exact tag.
