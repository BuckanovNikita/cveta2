"""Unit tests for cveta2/services/convert/common.py.

Coordinate conversion, image linking, search-dir resolution, CSV row
builders and split validation — everything the YOLO and COCO exporters
share.
"""

from __future__ import annotations

import errno
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml

from cveta2.commands.convert import run_convert
from cveta2.exceptions import Cveta2Error
from cveta2.models import CSV_COLUMNS
from cveta2.services.convert import common as convert
from cveta2.services.convert import (
    convert_to_coco,
    convert_to_yolo,
)
from cveta2.services.convert.common import (
    CocoBox,
    PixelBox,
    YoloBox,
    _build_search_dirs,
    _find_image_by_stem,
    _link_or_copy,
    _make_csv_row_base,
    _make_csv_row_box,
    _pixel_to_coco,
    _pixel_to_yolo,
    _require_positive_dimensions,
    _SizeCache,
    _validate_splits,
    _write_csv,
    _yolo_to_pixel,
)
from cveta2.services.output import read_text_utf8, write_text_utf8
from tests.helpers import (
    csv_row,
    make_image,
    parse_cli_args,
    write_convert_csv,
)


class TestCoordinateConversion:
    """Tests for pixel <-> YOLO coordinate conversion."""

    @pytest.mark.parametrize(
        ("result", "expected"),
        [
            (
                _pixel_to_yolo(PixelBox(100, 50, 200, 150), 400, 300),
                YoloBox(0.375, 1.0 / 3.0, 0.25, 1.0 / 3.0),
            ),
            (
                _yolo_to_pixel(YoloBox(0.5, 0.5, 0.5, 0.5), 640, 480),
                PixelBox(160.0, 120.0, 480.0, 360.0),
            ),
            (
                _pixel_to_coco(PixelBox(100, 50, 300, 250)),
                CocoBox(x=100, y=50, w=200, h=200),
            ),
        ],
    )
    def test_conversion_directions(
        self,
        result: tuple[float, ...],
        expected: tuple[float, ...],
    ) -> None:
        assert result == pytest.approx(expected)

    def test_roundtrip(self) -> None:
        """Pixel -> yolo -> pixel should recover original coords."""
        original = PixelBox(50.0, 30.0, 200.0, 180.0)
        img_w, img_h = 640, 480
        yolo = _pixel_to_yolo(original, img_w, img_h)
        recovered = _yolo_to_pixel(yolo, img_w, img_h)
        assert recovered.x_tl == pytest.approx(original.x_tl, abs=0.01)
        assert recovered.y_tl == pytest.approx(original.y_tl, abs=0.01)
        assert recovered.x_br == pytest.approx(original.x_br, abs=0.01)
        assert recovered.y_br == pytest.approx(original.y_br, abs=0.01)

    @pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (0, 0), (-1, 5)])
    def test_non_positive_dimensions_raise(self, width: int, height: int) -> None:
        with pytest.raises(Cveta2Error, match="некорректный размер"):
            _require_positive_dimensions(width, height, "bad.jpg")

    @pytest.mark.parametrize(
        ("width", "height"), [(1, 1), (1, 480), (640, 1), (640, 480)]
    )
    def test_positive_dimensions_pass(self, width: int, height: int) -> None:
        """A single-pixel dimension is valid.

        The old test only passed 640x480, so widening either bound to
        ``<= 1`` (rejecting 1-pixel images) changed nothing observable.
        """
        _require_positive_dimensions(width, height, "ok.jpg")


class TestLinkOrCopy:
    """Tests for _link_or_copy file placement."""

    @pytest.mark.parametrize("mode", ["copy", "symlink", "hardlink"])
    def test_link_mode_places_file(self, tmp_path: Path, mode: str) -> None:
        """Destination sits two levels deep, so ``parents=True`` is load-bearing.

        The old destination was ``tmp_path/out/dst.txt`` — one missing
        level, which ``mkdir(parents=False)`` still creates.
        """
        src = tmp_path / "src.txt"
        src.write_text("hello")
        dst = tmp_path / "out" / "deep" / "dst.txt"
        _link_or_copy(src, dst, mode)
        assert dst.read_text() == "hello"
        if mode == "symlink":
            assert dst.is_symlink()
        if mode == "hardlink":
            assert src.stat().st_ino == dst.stat().st_ino

    def test_unknown_mode_rejected(self, tmp_path: Path) -> None:
        """An unrecognised link mode names itself in the error.

        Nothing exercised the ``else`` branch, so replacing its whole
        message with ``None`` was invisible.
        """
        src = tmp_path / "src.txt"
        src.write_text("hello")
        with pytest.raises(Cveta2Error, match="Неизвестный link-mode: 'teleport'"):
            _link_or_copy(src, tmp_path / "dst.txt", "teleport")

    def test_skip_existing(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("new")
        dst = tmp_path / "dst.txt"
        dst.write_text("old")
        _link_or_copy(src, dst, "copy")
        assert dst.read_text() == "old"  # not overwritten


class TestReflinkFallback:
    """Tests for fallback to plain copy when reflink fails."""

    @pytest.fixture(autouse=True)
    def _reset_warned_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(convert, "_reflink_warner", convert._OnceWarner())

    @staticmethod
    def _make_src(tmp_path: Path, name: str = "src.txt") -> Path:
        src = tmp_path / name
        src.write_text("hello")
        return src

    @pytest.mark.parametrize(
        ("mode", "patch_target"),
        [
            ("reflink", "reflink_copy.reflink"),
            ("auto", "reflink_copy.reflink_or_copy"),
        ],
    )
    def test_falls_back_to_copy_on_oserror(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
        mode: str,
        patch_target: str,
    ) -> None:
        def failing(_src: str, _dst: str) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(patch_target, failing)
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, mode)
        assert dst.read_text() == "hello"
        assert any("reflink недоступен" in m for m in capture_logs)

    def test_half_created_dst_removed_before_copy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def failing_reflink(_src: str, dst: str) -> None:
            Path(dst).write_text("partial")
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr("reflink_copy.reflink", failing_reflink)
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "reflink")
        assert dst.read_text() == "hello"

    def test_warning_emitted_once_for_multiple_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        def failing_reflink(_src: str, _dst: str) -> None:
            raise OSError(errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr("reflink_copy.reflink", failing_reflink)
        for i in range(3):
            src = self._make_src(tmp_path, f"src{i}.txt")
            _link_or_copy(src, tmp_path / "out" / f"dst{i}.txt", "reflink")
        warnings = [m for m in capture_logs if "reflink недоступен" in m]
        assert len(warnings) == 1

    def test_reflink_success_no_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        def succeeding_reflink(src: str, dst: str) -> None:
            shutil.copy2(src, dst)

        monkeypatch.setattr("reflink_copy.reflink", succeeding_reflink)
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "reflink")
        assert dst.read_text() == "hello"
        assert not capture_logs

    def test_auto_mode_real_library_no_warning(
        self,
        tmp_path: Path,
        capture_logs: list[str],
    ) -> None:
        src = self._make_src(tmp_path)
        dst = tmp_path / "out" / "dst.txt"
        _link_or_copy(src, dst, "auto")
        assert dst.read_text() == "hello"
        assert not capture_logs


class TestSizeCache:
    """Tests for _SizeCache image dimension caching."""

    def test_read_all_false_returns_first_size(self, tmp_path: Path) -> None:
        """When read_all=False, all calls return the first image's size."""
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache(read_all=False)
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (640, 480)

    def test_default_reuses_the_first_size(self, tmp_path: Path) -> None:
        """Constructed with no arguments, the cache measures only once.

        Both existing tests pass ``read_all`` explicitly, so flipping the
        default was never observed.
        """
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache()
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (640, 480)

    def test_read_all_true_reads_each_image(self, tmp_path: Path) -> None:
        """When read_all=True, each image is read individually."""
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache(read_all=True)
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == (320, 240)


class TestUtf8FileHelpers:
    """Tests for the locale-independent text read/write helpers."""

    def test_roundtrip_writes_utf8_bytes_and_keeps_newlines(
        self, tmp_path: Path
    ) -> None:
        """Content is encoded as UTF-8 with untranslated line endings.

        Nothing ever read the raw bytes of a label file or dataset.yaml back,
        so the codec used to write them was unconstrained.
        """
        path = tmp_path / "t.txt"
        text = "кошка\nсобака\n"
        write_text_utf8(path, text)
        assert path.read_bytes() == text.encode("utf-8")
        assert read_text_utf8(path) == text


class TestBuildSearchDirs:
    """Tests for combining --image-dir args with the image-cache config."""

    @staticmethod
    def _write_image_cache(config_path: Path, projects: dict[str, Path]) -> None:
        config_path.write_text(
            yaml.dump({"image_cache": {k: str(v) for k, v in projects.items()}}),
            encoding="utf-8",
        )

    def test_cache_dirs_follow_the_explicit_ones(
        self, tmp_path: Path, isolated_config_path: Path
    ) -> None:
        """Configured cache dirs are appended after the --image-dir args.

        No test called this function at all, so both the dedup check and the
        appended value itself were free.
        """
        self._write_image_cache(
            isolated_config_path, {"p1": tmp_path / "c1", "p2": tmp_path / "c2"}
        )
        assert _build_search_dirs([tmp_path / "given"]) == [
            tmp_path / "given",
            tmp_path / "c1",
            tmp_path / "c2",
        ]

    def test_cache_dir_already_given_is_not_repeated(
        self, tmp_path: Path, isolated_config_path: Path
    ) -> None:
        """A cache dir passed as --image-dir appears once, not twice."""
        self._write_image_cache(isolated_config_path, {"p1": tmp_path / "shared"})
        assert _build_search_dirs([tmp_path / "shared"]) == [tmp_path / "shared"]

    def test_without_args_only_cache_dirs_remain(
        self, tmp_path: Path, isolated_config_path: Path
    ) -> None:
        """With no --image-dir args the cache dirs are the whole search path."""
        self._write_image_cache(isolated_config_path, {"p1": tmp_path / "c1"})
        assert _build_search_dirs(None) == [tmp_path / "c1"]


class TestFindImageByStem:
    """Tests for the search order of ``_find_image_by_stem``."""

    def test_flat_file_beats_subdir(self, tmp_path: Path) -> None:
        """A flat hit wins over the same stem inside a subdir."""
        make_image(tmp_path / "a.jpg")
        make_image(tmp_path / "images" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path], subdirs=["images"])
        assert found == tmp_path / "a.jpg"

    def test_earlier_extension_wins(self, tmp_path: Path) -> None:
        """``.jpg`` precedes ``.png`` in the extension order."""
        make_image(tmp_path / "a.png")
        make_image(tmp_path / "a.jpg")
        assert _find_image_by_stem("a", [tmp_path]) == tmp_path / "a.jpg"

    def test_earlier_dir_wins(self, tmp_path: Path) -> None:
        """The first search dir holding the stem wins."""
        make_image(tmp_path / "first" / "a.jpg")
        make_image(tmp_path / "second" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path / "first", tmp_path / "second"])
        assert found == tmp_path / "first" / "a.jpg"

    def test_missing_dir_does_not_stop_the_search(self, tmp_path: Path) -> None:
        """A nonexistent search dir is skipped, not treated as the end.

        Only ever called with existing dirs, so turning the ``continue``
        into a ``break`` was invisible.
        """
        make_image(tmp_path / "real" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path / "gone", tmp_path / "real"])
        assert found == tmp_path / "real" / "a.jpg"

    def test_found_inside_subdir(self, tmp_path: Path) -> None:
        """A stem only present under a subdir is still found.

        Every previous call resolved on the flat ``.jpg`` case, so the whole
        subdir loop was unexecuted.
        """
        make_image(tmp_path / "images" / "a.png")
        found = _find_image_by_stem("a", [tmp_path], subdirs=["images"])
        assert found == tmp_path / "images" / "a.png"

    def test_missing_subdir_does_not_stop_the_search(self, tmp_path: Path) -> None:
        """A nonexistent subdir is skipped, not treated as the end."""
        make_image(tmp_path / "images" / "a.jpg")
        found = _find_image_by_stem("a", [tmp_path], subdirs=["gone", "images"])
        assert found == tmp_path / "images" / "a.jpg"

    def test_returns_none_when_nothing_matches(self, tmp_path: Path) -> None:
        """An absent stem yields None rather than raising."""
        assert _find_image_by_stem("a", [tmp_path], subdirs=["images"]) is None


class TestCsvRowBuilders:
    """Tests for the row dicts stamped on every YOLO-imported annotation."""

    def test_base_row_stamps_yolo_provenance(self) -> None:
        """The full row dict is pinned, constants included.

        Nothing asserted the provenance columns this function fills in, so
        every literal in it - ``task_name``, ``source``, the empty strings,
        even the ``img_size`` index - was free to change.
        """
        row = _make_csv_row_base(
            "none", "img.jpg", (640, 480), split="train", frame_id=7
        )
        expected: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
        expected.update(
            image_name="img.jpg",
            image_width=640,
            image_height=480,
            instance_shape="none",
            task_id=0,
            task_name="yolo",
            job_stage="",
            job_state="",
            task_updated_date="",
            created_by_username="",
            frame_id=7,
            split="train",
            subset="",
            source="yolo",
            attributes="{}",
        )
        assert row == expected

    def test_box_row_rounds_coordinates_to_two_decimals(self) -> None:
        """Box columns are pinned with coordinates that survive rounding.

        Coordinates with more than two decimals are what makes ``round(x, 3)``
        and a dropped precision argument distinguishable.
        """
        row = _make_csv_row_box(
            image_name="img.jpg",
            img_w=640,
            img_h=480,
            label="cat",
            x_tl=12.3456,
            y_tl=34.5678,
            x_br=56.7891,
            y_br=78.9123,
            split="val",
            frame_id=3,
            annotation_id=9,
            confidence=0.5,
        )
        expected: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
        expected.update(
            image_name="img.jpg",
            image_width=640,
            image_height=480,
            instance_shape="box",
            instance_label="cat",
            bbox_x_tl=12.35,
            bbox_y_tl=34.57,
            bbox_x_br=56.79,
            bbox_y_br=78.91,
            occluded=False,
            z_order=0,
            rotation=0.0,
            annotation_id=9,
            confidence=0.5,
            task_id=0,
            task_name="yolo",
            job_stage="",
            job_state="",
            task_updated_date="",
            created_by_username="",
            frame_id=3,
            split="val",
            subset="",
            source="yolo",
            attributes="{}",
        )
        assert row == expected


class TestWriteCsv:
    """Tests for the CSV writer shared by both from-YOLO modes."""

    def test_empty_rows_still_write_the_header(self, tmp_path: Path) -> None:
        """A run that produced no rows writes a headers-only CSV.

        Without the explicit ``columns`` the frame would have no columns at
        all and the file would be unreadable; nothing covered that path, nor
        an output path whose parent chain does not exist yet.
        """
        out = tmp_path / "a" / "b" / "out.csv"
        _write_csv([], out)
        df = pd.read_csv(out)
        assert list(df.columns) == list(CSV_COLUMNS)
        assert len(df) == 0

    def test_dataframe_index_is_not_written(self, tmp_path: Path) -> None:
        """No extra index column leaks into the CSV."""
        out = tmp_path / "out.csv"
        row = _make_csv_row_base("none", "a.jpg", (10, 20), split=None, frame_id=0)
        _write_csv([row], out)
        assert list(pd.read_csv(out).columns) == list(CSV_COLUMNS)


class TestValidateSplits:
    """Tests for the split-completeness guard."""

    def test_empty_string_split_is_rejected(self) -> None:
        """A literal empty split is as invalid as a missing one.

        ``pd.read_csv`` turns empty fields into NaN, so no CSV-driven test can
        reach the ``== ""`` half of the condition - only a direct call can.
        """
        df = pd.DataFrame(
            [
                {"image_name": "a.jpg", "split": ""},
                {"image_name": "b.jpg", "split": "train"},
            ]
        )
        with pytest.raises(
            Cveta2Error, match=r"у 1 изображений не задан split\. Примеры: a\.jpg"
        ):
            _validate_splits(df)


@pytest.mark.parametrize("export_format", ["yolo", "coco"])
def test_missing_split_error(tmp_path: Path, export_format: str) -> None:
    """--to-yolo and --to-coco both error when any image has no split."""
    rows = [csv_row("test.jpg", label="cat", split="train")]
    rows[0]["split"] = None
    csv_path = write_convert_csv(tmp_path, rows)

    export = convert_to_yolo if export_format == "yolo" else convert_to_coco
    with pytest.raises(Cveta2Error, match="не задан split"):
        export(csv_path, tmp_path / "out", image_dirs=[str(tmp_path)], link_mode="copy")


def test_run_convert_missing_split_exits(tmp_path: Path) -> None:
    """A conversion-logic error propagates to the CLI boundary."""
    rows = [csv_row("test.jpg", label="cat", split="train")]
    rows[0]["split"] = None
    csv_path = write_convert_csv(tmp_path, rows)

    args = parse_cli_args(
        "convert",
        "--to-yolo",
        "-d",
        str(csv_path),
        "-o",
        str(tmp_path / "yolo_out"),
        "--link-mode",
        "copy",
    )

    with pytest.raises(Cveta2Error, match="не задан split"):
        run_convert(args)
