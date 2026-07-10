"""Integration tests for ClearML dataset publishing.

Requires a running ClearML server (see scripts/integration_up.sh).
Gated by the CLEARML_API_HOST env var.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

CLEARML_API_HOST = os.environ.get("CLEARML_API_HOST", "")


def _skip_if_no_clearml_server() -> None:
    if not CLEARML_API_HOST:
        pytest.skip("CLEARML_API_HOST not set — skipping ClearML integration tests")
    try:
        import clearml  # noqa: F401
    except ImportError:
        pytest.skip("clearml package not installed")


def _unique_name(prefix: str = "test") -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _check_clearml() -> None:
    _skip_if_no_clearml_server()


class TestPublishToClearml:
    """Integration tests for ClearML dataset publishing."""

    def test_publish_creates_dataset(self, tmp_path: Path) -> None:
        """Create CSV files and publish them as a ClearML dataset."""
        from clearml import Dataset

        from cveta2._clearml._dataset import publish_to_clearml
        from cveta2.config import ClearmlProjectMapping

        (tmp_path / "dataset.csv").write_text(
            "image_name,label\nimg1.jpg,cat\n", encoding="utf-8"
        )
        (tmp_path / "obsolete.csv").write_text(
            "image_name,label\nimg2.jpg,dog\n", encoding="utf-8"
        )

        project_name = _unique_name("cveta2-test")
        dataset_name = _unique_name("ds")

        mapping = ClearmlProjectMapping(
            clearml_project=project_name,
            clearml_dataset=dataset_name,
        )

        publish_to_clearml(mapping, tmp_path)

        ds = Dataset.get(
            dataset_project=project_name,
            dataset_name=dataset_name,
        )
        assert ds is not None
        assert ds.id

    def test_publish_includes_all_csv_files(self, tmp_path: Path) -> None:
        """Verify the published dataset contains all CSV files."""
        from clearml import Dataset

        from cveta2._clearml._dataset import publish_to_clearml
        from cveta2.config import ClearmlProjectMapping

        csv_names = [
            "dataset.csv",
            "obsolete.csv",
            "in_progress.csv",
            "deleted.csv",
        ]
        for name in csv_names:
            (tmp_path / name).write_text(f"col\n{name}\n", encoding="utf-8")

        project_name = _unique_name("cveta2-test")
        dataset_name = _unique_name("ds")

        mapping = ClearmlProjectMapping(
            clearml_project=project_name,
            clearml_dataset=dataset_name,
        )

        publish_to_clearml(mapping, tmp_path)

        ds = Dataset.get(
            dataset_project=project_name,
            dataset_name=dataset_name,
        )
        file_entries = ds.list_files()
        basenames = {Path(f).name for f in file_entries}
        for name in csv_names:
            assert name in basenames, f"{name} not found in dataset files: {basenames}"


class TestMaybePublishSkipPaths:
    """Integration tests for skip paths in maybe_publish_clearml."""

    def test_clearml_disabled_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify no dataset is created when CVETA2_CLEARML=false."""
        from clearml import Dataset

        from cveta2._clearml import maybe_publish_clearml
        from cveta2.config import (
            ClearmlConfig,
            ClearmlProjectMapping,
        )

        (tmp_path / "dataset.csv").write_text("col\nval\n", encoding="utf-8")

        project_name = _unique_name("cveta2-skip")
        dataset_name = _unique_name("ds-skip")
        config_path = tmp_path / "config.yaml"

        cfg = ClearmlConfig(
            enabled=True,
            projects={
                project_name: ClearmlProjectMapping(
                    clearml_project=project_name,
                    clearml_dataset=dataset_name,
                )
            },
        )
        cfg.save(config_path)
        monkeypatch.setenv("CVETA2_CONFIG", str(config_path))
        monkeypatch.setenv("CVETA2_CLEARML", "false")

        maybe_publish_clearml(project_name, tmp_path)

        with pytest.raises(ValueError, match="Could not find"):
            Dataset.get(
                dataset_project=project_name,
                dataset_name=dataset_name,
            )

    def test_no_mapping_skips(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify no dataset is created when project has no mapping."""
        from cveta2._clearml import maybe_publish_clearml
        from cveta2.config import ClearmlConfig

        (tmp_path / "dataset.csv").write_text("col\nval\n", encoding="utf-8")
        config_path = tmp_path / "config.yaml"

        cfg = ClearmlConfig(enabled=True, projects={})
        cfg.save(config_path)
        monkeypatch.setenv("CVETA2_CONFIG", str(config_path))
        monkeypatch.delenv("CVETA2_CLEARML", raising=False)

        maybe_publish_clearml("unmapped-project", tmp_path)
