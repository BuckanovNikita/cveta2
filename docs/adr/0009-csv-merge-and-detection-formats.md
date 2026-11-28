# Merge whole images and convert detection coordinates at format boundaries

## Choosing merge rows

Match by image name and take all rows from one input. The new input wins by default. With `--by-task` the highest maximum task ID wins, with ties going to the new input. Deletion removes the image from both inputs. Reopened-deletion evidence can suppress the old copy. A blank winning split can inherit the old assignment. [Merge through the API](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_api_projects.py) · [Merge cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_merge.py)

## Exporting detections

YOLO writes normalized center coordinates and sizes by split, with empty label files for negative images. COCO writes image and category IDs with pixel origin, width and height. Both exporters validate inputs before placing images. A rerun reconciles owned output files and preserves unrelated content. [YOLO cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_convert_yolo.py) · [COCO output](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_convert_coco.py) · [Export ownership cases](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_review_dataset.py)

## Importing YOLO

Dataset YAML supplies split and class definitions. Prediction files are paired with source images. At `8bf1e29`, import reuses the first image’s dimensions by default. For mixed sizes, `--read-all-sizes` measures each image so pixel coordinates use the correct dimensions. The original rationale for the default is unknown. [Import tests](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/tests/test_convert_yolo.py) · [Pinned conversion guide](https://github.com/BuckanovNikita/cveta2/blob/8bf1e29ad4176e47419c87797b554315798051b3/docs/commands/convert.md)
