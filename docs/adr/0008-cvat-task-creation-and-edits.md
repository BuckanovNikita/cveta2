# Make CVAT task creation resumable and scope edits to the selected CVAT entity

## Frame selection

An upload label selects an entire image and all its annotations. The caller can exclude in-progress images. Validate that the target project supports the selected labels before writing the task. The ordered inputs and options identify the upload manifest. [Selection cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_upload_selection.py) · [Label validation](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_upload_label_validation.py) · [Upload manifest](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_upload_manifest.py)

## Resuming writes

`upload --resume` uses the saved task ID, server filenames and progress checkpoints. For review issues, reconcile the frame, position and comment with existing issues before creating another. `--mark-all-deleted` changes frame state. `--complete` sets every job to acceptance/completed. Python returns the task identity and counts. [Upload API](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_upload.py) · [Resume after a write](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/integration/test_review_remediation.py) · [Issue matching examples](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_issues.py)

## Project and task edits

Project label operations add, rename, recolor or delete labels. Interactive deletion checks usage and whether every task could be inspected. Python accepts explicit label IDs. Within a task, marking a frame deleted retains the task, dropping a label removes matching annotations, deleting the task removes it, and changing status updates the supplied fields on every job. [Interactive label operations](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_labels.py) · [Task writes through Python](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_task_ops.py)
