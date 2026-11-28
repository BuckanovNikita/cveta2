# Preserve the user’s published split for each image

The user assigns each new image to train, val or test. An empty split is pending during preparation and prevents publication. Version 0.16 removed the 0.15 proportional split policy.

| Workflow | Image identity | Parent assignment during preparation |
| --- | --- | --- |
| Bundle | Image name | Fill empty split cells when the image’s other split cells agree with the parent. |
| Managed dataset | SHA-256 of the image content | Carry the published split forward, including when a file is renamed. |

Changing a published assignment requires `--force-resplit` on the publishing command. Within one managed version, identical content must occupy a single split even with that flag. A first managed lineage over non-managed history uses `dataset prepare --first` and takes its splits from the CSV.

A published split makes evaluation comparable across versions. Moving copies of the same image between train and test risks evaluation leakage. The flag makes a deliberate resplit visible. [splits tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_splits.py) [managed workflow tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_managed_workflow.py)
