"""Regression tests for dataset correctness findings."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from cveta2.exceptions import Cveta2Error
from cveta2.services.convert import convert_from_yolo, convert_to_coco, convert_to_yolo
from cveta2.services.convert.yolo import _normalize_class_names, _parse_label_file
from cveta2.services.merge import _read_deleted_names
from cveta2.services.output import read_dataset_csv
from tests.helpers import csv_row, make_image, write_convert_csv


def _helper_script(name: str) -> ModuleType:
    """Load a dev helper without making scripts a second package identity."""
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    if not path.is_file():
        pytest.skip("Helper scripts are absent from the copied source tree")
    spec = importlib.util.spec_from_file_location(f"review_{name}", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["NA", "N/A", "NULL", "001"])
def test_literal_deletion_names(tmp_path: Path, name: str) -> None:
    path = tmp_path / "deleted.csv"
    pd.DataFrame([{"image_name": name}]).to_csv(path, index=False)
    assert _read_deleted_names(path) == {name}


@pytest.mark.parametrize("export", [convert_to_yolo, convert_to_coco])
@pytest.mark.parametrize("split", [None, "validation", "../outside", "TRAIN"])
def test_export_rejects_every_invalid_split(
    tmp_path: Path, export: Any, split: str | None
) -> None:
    csv = write_convert_csv(
        tmp_path, [csv_row("a.jpg", split="train"), csv_row("b.jpg", split=split)]
    )
    output = tmp_path / "output"
    with pytest.raises(Cveta2Error):
        export(csv, output)
    assert not output.exists()


@pytest.mark.parametrize(
    ("export", "relative"),
    [(convert_to_yolo, "images/train/a.jpg"), (convert_to_coco, "train/a.jpg")],
)
@pytest.mark.parametrize("mode", ["copy", "hardlink", "symlink", "auto", "reflink"])
def test_repeat_export_refreshes_bytes(
    tmp_path: Path, export: Any, relative: str, mode: str
) -> None:
    images = tmp_path / "source"
    source = images / "a.jpg"
    make_image(source)
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    output = tmp_path / "output"
    export(csv, output, image_dirs=[images], link_mode=mode)
    source.unlink()
    source.write_bytes(b"replacement image")
    export(csv, output, image_dirs=[images], link_mode=mode)
    assert (output / relative).read_bytes() == source.read_bytes()


def test_coco_replaces_only_owned_files(tmp_path: Path) -> None:
    images = tmp_path / "source"
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        make_image(images / name)
    csv = write_convert_csv(
        tmp_path,
        [
            csv_row("a.jpg", split="train"),
            csv_row("b.jpg", split="val"),
            csv_row("c.jpg", split="train"),
        ],
    )
    output = tmp_path / "output"
    convert_to_coco(csv, output, image_dirs=[images], link_mode="copy")
    (output / "train/unrelated.jpg").write_bytes(b"keep")
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    convert_to_coco(csv, output, image_dirs=[images], link_mode="copy")
    assert not (output / "valid").exists()
    assert not (output / "train/c.jpg").exists()
    assert (output / "train/unrelated.jpg").read_bytes() == b"keep"


@pytest.mark.parametrize(
    "name", ["../victim.jpg", "/victim.jpg", "nested/victim.jpg", "bad\x00.jpg"]
)
def test_coco_rejects_unsafe_previous_metadata(tmp_path: Path, name: str) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    output = tmp_path / "output"
    split = output / "train"
    split.mkdir(parents=True)
    metadata = split / "_annotations.coco.json"
    text = json.dumps({"images": [{"file_name": name}]})
    metadata.write_text(text)
    with pytest.raises(Cveta2Error):
        convert_to_coco(csv, output)
    assert metadata.read_text() == text


def test_invalid_export_input_preserves_existing_destination(tmp_path: Path) -> None:
    csv = write_convert_csv(
        tmp_path, [csv_row("a.jpg", split="train", image_width="bad")]
    )
    output = tmp_path / "output"
    output.mkdir()
    (output / "sentinel").write_text("keep")
    with pytest.raises(Cveta2Error):
        convert_to_coco(csv, output)
    assert list(output.iterdir()) == [output / "sentinel"]


def test_csv_parser_error_is_contextual(tmp_path: Path) -> None:
    path = tmp_path / "broken.csv"
    path.write_text('image_name\n"unterminated\n')
    with pytest.raises(Cveta2Error, match=r"broken\.csv"):
        read_dataset_csv(path, {"image_name"})


@pytest.mark.parametrize(
    "names",
    [{"bad": "cat"}, {-1: "cat"}, {1.5: "cat"}, {0: None}, {0: "cat", "0": "dog"}],
)
def test_malformed_class_mapping_is_contextual(names: object) -> None:
    with pytest.raises(Cveta2Error, match=r"names\.yaml"):
        _normalize_class_names(names, Path("names.yaml"))


@pytest.mark.parametrize("names_mode", [False, True])
def test_yaml_syntax_error_is_contextual(tmp_path: Path, *, names_mode: bool) -> None:
    path = tmp_path / ("names.yaml" if names_mode else "dataset.yaml")
    path.write_text("names: [cat\n")
    with pytest.raises(Cveta2Error, match=path.name):
        convert_from_yolo(
            tmp_path, tmp_path / "out.csv", names_file=path if names_mode else None
        )


@pytest.mark.parametrize(
    "bad",
    [
        "1.9 .5 .5 .2 .2",
        "-1 .5 .5 .2 .2",
        "0 nan .5 .2 .2",
        "0 .5 inf .2 .2",
        "0 .5 .5 0 .2",
        "0 1.1 .5 .2 .2",
        "0 .5 .5 .2 .2 nan",
        "0 .5 .5 .2 .2 1.1",
    ],
)
def test_yolo_invalid_numeric_rows_preserve_valid_sibling(
    tmp_path: Path, bad: str
) -> None:
    path = tmp_path / "a.txt"
    path.write_text(bad + "\n0 .5 .5 .2 .2 .9\n")
    assert _parse_label_file(path) == [[0, 0.5, 0.5, 0.2, 0.2, 0.9]]


def test_clone_uses_each_tasks_frame_order(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    clone = _helper_script("clone_project_to_s3")

    source_tasks = [
        SimpleNamespace(id=11, name="one", subset=""),
        SimpleNamespace(id=12, name="two", subset=""),
    ]
    metadata = {
        11: SimpleNamespace(
            frames=[SimpleNamespace(name="z.jpg"), SimpleNamespace(name="a.jpg")],
            deleted_frames=[1],
        ),
        12: SimpleNamespace(frames=[SimpleNamespace(name="b.jpg")], deleted_frames=[]),
    }
    source = MagicMock()
    source.id, source.name = 1, "source"
    source.get_tasks.return_value = source_tasks
    source.get_labels.return_value = []
    destination = MagicMock()
    destination.id, destination.name = 2, "destination"
    destination.get_labels.return_value = []
    client = MagicMock()
    client.__enter__.return_value = client
    client.projects.list.return_value = [source]
    client.projects.retrieve.side_effect = lambda project_id: (
        source if project_id == 1 else destination
    )
    client.projects.create.return_value = destination
    api = client.api_client.tasks_api
    api.retrieve_data_meta.side_effect = lambda task_id: (metadata[task_id], None)
    api.retrieve_annotations.return_value = (
        SimpleNamespace(shapes=[], tracks=[]),
        None,
    )
    api.create.side_effect = [
        (SimpleNamespace(id=21), None),
        (SimpleNamespace(id=22), None),
    ]
    client.api_client.cloudstorages_api.retrieve.return_value = (
        SimpleNamespace(id=1, resource="bucket", specific_attributes="prefix=data"),
        None,
    )
    client.tasks.retrieve.side_effect = lambda task_id: SimpleNamespace(
        size=2,
        name="task",
        get_frame=lambda frame, **_: io.BytesIO(f"{task_id}:{frame}".encode()),
        remove_frames_by_ids=lambda _: None,
    )
    config = MagicMock()
    config.require_credentials.return_value = SimpleNamespace(
        host="host", username="u", password="p", organization=None
    )
    monkeypatch.setattr(clone.CvatConfig, "load", lambda: config)
    monkeypatch.setattr(clone, "make_client", lambda **_: client)
    monkeypatch.setattr(clone.time, "sleep", lambda _: None)
    s3 = MagicMock()
    monkeypatch.setattr(
        clone.boto3, "Session", lambda: SimpleNamespace(client=lambda *_, **__: s3)
    )
    monkeypatch.setattr(sys, "argv", ["clone", "--source", "source"])
    clone.main()
    requests = [call.kwargs["data_request"] for call in api.create_data.call_args_list]
    assert requests[0].server_files == [
        "data/source-s3/task_11/z.jpg",
        "data/source-s3/task_11/a.jpg",
    ]
    assert requests[1].server_files == ["data/source-s3/task_12/b.jpg"]
    assert requests[0].upload_file_order == requests[0].server_files
    assert str(requests[0].sorting_method) == "predefined"
    assert [call.kwargs["Body"] for call in s3.put_object.call_args_list] == [
        b"11:0",
        b"11:1",
        b"12:0",
    ]


def test_clone_empty_project_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    clone = _helper_script("clone_project_to_s3")

    source = MagicMock()
    source.id, source.name = 1, "source"
    source.get_tasks.return_value = []
    source.get_labels.return_value = []
    client = MagicMock()
    client.__enter__.return_value = client
    client.projects.list.return_value = [source]
    client.projects.retrieve.return_value = source
    client.projects.create.return_value = source
    client.api_client.cloudstorages_api.retrieve.return_value = (
        SimpleNamespace(id=1, resource="bucket", specific_attributes=""),
        None,
    )
    config = MagicMock()
    config.require_credentials.return_value = SimpleNamespace(
        host="host", username="u", password="p", organization=None
    )
    monkeypatch.setattr(clone.CvatConfig, "load", lambda: config)
    monkeypatch.setattr(clone, "make_client", lambda **_: client)
    monkeypatch.setattr(clone.boto3, "Session", MagicMock())
    monkeypatch.setattr(sys, "argv", ["clone", "--source", "source"])
    clone.main()
    client.projects.create.assert_called_once()
    client.api_client.tasks_api.create.assert_not_called()


def test_helper_sparse_class_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    upload = _helper_script("upload_dataset_to_cvat")

    image = tmp_path / "images/train/a.jpg"
    make_image(image)
    label = tmp_path / "labels/train/a.txt"
    label.parent.mkdir(parents=True)
    label.write_text("2 .5 .5 .2 .2\n5 .5 .5 .2 .2\n")
    yaml = tmp_path / "data.yaml"
    yaml.write_text("path: .\ntrain: images/train\nnames: {2: cat, 5: dog}\n")
    task = MagicMock()
    task.id, task.name, task.size = 9, "task", 1
    task.get_labels.return_value = [
        SimpleNamespace(name="cat", id=42),
        SimpleNamespace(name="dog", id=45),
    ]
    client = MagicMock()
    client.__enter__.return_value = client
    client.projects.create.return_value = SimpleNamespace(id=1, name="project")
    client.tasks.create_from_data.return_value = task
    config = MagicMock()
    config.require_credentials.return_value = SimpleNamespace(
        host="host", username="u", password="p", organization=None
    )
    monkeypatch.setattr(upload.CvatConfig, "load", lambda: config)
    monkeypatch.setattr(upload, "make_client", lambda **_: client)
    monkeypatch.setattr(sys, "argv", ["upload", "--yaml", str(yaml), "--tasks", "1"])
    upload.main()
    request = task.update_annotations.call_args.args[0]
    assert [shape.label_id for shape in request.shapes] == [42, 45]


def test_helper_unknown_class_rejected_before_remote_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys
    from unittest.mock import MagicMock

    upload = _helper_script("upload_dataset_to_cvat")

    make_image(tmp_path / "images/train/a.jpg")
    label = tmp_path / "labels/train/a.txt"
    label.parent.mkdir(parents=True)
    label.write_text("3 .5 .5 .2 .2\n")
    yaml = tmp_path / "data.yaml"
    yaml.write_text("path: .\ntrain: images/train\nnames: {2: cat}\n")
    remote = MagicMock()
    monkeypatch.setattr(upload, "make_client", remote)
    monkeypatch.setattr(sys, "argv", ["upload", "--yaml", str(yaml)])
    with pytest.raises(Cveta2Error, match="3"):
        upload.main()
    remote.assert_not_called()


def test_internal_reader_failure_is_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "dataset.csv"
    path.write_text("image_name\na.jpg\n")

    def internal_failure(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("internal bug")

    monkeypatch.setattr(pd, "read_csv", internal_failure)
    with pytest.raises(RuntimeError, match="internal bug"):
        read_dataset_csv(path, {"image_name"})


def test_clone_ambiguous_project_rejected_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    clone = _helper_script("clone_project_to_s3")

    client = MagicMock()
    client.__enter__.return_value = client
    client.projects.list.return_value = [
        SimpleNamespace(id=1, name="source"),
        SimpleNamespace(id=2, name="SOURCE"),
    ]
    config = MagicMock()
    config.require_credentials.return_value = SimpleNamespace(
        host="host", username="u", password="p", organization=None
    )
    monkeypatch.setattr(clone.CvatConfig, "load", lambda: config)
    monkeypatch.setattr(clone, "make_client", lambda **_: client)
    monkeypatch.setattr(sys, "argv", ["clone", "--source", "source"])
    with pytest.raises(Cveta2Error, match="1, 2"):
        clone.main()
    client.projects.create.assert_not_called()
    client.api_client.cloudstorages_api.retrieve.assert_not_called()


@pytest.mark.parametrize("class_id", ["-1", "1.9", "nan", "missing"])
def test_helper_invalid_class_ids_are_rejected(tmp_path: Path, class_id: str) -> None:
    upload = _helper_script("upload_dataset_to_cvat")

    path = tmp_path / "a.txt"
    path.write_text(f"{class_id} .5 .5 .2 .2\n")
    with pytest.raises(Cveta2Error, match=r"a\.txt:1"):
        upload.parse_yolo_label_file(path)


def test_coco_preserves_unowned_empty_split_directory(tmp_path: Path) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    output = tmp_path / "output"
    (output / "valid").mkdir(parents=True)
    convert_to_coco(csv, output)
    assert (output / "valid").is_dir()


def test_coco_rejects_symlink_cleanup_parent(tmp_path: Path) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    outside = tmp_path / "outside"
    outside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(outside, target_is_directory=True)
    with pytest.raises(Cveta2Error):
        convert_to_coco(csv, alias / "output")
    assert not (outside / "output").exists()


@pytest.mark.parametrize(
    "content",
    [
        "{",
        '{"images": 1}',
        '{"images": [{"file_name": "a.jpg"}, {"file_name": "a.jpg"}]}',
    ],
)
def test_coco_rejects_corrupt_or_ambiguous_metadata(
    tmp_path: Path, content: str
) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    output = tmp_path / "output"
    metadata = output / "train/_annotations.coco.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(content)
    with pytest.raises(Cveta2Error):
        convert_to_coco(csv, output)
    assert metadata.read_text() == content


def test_yolo_warning_identifies_line(tmp_path: Path, capture_logs: list[str]) -> None:
    path = tmp_path / "label.txt"
    path.write_text("\n0 nan .5 .2 .2\n0 .5 .5 .2 .2\n")
    assert len(_parse_label_file(path)) == 1
    assert f"{path}:2" in capture_logs[0]


def test_yaml_internal_failure_is_not_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import yaml

    path = tmp_path / "dataset.yaml"
    path.write_text("names: {0: cat}\n")

    def internal_failure(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("internal yaml bug")

    monkeypatch.setattr(yaml, "safe_load", internal_failure)
    with pytest.raises(RuntimeError, match="internal yaml bug"):
        convert_from_yolo(tmp_path, tmp_path / "out.csv")


@pytest.mark.parametrize("name", ["_annotations.coco.json", "bad\x00.jpg"])
def test_coco_rejects_reserved_or_invalid_current_name_before_writes(
    tmp_path: Path, name: str
) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("placeholder.jpg", split="train")])
    # Build malformed bytes directly: pandas versions differ on writing NUL cells.
    csv.write_bytes(csv.read_bytes().replace(b"placeholder.jpg", name.encode("utf-8")))
    output = tmp_path / "output"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_bytes(b"keep")
    with pytest.raises(Cveta2Error):
        convert_to_coco(csv, output)
    assert list(output.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"keep"


def test_csv_reader_stops_after_first_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    class BoundedEofStream(io.BytesIO):
        """A owned stream that reports misuse immediately instead of hanging."""

        ended = False

        def read(self, size: int | None = -1) -> bytes:
            if self.ended:
                raise AssertionError("reader continued after EOF")
            value = super().read(size)
            self.ended = not value
            return value

    path = tmp_path / "finite.csv"
    content = b"image_name\na.jpg\n"
    path.write_bytes(content)
    original_open = Path.open

    def open_owned_stream(
        file: Path, mode: str = "r", *args: Any, **kwargs: Any
    ) -> Any:
        if file == path and mode == "rb":
            return BoundedEofStream(content)
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_owned_stream)
    assert read_dataset_csv(path, {"image_name"})["image_name"].tolist() == ["a.jpg"]


def test_csv_nul_failure_has_source_context(tmp_path: Path) -> None:
    path = tmp_path / "nul.csv"
    path.write_bytes(b"image_name\na\x00.jpg\n")
    with pytest.raises(Cveta2Error) as error:
        read_dataset_csv(path, {"image_name"})
    assert str(path) in str(error.value)


def test_deleted_invalid_utf8_has_source_context(tmp_path: Path) -> None:
    path = tmp_path / "deleted.csv"
    path.write_bytes(b"image_name\n\xff\n")
    with pytest.raises(Cveta2Error) as error:
        _read_deleted_names(path)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("line", ["0 0 1 1 1 0", "0 1 0 1 1 1"])
def test_yolo_numeric_endpoints_are_accepted(tmp_path: Path, line: str) -> None:
    path = tmp_path / "endpoints.txt"
    path.write_text(line + "\n")
    assert _parse_label_file(path) == [[float(value) for value in line.split()]]


@pytest.mark.parametrize(
    "line", ["0 .5 .5 1.01 .5", "0 .5 .5 .5 1.01", "0 -.01 .5 .5 .5", "0 .5 -.01 .5 .5"]
)
def test_yolo_out_of_domain_siblings_are_skipped(tmp_path: Path, line: str) -> None:
    path = tmp_path / "outside.txt"
    path.write_text(line + "\n0 .5 .5 .5 .5\n")
    assert _parse_label_file(path) == [[0, 0.5, 0.5, 0.5, 0.5]]


@pytest.mark.parametrize("names", [{0: " "}, {0: "cat", 1: "cat"}])
def test_names_reject_whitespace_and_duplicate_values(names: object) -> None:
    source = Path("source-names.yaml")
    with pytest.raises(Cveta2Error) as error:
        _normalize_class_names(names, source)
    assert str(source) in str(error.value)


def test_flat_names_yaml_bad_key_has_context(tmp_path: Path) -> None:
    from cveta2.services.convert.yolo import _load_class_names_yaml

    path = tmp_path / "flat-names.yaml"
    path.write_text("bad: cat\n")
    with pytest.raises(Cveta2Error) as error:
        _load_class_names_yaml(path)
    assert str(path) in str(error.value)


def test_dataset_root_type_error_has_context(tmp_path: Path) -> None:
    path = tmp_path / "dataset.yaml"
    path.write_text("path: [invalid]\nnames: {0: cat}\ntrain: images/train\n")
    with pytest.raises(Cveta2Error) as error:
        convert_from_yolo(tmp_path, tmp_path / "out.csv")
    assert str(path) in str(error.value)


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
@pytest.mark.parametrize(
    "column",
    [
        "image_width",
        "image_height",
        "instance_label",
        "bbox_x_tl",
        "bbox_y_tl",
        "bbox_x_br",
        "bbox_y_br",
    ],
)
def test_export_missing_columns_rejected_before_output(
    tmp_path: Path, export: Any, column: str
) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    df = pd.read_csv(csv)
    df.drop(columns=[column]).to_csv(csv, index=False)
    output = tmp_path / "out"
    with pytest.raises(Cveta2Error) as error:
        export(csv, output)
    assert column in str(error.value)
    assert str(csv) in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
@pytest.mark.parametrize("shape", ["none", "box"])
@pytest.mark.parametrize("column", ["image_width", "image_height"])
@pytest.mark.parametrize("value", [0, -1, 0.5, "bad", "inf", "nan"])
def test_export_dimensions_are_validated_before_output(
    tmp_path: Path, export: Any, shape: str, column: str, value: Any
) -> None:
    row = csv_row("dimension.jpg", shape=shape, split="train")
    row[column] = value
    csv = write_convert_csv(tmp_path, [row])
    output = tmp_path / "out"
    with pytest.raises(Cveta2Error) as error:
        export(csv, output)
    assert "dimension.jpg" in str(error.value)
    assert str(csv) in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
def test_export_accepts_one_pixel_dimensions(tmp_path: Path, export: Any) -> None:
    csv = write_convert_csv(
        tmp_path,
        [
            csv_row(
                "one.jpg", shape="none", split="train", image_width=1, image_height=1
            )
        ],
    )
    output = tmp_path / "out"
    export(csv, output)
    assert output.is_dir()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
@pytest.mark.parametrize("name", [None, "nested/a.jpg", "..", "a\\b.jpg"])
def test_export_invalid_names_have_context_without_output(
    tmp_path: Path, export: Any, name: str | None
) -> None:
    row = csv_row("placeholder.jpg", split="train")
    row["image_name"] = name
    csv = write_convert_csv(tmp_path, [row])
    output = tmp_path / "out"
    with pytest.raises(Cveta2Error) as error:
        export(csv, output)
    assert str(csv) in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
@pytest.mark.parametrize(
    "coords",
    [
        (10, 20, 10, 120),
        (10, 20, 110, 20),
        (10, 20, 9, 120),
        (10, 20, 110, 19),
        ("nan", 20, 110, 120),
        (10, 20, "inf", 120),
        ("bad", 20, 110, 120),
    ],
)
def test_export_invalid_boxes_have_context_without_output(
    tmp_path: Path, export: Any, coords: tuple[Any, Any, Any, Any]
) -> None:
    row = csv_row("box.jpg", split="train")
    for key, value in zip(
        ("bbox_x_tl", "bbox_y_tl", "bbox_x_br", "bbox_y_br"), coords, strict=True
    ):
        row[key] = value
    csv = write_convert_csv(tmp_path, [row])
    output = tmp_path / "out"
    with pytest.raises(Cveta2Error) as error:
        export(csv, output)
    assert "box.jpg" in str(error.value)
    assert str(csv) in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
def test_export_valid_box_axes_are_independent(tmp_path: Path, export: Any) -> None:
    csv = write_convert_csv(
        tmp_path,
        [
            csv_row(
                "box.jpg",
                split="train",
                bbox_x_tl=10,
                bbox_y_tl=200,
                bbox_x_br=110,
                bbox_y_br=300,
            )
        ],
    )
    assert export(csv, tmp_path / "out").is_dir()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
def test_export_missing_label_has_context_without_output(
    tmp_path: Path, export: Any
) -> None:
    row = csv_row("unlabelled.jpg", split="train")
    row["instance_label"] = None
    csv = write_convert_csv(tmp_path, [row])
    output = tmp_path / "out"
    with pytest.raises(Cveta2Error) as error:
        export(csv, output)
    assert "unlabelled.jpg" in str(error.value)
    assert str(csv) in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
def test_export_split_error_identifies_value_and_image(
    tmp_path: Path, export: Any
) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("split.jpg", split="validation")])
    with pytest.raises(Cveta2Error) as error:
        export(csv, tmp_path / "out")
    message = str(error.value)
    assert "validation" in message
    assert "split.jpg" in message
    assert all(split in message.lower() for split in ("train", "val", "test"))


@pytest.mark.parametrize("export", [convert_to_coco, convert_to_yolo])
def test_invalid_link_mode_identified_before_output(
    tmp_path: Path, export: Any
) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    output = tmp_path / "out"
    with pytest.raises(Cveta2Error) as error:
        export(csv, output, link_mode="invalid-mode")
    assert "invalid-mode" in str(error.value)
    assert not output.exists()


@pytest.mark.parametrize("split", ["val", "test"])
def test_coco_repeated_retained_split_preserves_current_output(
    tmp_path: Path, split: str
) -> None:
    images = tmp_path / "source"
    make_image(images / "a.jpg")
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split=split)])
    output = tmp_path / "out"
    convert_to_coco(csv, output, image_dirs=[images], link_mode="copy")
    convert_to_coco(csv, output, image_dirs=[images], link_mode="copy")
    directory = output / ("valid" if split == "val" else split)
    assert (directory / "a.jpg").read_bytes() == (images / "a.jpg").read_bytes()
    assert (
        json.loads((directory / "_annotations.coco.json").read_text())["images"][0][
            "file_name"
        ]
        == "a.jpg"
    )


def test_coco_removes_owned_test_split_even_without_train_metadata(
    tmp_path: Path,
) -> None:
    images = tmp_path / "source"
    make_image(images / "a.jpg")
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="test")])
    output = tmp_path / "out"
    convert_to_coco(csv, output, image_dirs=[images], link_mode="copy")
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="val")])
    convert_to_coco(csv, output, image_dirs=[images], link_mode="copy")
    assert not (output / "test").exists()
    assert (output / "valid/a.jpg").is_file()


@pytest.mark.parametrize("split", ["train", "valid"])
@pytest.mark.parametrize("dangling", [False, True])
def test_coco_unowned_image_collision_rejected_with_context(
    tmp_path: Path, split: str, *, dangling: bool
) -> None:
    output = tmp_path / "out"
    directory = output / split
    directory.mkdir(parents=True)
    destination = directory / "a.jpg"
    if dangling:
        destination.symlink_to(tmp_path / "absent.jpg")
    else:
        destination.write_bytes(b"unrelated")
    csv = write_convert_csv(
        tmp_path, [csv_row("a.jpg", split="val" if split == "valid" else split)]
    )
    with pytest.raises(Cveta2Error) as error:
        convert_to_coco(csv, output)
    assert str(destination) in str(error.value)
    assert not (directory / "_annotations.coco.json").exists()
    assert (
        destination.is_symlink()
        if dangling
        else destination.read_bytes() == b"unrelated"
    )


@pytest.mark.parametrize(
    "kind", ["split-file", "split-symlink", "metadata-symlink", "root-symlink"]
)
def test_coco_unsafe_destination_types_rejected_with_context(
    tmp_path: Path, kind: str
) -> None:
    output = tmp_path / "out"
    output.mkdir()
    directory = output / "test"
    metadata = directory / "_annotations.coco.json"
    if kind == "split-file":
        directory.write_text("unrelated")
        unsafe = directory
    elif kind == "split-symlink":
        outside = tmp_path / "outside"
        outside.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
        unsafe = directory
    elif kind == "metadata-symlink":
        directory.mkdir()
        outside = tmp_path / "metadata.json"
        outside.write_text('{"images": []}')
        metadata.symlink_to(outside)
        unsafe = metadata
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(output, target_is_directory=True)
        output = alias
        unsafe = alias
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    with pytest.raises(Cveta2Error) as error:
        convert_to_coco(csv, output)
    assert str(unsafe) in str(error.value)
    assert not (output / "train").exists()


@pytest.mark.parametrize("name", [7, "", "..", "_annotations.coco.json", "a\\b.jpg"])
def test_coco_invalid_owned_names_identify_metadata(
    tmp_path: Path, name: object
) -> None:
    output = tmp_path / "out"
    metadata = output / "train/_annotations.coco.json"
    metadata.parent.mkdir(parents=True)
    content = json.dumps({"images": [{"file_name": name}]})
    metadata.write_text(content)
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    with pytest.raises(Cveta2Error) as error:
        convert_to_coco(csv, output)
    assert str(metadata) in str(error.value)
    assert metadata.read_text() == content


@pytest.mark.parametrize("content", ["{", '{"images": 1}'])
def test_coco_metadata_parse_errors_identify_source(
    tmp_path: Path, content: str
) -> None:
    output = tmp_path / "out"
    metadata = output / "train/_annotations.coco.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(content)
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    with pytest.raises(Cveta2Error) as error:
        convert_to_coco(csv, output)
    assert str(metadata) in str(error.value)
    assert metadata.read_text() == content


def test_coco_owned_image_directory_rejected_with_context(tmp_path: Path) -> None:
    output = tmp_path / "out"
    metadata = output / "train/_annotations.coco.json"
    destination = output / "train/a.jpg"
    destination.mkdir(parents=True)
    metadata.write_text('{"images": [{"file_name": "a.jpg"}]}')
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    with pytest.raises(Cveta2Error) as error:
        convert_to_coco(csv, output)
    assert str(destination) in str(error.value)
    assert destination.is_dir()


def test_coco_prunes_missing_owned_image_without_error(tmp_path: Path) -> None:
    csv = write_convert_csv(tmp_path, [csv_row("absent.jpg", split="test")])
    output = tmp_path / "out"
    convert_to_coco(csv, output)
    assert not (output / "test/absent.jpg").exists()
    csv = write_convert_csv(tmp_path, [csv_row("a.jpg", split="train")])
    convert_to_coco(csv, output)
    assert not (output / "test").exists()
    assert (output / "train/_annotations.coco.json").is_file()


def test_reserved_coco_image_diagnostic_identifies_conflict(tmp_path: Path) -> None:
    csv = write_convert_csv(
        tmp_path, [csv_row("_annotations.coco.json", split="train")]
    )
    with pytest.raises(Cveta2Error) as error:
        convert_to_coco(csv, tmp_path / "out")
    assert "_annotations.coco.json" in str(error.value)


def test_csv_reader_guard_is_collected_before_real_reader() -> None:
    import subprocess

    real_reader = "tests/test_output.py::test_read_dataset_csv_returns_rows"
    bounded_reader = (
        "tests/test_review_dataset.py::test_csv_reader_stops_after_first_eof"
    )
    # Explicit node order models mutmut's unordered caller set; collection must
    # retain both tests while putting finite-EOF verification ahead of real IO.
    result = subprocess.run(  # noqa: S603 - fixed pytest nodes and current interpreter
        [
            sys.executable,
            "-m",
            "pytest",
            real_reader,
            bounded_reader,
            "--collect-only",
            "-q",
            "-o",
            "addopts=-p tests.env_isolation",
            "-p",
            "no:cacheprovider",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nodeids = [
        line
        for line in result.stdout.splitlines()
        if line in {real_reader, bounded_reader}
    ]
    assert nodeids == [bounded_reader, real_reader]
