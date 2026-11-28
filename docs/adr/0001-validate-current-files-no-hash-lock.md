# Validate the current files at publication

In 0.15, editing a row after preparation invalidated the recorded checksums. Since 0.16, publication reads the files as they are and validates their contents. Users can correct annotations, classes, roots or splits in a prepared bundle.

## What stops publication

- **Invalid content.** Examples include rejected rows, an active class with no bounding box, and an image assigned to multiple splits.
- **Stale remote state.** Check the ClearML parent again. For managed data, a different CVAT server or a task completed since fetch also requires a fresh preparation.

Other source differences produce warnings. Feedback skips and counts findings associated with the affected tasks.

## Alternatives considered

An allowlist of editable fields would still prevent correcting individual rows. Requiring the user to run verification again to seal each edit would add a step while checking the same content rules. Both options were rejected. This decision makes the completeness of the publication checks essential. [upload tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/bundle/test_upload.py)
