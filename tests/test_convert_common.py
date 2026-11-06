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
from hypothesis import given
from hypothesis import strategies as st

from cveta2.adapters.files import materialization as convert
from cveta2.adapters.files.conversion import (
    LocalConversionFiles,
    _find_image_by_stem,
    _write_csv,
)
from cveta2.adapters.files.dataset import read_text_utf8, write_text_utf8
from cveta2.adapters.files.materialization import _link_or_copy
from cveta2.application.use_cases.convert.common import _SizeCache
from cveta2.composition.conversion import (
    _build_search_dirs,
)
from cveta2.domain.conversion import (
    CocoBox,
    PixelBox,
    YoloBox,
    _make_csv_row_base,
    _make_csv_row_box,
    _pixel_to_coco,
    _pixel_to_yolo,
    _require_positive_dimensions,
    _validate_splits,
    _yolo_to_pixel,
)
from cveta2.domain.errors import Cveta2Error
from cveta2.domain.models import CSV_COLUMNS
from cveta2.interfaces.commands.convert import run_convert
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

    @given(
        coords=st.lists(st.integers(0, 4000), min_size=4, max_size=4),
        size=st.tuples(st.integers(1, 4000), st.integers(1, 4000)),
    )
    def test_pixel_yolo_roundtrip(
        self, coords: list[int], size: tuple[int, int]
    ) -> None:
        """Pixel -> YOLO -> pixel recovers any box on any positive image size."""
        x1, x2 = sorted(coords[:2])
        y1, y2 = sorted(coords[2:])
        original = PixelBox(x1 / 4, y1 / 4, x2 / 4, y2 / 4)
        recovered = _yolo_to_pixel(_pixel_to_yolo(original, *size), *size)
        assert recovered == pytest.approx(original, abs=1e-6)

    @given(width=st.integers(-5, 5), height=st.integers(-5, 5))
    def test_dimensions_must_be_positive(self, width: int, height: int) -> None:
        """Any zero or negative side is rejected; 1-pixel sides are valid."""
        if width > 0 and height > 0:
            _require_positive_dimensions(width, height, "ok.jpg")
        else:
            with pytest.raises(Cveta2Error, match="некорректный размер"):
                _require_positive_dimensions(width, height, "bad.jpg")


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
        assert dst.read_text() == "new"  # refreshed from the current source


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

    @pytest.mark.parametrize(
        ("read_all", "second"), [(False, (640, 480)), (True, (320, 240))]
    )
    def test_read_all_controls_measurement(
        self,
        tmp_path: Path,
        read_all: bool,  # noqa: FBT001 - parametrized flag
        second: tuple[int, int],
    ) -> None:
        """Without read_all every call returns the first image's size."""
        img1 = make_image(tmp_path / "a.jpg", 640, 480)
        img2 = make_image(tmp_path / "b.jpg", 320, 240)

        cache = _SizeCache(read_all=read_all, files=LocalConversionFiles())
        assert cache.get(img1) == (640, 480)
        assert cache.get(img2) == second


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

    @pytest.mark.parametrize(
        ("cache", "explicit_names", "expected"),
        [
            pytest.param(["c1", "c2"], ["given"], ["given", "c1", "c2"], id="append"),
            pytest.param(["shared"], ["shared"], ["shared"], id="dedupe"),
            pytest.param(["c1"], None, ["c1"], id="cache-only"),
        ],
    )
    def test_cache_dirs_follow_the_explicit_ones(
        self,
        tmp_path: Path,
        isolated_config_path: Path,
        cache: list[str],
        explicit_names: list[str] | None,
        expected: list[str],
    ) -> None:
        """Configured cache dirs are appended after --image-dir, without repeats."""
        self._write_image_cache(
            isolated_config_path,
            {f"p{i}": tmp_path / name for i, name in enumerate(cache)},
        )
        explicit = (
            None
            if explicit_names is None
            else [tmp_path / name for name in explicit_names]
        )
        assert _build_search_dirs(explicit) == [tmp_path / name for name in expected]


class TestFindImageByStem:
    """Tests for the search order of ``_find_image_by_stem``."""

    @pytest.mark.parametrize(
        ("images", "dirs", "subdirs", "expected"),
        [
            pytest.param(
                ["a.jpg", "images/a.jpg"], ["."], ["images"], "a.jpg", id="flat-first"
            ),
            pytest.param(["a.png", "a.jpg"], ["."], [], "a.jpg", id="extension-order"),
            pytest.param(
                ["first/a.jpg", "second/a.jpg"],
                ["first", "second"],
                [],
                "first/a.jpg",
                id="dir-order",
            ),
            pytest.param(
                ["real/a.jpg"], ["gone", "real"], [], "real/a.jpg", id="missing-dir"
            ),
            pytest.param(
                ["images/a.png"], ["."], ["images"], "images/a.png", id="subdir"
            ),
            pytest.param(
                ["images/a.jpg"],
                ["."],
                ["gone", "images"],
                "images/a.jpg",
                id="missing-subdir",
            ),
            pytest.param([], ["."], ["images"], None, id="no-match"),
        ],
    )
    def test_search_order(
        self,
        tmp_path: Path,
        images: list[str],
        dirs: list[str],
        subdirs: list[str],
        expected: str | None,
    ) -> None:
        """Flat hits, then subdirs; earlier dirs and extensions win; gaps skip."""
        for image in images:
            make_image(tmp_path / image)
        found = _find_image_by_stem(
            "a", [tmp_path / d for d in dirs], subdirs=subdirs or None
        )
        assert found == (None if expected is None else tmp_path / expected)


def _yolo_row(shape: str, *, split: str, frame_id: int) -> dict[str, object]:
    """Return the full expected row with YOLO provenance constants."""
    expected: dict[str, object] = dict.fromkeys(CSV_COLUMNS, None)
    expected.update(
        image_name="img.jpg",
        image_width=640,
        image_height=480,
        instance_shape=shape,
        task_id=0,
        task_name="yolo",
        job_stage="",
        job_state="",
        task_updated_date="",
        created_by_username="",
        frame_id=frame_id,
        split=split,
        subset="",
        source="yolo",
        attributes="{}",
    )
    return expected


class TestCsvRowBuilders:
    """Tests for the row dicts stamped on every YOLO-imported annotation."""

    def test_base_row_stamps_yolo_provenance(self) -> None:
        """The full row dict is pinned, constants included."""
        row = _make_csv_row_base(
            "none", "img.jpg", (640, 480), split="train", frame_id=7
        )
        assert row == _yolo_row("none", split="train", frame_id=7)

    def test_box_row_rounds_coordinates_to_two_decimals(self) -> None:
        """Coordinates with more than two decimals pin the rounding precision."""
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
        assert row == {
            **_yolo_row("box", split="val", frame_id=3),
            "instance_label": "cat",
            "bbox_x_tl": 12.35,
            "bbox_y_tl": 34.57,
            "bbox_x_br": 56.79,
            "bbox_y_br": 78.91,
            "occluded": False,
            "z_order": 0,
            "rotation": 0.0,
            "annotation_id": 9,
            "confidence": 0.5,
        }


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
