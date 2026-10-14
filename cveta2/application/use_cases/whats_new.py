"""Baseline orchestration with optional sibling persistence supplied explicitly."""

from pathlib import Path

import pandas as pd

from cveta2.application.ports.dataset import DatasetFiles
from cveta2.domain.baseline import WhatsNewBaseline
from cveta2.domain.baseline import compute_baseline as baseline_from_frames


def compute_baseline(
    df: pd.DataFrame, path: Path, *, files: DatasetFiles
) -> WhatsNewBaseline:
    """Build the baseline including completed tasks from optional sibling CSVs."""
    return baseline_from_frames(df, path, files.read_baseline_siblings(path))
