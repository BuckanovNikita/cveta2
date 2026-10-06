# Research

CSV shared reader already preserves NA-like strings; deleted CSV bypasses options. Export validates missing splits only and creates destination early. Image placement skips existing files. COCO has no pruning; its prior _annotations.coco.json can establish image ownership. YAML safe_load and integer conversion leak expected parse/type errors. YOLO float parsing accepts nonfinite and fractional IDs. Clone assumes first task images; helper upload replaces source IDs with list offsets.

Decisions: reuse shared CSV options; specific expected exceptions only; prevalidate dimensions/labels/coordinates; COCO prior metadata establishes cleanup ownership and must be confined. Keep legacy extra-field detection import compatibility. Sparse class mappings remain keyed mappings.
