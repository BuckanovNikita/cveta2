# Data model

Split is train, val or test. YOLO class ID is nonnegative integral; normalized centers are finite [0,1], widths/heights finite (0,1], confidence finite [0,1]. Source names mappings accept nonnegative integer keys or decimal strings without collisions and nonempty unique string names. COCO ownership consists of known train/valid/test annotation JSON files and their safe basename image entries; unexpected directories/symlink parents/invalid metadata reject cleanup.
