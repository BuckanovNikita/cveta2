"""Integration tests for ClearML dataset publishing on the shared stand.

The stand, the identity and the run tag come from ``scripts/integration_test.sh``
(``INTEGRATION_RUN_TAG`` and the ``CLEARML_*`` exports of the cveta2 Secret);
every project the tests create is named ``"<tag> <what>"`` and the session
teardown removes them all. Nothing here skips: a missing variable or SDK is a
failure, the same way a stand that does not answer is.

Every ``clearml`` import stays inside a fixture or a test: importing the
package logs in to the configured server, which collection must never do.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from loguru import logger

from tests.integration.clearml_run import (
    RunError,
    RunSettings,
    delete_run_projects,
    open_session,
    project_name,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

PUBLISH = "clearml-publish"
SKIP_PATHS = "clearml-skip"


def _unique_dataset_name() -> str:
    return f"ds-{uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def clearml_run() -> Iterator[RunSettings]:
    """Provide the run's tag and stand; on teardown its ``"<tag> ..."`` projects go."""
    try:
        settings = RunSettings.from_env()
    except RunError as exc:
        pytest.fail(str(exc))
    try:
        import clearml  # noqa: F401
    except ImportError:
        pytest.fail(
            "the clearml SDK is not installed: it is the `clearml` extra, which "
            "scripts/integration_test.sh adds (uv run --extra clearml); "
            "for a bare pytest run `uv sync --extra clearml` first"
        )
    yield settings
    deleted = delete_run_projects(open_session(), settings.tag)
    logger.info(
        f"removed {len(deleted)} ClearML project(s) of run {settings.tag!r} "
        f"from {settings.api_host}: {', '.join(deleted) or 'none were left'}"
    )


class TestPublishToClearml:
    """Integration tests for ClearML dataset publishing."""

    def test_publish_creates_dataset(
        self, tmp_path: Path, clearml_run: RunSettings
    ) -> None:
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

        project = project_name(clearml_run.tag, PUBLISH)
        dataset_name = _unique_dataset_name()

        mapping = ClearmlProjectMapping(
            clearml_project=project,
            clearml_dataset=dataset_name,
        )

        publish_to_clearml(mapping, tmp_path)

        ds = Dataset.get(
            dataset_project=project,
            dataset_name=dataset_name,
        )
        assert ds is not None
        assert ds.id

    def test_publish_includes_all_csv_files(
        self, tmp_path: Path, clearml_run: RunSettings
    ) -> None:
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

        project = project_name(clearml_run.tag, PUBLISH)
        dataset_name = _unique_dataset_name()

        mapping = ClearmlProjectMapping(
            clearml_project=project,
            clearml_dataset=dataset_name,
        )

        publish_to_clearml(mapping, tmp_path)

        ds = Dataset.get(
            dataset_project=project,
            dataset_name=dataset_name,
        )
        file_entries = ds.list_files()
        basenames = {Path(f).name for f in file_entries}
        for name in csv_names:
            assert name in basenames, f"{name} not found in dataset files: {basenames}"


class TestMaybePublishSkipPaths:
    """Integration tests for skip paths in maybe_publish_clearml."""

    def test_clearml_disabled_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clearml_run: RunSettings,
    ) -> None:
        """Verify no dataset is created when CVETA2_CLEARML=false."""
        from clearml import Dataset

        from cveta2._clearml import maybe_publish_clearml
        from cveta2.config import (
            ClearmlConfig,
            ClearmlProjectMapping,
        )

        (tmp_path / "dataset.csv").write_text("col\nval\n", encoding="utf-8")

        project = project_name(clearml_run.tag, SKIP_PATHS)
        dataset_name = _unique_dataset_name()
        config_path = tmp_path / "config.yaml"

        cfg = ClearmlConfig(
            enabled=True,
            projects={
                project: ClearmlProjectMapping(
                    clearml_project=project,
                    clearml_dataset=dataset_name,
                )
            },
        )
        cfg.save(config_path)
        monkeypatch.setenv("CVETA2_CONFIG", str(config_path))
        monkeypatch.setenv("CVETA2_CLEARML", "false")

        maybe_publish_clearml(project, tmp_path)

        with pytest.raises(ValueError, match="Could not find"):
            Dataset.get(
                dataset_project=project,
                dataset_name=dataset_name,
            )

    def test_no_mapping_skips(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clearml_run: RunSettings,
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

        maybe_publish_clearml(project_name(clearml_run.tag, "unmapped"), tmp_path)
