"""Exit codes of the managed dataset CLI group."""

import json
import sys
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
from tests.helpers import parse_cli_args


def test_missing_shared_config_exits_two_with_path(tmp_path: Path, capture_logs: list[str]) -> None:
    missing = tmp_path / "absent.yaml"
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "show", "combined", "--global-config", str(missing)])
    assert exited.value.code == 2
    assert any(str(missing) in line for line in capture_logs)


@pytest.mark.parametrize(
    "error",
    [ManagedError("источник недоступен"), PermissionError(13, "Permission denied", "out"), NoCredentialsError()],
    ids=["managed-error", "os-error", "sdk-error"],
)
def test_operational_errors_exit_two(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    capture_logs: list[str],
    error: Exception,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        sys.stdout.write("SDK progress\n")
        raise error

    monkeypatch.setattr(managed_datasets, "fetch_dataset", fail)
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "fetch", "combined", "--output-dir", str(tmp_path / "out"), "--json"])
    assert exited.value.code == 2
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "SDK progress" in captured.err
    assert any(str(error) in line for line in capture_logs)


def test_unready_preparation_still_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    prepared = managed_datasets.PreparationSummary(directory=tmp_path / "prepared", ready=False, report={})
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
                "--json",
            ]
        )
    assert exited.value.code == 1
    assert json.loads(capsys.readouterr().out) == prepared.model_dump(mode="json")


@pytest.mark.parametrize(("flags", "clean"), [((), True), (("--no-clean",), False), (("--clean",), True)])
def test_prepare_cleans_by_default_and_no_clean_opts_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...], *, clean: bool
) -> None:
    calls: list[dict[str, object]] = []

    def prepare(*_args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(ready=True, model_dump=lambda **_kwargs: {"ready": True})

    monkeypatch.setattr(managed_datasets, "prepare_managed_dataset", prepare)
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
            *flags,
        ]
    )
    assert [call["clean"] for call in calls] == [clean]


def test_prepare_refuses_clean_together_with_no_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(managed_datasets, "prepare_managed_dataset", lambda *args, **_kwargs: calls.append(args))
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
                "--no-clean",
                "--clean",
            ]
        )
    assert exited.value.code == 2
    assert calls == []


def test_failed_feedback_report_still_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    report = managed_datasets.FeedbackOutcome(failed=["unreachable frame"])
    monkeypatch.setattr(managed_datasets, "report_dataset_errors", lambda *_args, **_kwargs: report)
    with pytest.raises(SystemExit) as exited:
        main(["dataset", "report-errors", str(tmp_path), "--json"])
    assert exited.value.code == 2
    assert json.loads(capsys.readouterr().out) == report.model_dump(mode="json")


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


@pytest.mark.parametrize(
    "operation",
    [
        ("list",),
        ("show", "combined"),
        ("versions", "combined"),
        ("fetch", "combined", "--output-dir", "out"),
        ("prepare", "combined", "in.csv", "--source", "src", "--output-dir", "out"),
        ("diff", "old", "new"),
        ("report-errors", "prepared"),
        ("publish", "prepared"),
    ],
    ids=lambda operation: operation[0],
)
def test_dataset_commands_accept_global_config(operation: tuple[str, ...]) -> None:
    args = parse_cli_args("dataset", *operation, "--global-config", "g.yaml")

    assert args.global_config == Path("g.yaml")


@pytest.mark.parametrize(("flags", "force_resplit"), [((), False), (("--force-resplit",), True)])
def test_publish_passes_force_resplit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...], *, force_resplit: bool
) -> None:
    calls: list[dict[str, object]] = []

    def publish(*_args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(dataset_id="version-1", version="1")

    monkeypatch.setattr(managed_datasets, "publish_dataset", publish)
    main(["dataset", "publish", str(tmp_path), *flags])
    assert [call["force_resplit"] for call in calls] == [force_resplit]
