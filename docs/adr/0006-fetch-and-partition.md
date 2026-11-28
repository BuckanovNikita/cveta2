# Use completed CVAT results to decide which image annotations are current

## Current result per image

Use the latest completed result for each image. Completion requires every job in a task to be at acceptance/completed. Older completed rows go to obsolete. A newer unfinished live frame can reopen a completed deletion. An unfinished deletion stays pending. Those distinctions determine which rows belong in the dataset, in-progress and deletion outputs. [Partition cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_partition.py) · [Glossary and partition definitions](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/GLOSSARY.md)

## Full fetch and task fetch

A full fetch writes four partition outputs and a dataset draft. `--raw` adds all records including deletions, and `--save-tasks` preserves individual task tables. A task fetch selects tasks by ID or name and writes dataset and deletion tables. Empty frames survive extraction. Rectangles retain their pixel bounds, usable polygons become enclosing boxes, and CVAT issues can contribute frame or box review information. [Public fetch examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_fetch.py) · [Polygon extraction](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_polygon_fetch.py) · [Review issues](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_issues.py)

## Task selection and writes

The ignore list excludes task IDs. A silent entry suppresses its notice. `--completed-only` filters by CVAT task status. On a full fetch, `--skip-validation` promotes eligible completed annotation jobs to acceptance before reading them. A task without data contributes no cached rows, even in strict mode. A task-level server failure can yield a partial result or abort a strict fetch. [Task filtering](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/application/client/fetch.py) · [Skip-validation behavior](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_fetch_skip_validation.py)

## What counts as new

`whats-new` compares completed task IDs with the IDs represented in the fetched CSV and its eligible siblings. An unknown ID below the cutoff still qualifies. Project-wide label edits can change timestamps on every task, so update time cannot establish which tasks are new. [Known-task selection](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/application/client/read.py#L67) · [What’s-new examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_whats_new.py)
