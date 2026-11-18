"""Exit codes of the managed dataset CLI group."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from botocore.exceptions import (
    NoCredentialsError,
    NoRegionError,
    PartialCredentialsError,
    ProfileNotFound,
    UnauthorizedSSOTokenError,
)

from cveta2.adapters.s3.managed_sources import S3CsvSources
from cveta2.domain.managed.models import ManagedError
from cveta2.interfaces import managed_datasets
from cveta2.interfaces.cli import main


def test_missing_shared_config_exits_two_with_path(tmp_path: Path, capture_logs: list[str]) -> None:
    missing = tmp_path / "absent.yaml"
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "show", "combined", "--project-config", str(missing)])
    assert exited.value.code == 2
    assert any(str(missing) in line for line in capture_logs)


@pytest.mark.parametrize(
    "error",
    [ManagedError("источник недоступен"), PermissionError(13, "Permission denied", "out")],
    ids=["managed-error", "os-error"],
)
def test_operational_errors_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capture_logs: list[str], error: Exception
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(managed_datasets, "fetch_dataset", fail)
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "fetch", "combined", "--output-dir", str(tmp_path / "out")])
    assert exited.value.code == 2
    assert any(str(error) in line for line in capture_logs)


def test_unready_preparation_still_exits_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prepared = SimpleNamespace(ready=False, model_dump=lambda **_kwargs: {"ready": False})
    monkeypatch.setattr(managed_datasets, "prepare_managed_dataset", lambda *_args, **_kwargs: prepared)
    with pytest.raises(SystemExit) as exited:
        main(
            [
                "dataset",
                "prepare",
                "combined",
                str(tmp_path / "in.csv"),
                "--source",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "prepared"),
            ]
        )
    assert exited.value.code == 1


def test_failed_feedback_report_still_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = SimpleNamespace(model_dump=lambda **_kwargs: {"failed": 1})
    monkeypatch.setattr(managed_datasets, "report_dataset_errors", lambda *_args, **_kwargs: report)
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "report-errors", str(tmp_path)])
    assert exited.value.code == 2


@pytest.mark.parametrize(
    "error",
    [
        NoCredentialsError(),
        ProfileNotFound(profile="absent"),
        PartialCredentialsError(provider="env", cred_var="AWS_SECRET_ACCESS_KEY"),
        NoRegionError(),
        UnauthorizedSSOTokenError(),
    ],
    ids=["no-credentials", "unknown-profile", "partial-credentials", "no-region", "sso-token"],
)
def test_s3_credential_failures_exit_two_naming_the_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_logs: list[str],
    error: Exception,
) -> None:
    uri = "s3://csv-bucket/exports/annotations.csv"

    class _NoCredentials:
        def get_object(self, **_kwargs: object) -> object:
            raise error

    def fetch(*_args: object, **_kwargs: object) -> object:
        return S3CsvSources(client=_NoCredentials()).read_object(uri)  # type: ignore[arg-type]

    monkeypatch.setattr(managed_datasets, "fetch_dataset", fetch)
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "fetch", "combined", "--output-dir", str(tmp_path / "out")])
    assert exited.value.code == 2
    assert any(uri in line for line in capture_logs)
    assert exited.value.__cause__ is not None
    assert exited.value.__cause__.__cause__ is error
    assert not any("Traceback" in line for line in capture_logs)
