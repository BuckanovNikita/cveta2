# Keep verification evidence alongside an editable publication payload

## Verifying rows

CSV verification returns rejected rows and reasons under the selected profile. An output directory saves the report and broken rows. `--clean` also writes the clean CSV. Python can return a DataFrame validation result or the profile schema. Bundle preparation accepts cleanup by default. Blockers suppress its payload, while pending splits can wait until publication. [Verification rules](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/verification/test_validation.py) · [CLI behavior and exit status](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_interfaces.py)

## Preparing the bundle

Resolve publication settings from explicit choices, the dataset draft and parent metadata. Match classes by registry number across renames, canonicalize aliases and reject excluded classes. Archive the four fetch tables and retain broken-image diagnostics and the verification report. A successful preparation also writes the editable payload and task manifest. [Draft handling](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_draft.py) · [Class reconciliation](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_classes.py) · [Preparation](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_preparation.py)

## Publishing the current files

Prefill eligible empty split cells by matching parent images by name. `upload-dataset` validates the edited files, rederives the task manifest and checks the parent before finalization. The version contains `dataset.csv`, `dataset.yaml`, `tasks.yaml` and `sources.tar.gz`. Image roots point to external images. [Bundle split cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_splits.py) · [Four-file publication and parent checks](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_upload.py)
