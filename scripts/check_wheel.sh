#!/usr/bin/env bash
# Exercise the sdist-built wheel as a downstream CLI and Python library user.
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
cd "$scratch"
unset PYTHONPATH MYPYPATH CVETA2_GLOBAL_CONFIG CVAT_HOST CVAT_USERNAME CVAT_PASSWORD CVAT_ORGANIZATION
export CVETA2_CONFIG="$scratch/personal.yaml"

# By default uv build creates the sdist first, then builds the wheel from it.
uv build "$project" --out-dir "$scratch/dist"
for version in 3.12 3.13; do
    mkdir "$scratch/$version"
    cd "$scratch/$version"
    uv venv --python "$version" venv
    python="$PWD/venv/bin/python"
    uv pip install --python "$python" --no-deps "$scratch"/dist/*.whl
    # Treat the wheel's own runtime requirements as direct inputs to the resolver.
    "$python" -Ic 'from importlib.metadata import requires; print(*requires("cveta2"), sep="\n")' > requirements.txt
    uv pip install --python "$python" --resolution lowest-direct -r requirements.txt
    uv pip check --python "$python"
    venv/bin/cveta2 --help >/dev/null
    "$python" -Im cveta2 --help >/dev/null
    "$python" -Ic 'from importlib.metadata import version; print(version("cveta2"))' > expected-version
    venv/bin/cveta2 --version > console-version
    "$python" -Im cveta2 --version > module-version
    diff -u expected-version console-version
    diff -u expected-version module-version
    "$python" -I - <<'PY'
from importlib.resources import files
from pathlib import Path

from PIL import Image

import cveta2

assert files("cveta2").joinpath("py.typed").is_file()
assert cveta2.CvatConfig.load().host == "http://localhost:8080"
image = Path("frame.png")
Image.new("RGB", (80, 40)).save(image)
csv = Path("dataset.csv")
csv.write_text(
    "image_name,image_width,image_height,instance_shape,instance_label,split,bbox_x_tl,bbox_y_tl,bbox_x_br,bbox_y_br\n"
    "frame.png,80,40,box,cat,train,10,5,40,35\n",
    encoding="utf-8",
)
output = cveta2.convert_to_yolo(csv, "yolo", image_dirs=[image.parent], link_mode="copy")
assert (output / "images/train/frame.png").read_bytes() == image.read_bytes()
label = (output / "labels/train/frame.txt").read_text(encoding="utf-8").split()
assert [float(value) for value in label] == [0, 0.3125, 0.5, 0.375, 0.75], label
PY

    uv pip install --python "$python" mypy
    printf 'from cveta2 import Connection\nConnection(host="https://cvat.example")\n' > valid.py
    venv/bin/mypy --config-file= --strict valid.py
    printf 'from cveta2 import Connection\nConnection(host=123)\n' > invalid.py
    if venv/bin/mypy --config-file= --strict invalid.py > diagnostics; then
        echo "mypy accepted an integer Connection host" >&2
        exit 1
    fi
    grep -E 'invalid\.py:2:.*"host".*\[arg-type\]' diagnostics
done
