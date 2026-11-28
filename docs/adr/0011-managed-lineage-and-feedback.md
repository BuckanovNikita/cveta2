# Carry source evidence and image identity through a managed lineage

## Fetching sources

The global definition names sources and a ClearML destination. Discovery can list definitions, inspect a definition or list its finalized versions. A managed fetch snapshots CVAT project tasks and exact S3 CSV objects. A changed source can be reread independently when the remaining source evidence still supports reuse. [Definition and version operations](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/cveta2/interfaces/managed_datasets.py) · [Mixed-source and incremental fetch cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_managed_sources.py)

## Preparing a version

Use the transformed CSV with the source snapshot. Identical image content across sources requires a reviewed owner or exclusion. A renamed image keeps its published split by content. New splits can remain pending. Starting a managed lineage over non-managed history requires an explicit first version. A changed parent or CVAT server, or a task completed after fetch, can invalidate preparation. Other source changes can warn and suppress feedback for affected tasks. [Managed policies](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_managed_policies.py) · [Lineage and stale-source examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_managed_workflow.py)

## Comparing, reporting and publishing

`dataset diff` compares row multisets and summarizes images, classes and splits for local or published inputs. `report-errors` traces findings to CVAT frames, including findings from blocked preparations. Persist a receipt before delivery and reconcile it with remote issues on retry. Publication delivers eligible feedback, revalidates the files and finalizes `dataset.csv`, `dataset.yaml` and `tasks.yaml`. The task manifest carries the source snapshot. A forced resplit changes an inherited assignment, but identical content must still share one split within the version. [Diff contract](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/commands/dataset.md#L599) · [Feedback delivery](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_managed_feedback.py) · [Publication cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_managed_workflow.py)
