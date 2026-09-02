"""Unit tests for cveta2._clearml (mocked — no real ClearML needed)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from cveta2.config import ClearmlConfig, ClearmlProjectMapping
from cveta2.exceptions import ClearmlPublishError

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestPublishToClearml:
    """Tests for publish_to_clearml with mocked ClearML SDK."""

    def test_publish_calls_sdk(self, tmp_path: Path) -> None:
        (tmp_path / "dataset.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (tmp_path / "obsolete.csv").write_text("a,b\n3,4\n", encoding="utf-8")

        mock_dataset_instance = MagicMock()
        mock_dataset_instance.id = "test-dataset-id"
        mock_dataset_cls = MagicMock()
        mock_dataset_cls.create.return_value = mock_dataset_instance

        mock_clearml = MagicMock()
        mock_clearml.Dataset = mock_dataset_cls

        with patch.dict("sys.modules", {"clearml": mock_clearml}):
            from cveta2._clearml._dataset import publish_to_clearml

            mapping = ClearmlProjectMapping(
                clearml_project="team/ds", clearml_dataset="annot"
            )
            publish_to_clearml(mapping, tmp_path)

        mock_dataset_cls.create.assert_called_once_with(
            dataset_project="team/ds",
            dataset_name="annot",
        )
        assert mock_dataset_instance.add_files.call_count == 2
        mock_dataset_instance.upload.assert_called_once()
        mock_dataset_instance.finalize.assert_called_once()

    def test_no_csv_files_skips(self, tmp_path: Path) -> None:
        mock_dataset_cls = MagicMock()
        mock_clearml = MagicMock()
        mock_clearml.Dataset = mock_dataset_cls

        with patch.dict("sys.modules", {"clearml": mock_clearml}):
            from cveta2._clearml._dataset import publish_to_clearml

            mapping = ClearmlProjectMapping(clearml_project="p", clearml_dataset="d")
            publish_to_clearml(mapping, tmp_path)

        mock_dataset_cls.create.assert_not_called()


_MAPPED_CONFIG = ClearmlConfig(
    enabled=True,
    projects={"proj": ClearmlProjectMapping(clearml_project="p", clearml_dataset="d")},
)
"""A config that passes every guard, so a test can disable exactly one."""


class TestMaybePublishClearml:
    """Tests for maybe_publish_clearml skip paths."""

    def test_disabled_env_var(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CVETA2_CLEARML", "false")
        mock_publish = MagicMock()

        with patch("cveta2._clearml._dataset.publish_to_clearml", mock_publish):
            from cveta2._clearml import maybe_publish_clearml

            maybe_publish_clearml("proj", tmp_path)

        mock_publish.assert_not_called()

    def test_not_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every later guard is permissive, so only this one can do the skipping."""
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)
        mock_publish = MagicMock()

        with (
            patch("cveta2._clearml.is_clearml_available", return_value=False),
            patch("cveta2.config.ClearmlConfig.load", return_value=_MAPPED_CONFIG),
            patch("cveta2._clearml._dataset.publish_to_clearml", mock_publish),
        ):
            from cveta2._clearml import maybe_publish_clearml

            maybe_publish_clearml("proj", tmp_path)

        mock_publish.assert_not_called()

    def test_config_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`enabled=False` must win even though a mapping for the project exists."""
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)
        cfg = ClearmlConfig(enabled=False, projects=_MAPPED_CONFIG.projects)
        mock_publish = MagicMock()

        with (
            patch("cveta2._clearml.is_clearml_available", return_value=True),
            patch("cveta2.config.ClearmlConfig.load", return_value=cfg),
            patch("cveta2._clearml._dataset.publish_to_clearml", mock_publish),
        ):
            from cveta2._clearml import maybe_publish_clearml

            maybe_publish_clearml("proj", tmp_path)

        mock_publish.assert_not_called()

    def test_no_mapping(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)
        mock_publish = MagicMock()

        with (
            patch("cveta2._clearml.is_clearml_available", return_value=True),
            patch("cveta2.config.ClearmlConfig.load", return_value=_MAPPED_CONFIG),
            patch("cveta2._clearml._dataset.publish_to_clearml", mock_publish),
        ):
            from cveta2._clearml import maybe_publish_clearml

            maybe_publish_clearml("unmapped-project", tmp_path)

        mock_publish.assert_not_called()

    def test_config_path_reaches_the_config_loader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit config file is what the ``clearml`` section is read from."""
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)
        config_path = tmp_path / "team.yaml"

        with (
            patch("cveta2._clearml.is_clearml_available", return_value=True),
            patch(
                "cveta2.config.ClearmlConfig.load", return_value=_MAPPED_CONFIG
            ) as load,
            patch("cveta2._clearml._dataset.publish_to_clearml") as mock_publish,
        ):
            from cveta2._clearml import maybe_publish_clearml

            maybe_publish_clearml("proj", tmp_path, config_path)

        load.assert_called_once_with(config_path)
        mock_publish.assert_called_once_with(_MAPPED_CONFIG.projects["proj"], tmp_path)

    def test_exception_caught_and_logged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capture_logs: list[str],
    ) -> None:
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)

        with (
            patch("cveta2._clearml.is_clearml_available", return_value=True),
            patch("cveta2.config.ClearmlConfig.load", return_value=_MAPPED_CONFIG),
            patch(
                "cveta2._clearml._dataset.publish_to_clearml",
                side_effect=ClearmlPublishError("ClearML server unreachable"),
            ),
        ):
            from cveta2._clearml import maybe_publish_clearml

            # Should not raise — exception is caught
            maybe_publish_clearml("proj", tmp_path)

        assert capture_logs, "a swallowed publish failure must still be reported"
