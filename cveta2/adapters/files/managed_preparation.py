"""Capture and checksum reviewed managed inputs without publishing mutable files."""

import hashlib
import json
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from pydantic import JsonValue, TypeAdapter, ValidationError

from cveta2.adapters.files.bundle import _payload, _yaml
from cveta2.adapters.files.bundle_paths import LocalRoots
from cveta2.adapters.files.verification import read_csv_bytes, report_dict
from cveta2.application.ports.managed_preparation import (
    CapturedManagedInput,
    ImageHashes,
    LoadedManagedPreparation,
)
from cveta2.domain.bundle.models import (
    BundleValidation,
    DatasetMetadata,
    FetchTables,
    TaskManifest,
)
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot, SourceSnapshot
from cveta2.domain.managed.preparation import FeedbackFinding, ManagedRecord

_PAYLOAD = ("dataset.csv", "dataset.yaml", "tasks.yaml")
_TABLES = ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv")
_REPORT = TypeAdapter(dict[str, JsonValue])


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ManagedError(f"Expected a regular nonsymlink file: {path}")
    return path.read_bytes()


def _parse_snapshot(content: bytes) -> ManagedSnapshot:
    return ManagedSnapshot.model_validate(_yaml(content, "source-snapshot.yaml"))


def _tables(source: SourceSnapshot) -> FetchTables:
    if set(source.tables) != set(_TABLES):
        raise ManagedError(f"Incomplete four-table snapshot for source: {source.name}")
    frames = [
        read_csv_bytes(
            source.tables[name].encode("utf-8"), source=f"{source.name}/{name}"
        )
        for name in _TABLES
    ]
    return FetchTables(*frames)


def _integer(value: object) -> int | None:
    try:
        number = Decimal(str(value))
        return (
            int(number)
            if number.is_finite()
            and number >= 0
            and number == number.to_integral_value()
            else None
        )
    except InvalidOperation:
        return None


def _origins(snapshot: ManagedSnapshot) -> frozenset[tuple[str, int, int, int]]:
    origins = set()
    for source in snapshot.sources:
        if source.type != "cvat" or source.project_id is None:
            continue
        for key, task in source.tasks.items():
            if str(task.id) != key or set(task.tables) != set(_TABLES):
                raise ManagedError(
                    f"Invalid per-task evidence in source: {source.name}"
                )
            for name, content in task.tables.items():
                table = read_csv_bytes(
                    content.encode("utf-8"), source=f"{source.name}/{key}/{name}"
                )
                for row in table.to_dict(orient="records"):
                    if _integer(row.get("task_id")) != task.id:
                        raise ManagedError(
                            f"Source task identity mismatch: {source.name}/{key}"
                        )
                    if (frame := _integer(row.get("frame_id"))) is not None:
                        origins.add((source.name, source.project_id, task.id, frame))
    return frozenset(origins)


class LocalManagedPreparationFiles:
    """Own all filesystem, CSV and YAML effects for managed preparation."""

    def capture(self, transformed: Path, source: Path) -> CapturedManagedInput:
        """Read exact bytes once and independently attest original task frames."""
        source_path = source / "source-snapshot.yaml" if source.is_dir() else source
        try:
            if source.is_symlink():
                raise ManagedError(f"Source directory must not be a symlink: {source}")
            input_content, source_content = (
                _regular_bytes(transformed),
                _regular_bytes(source_path),
            )
            snapshot = _parse_snapshot(source_content)
            tables = {item.name: _tables(item) for item in snapshot.sources}
            if len(tables) != len(snapshot.sources):
                raise ManagedError("Source snapshot names must be unique")
            return CapturedManagedInput(
                frame=read_csv_bytes(input_content, source=str(transformed)),
                input_content=input_content,
                source_content=source_content,
                snapshot=snapshot,
                source_tables=tables,
                origins=_origins(snapshot),
            )
        except (OSError, ValidationError) as error:
            raise ManagedError(
                f"Cannot capture managed preparation inputs: {error}"
            ) from error

    def image_hashes(self, frame: pd.DataFrame) -> ImageHashes:
        """Hash each readable path once while letting media validation report errors."""
        identities: dict[str, str] = {}
        readable: dict[str, str] = {}
        for value in frame.get("image_path", []):
            if not isinstance(value, str) or not value or value in identities:
                continue
            try:
                digest = hashlib.sha256(Path(value).read_bytes()).hexdigest()
                readable[value] = digest
            except (OSError, ValueError):
                digest = (
                    "unreadable:" + hashlib.sha256(value.encode("utf-8")).hexdigest()
                )
            identities[value] = digest
        return ImageHashes(identities, readable)

    def check_roots(self, frame: pd.DataFrame, metadata: DatasetMetadata) -> None:
        """Require approved local and S3 coverage before cleanup removes any rows."""
        roots = LocalRoots()
        if uncovered := roots.uncovered_paths(frame, metadata.images):
            raise ManagedError(
                f"Transformed images are outside approved roots: {uncovered}"
            )
        roots.check_s3_paths(frame, metadata.images)

    def payload_bytes(
        self, frame: pd.DataFrame, metadata: DatasetMetadata, tasks: TaskManifest
    ) -> dict[str, bytes]:
        """Use the same deterministic three-file serialization as legacy bundles."""
        return _payload(frame, metadata, tasks)

    def validation_report(
        self,
        validation: BundleValidation,
        *,
        ready: bool,
        findings: list[FeedbackFinding],
        unmapped: int,
        split_replacements: int,
    ) -> dict[str, JsonValue]:
        """Serialize report tuples as JSON arrays and retain original diagnostics."""
        report = report_dict(validation.result)
        report.pop("metadata_columns", None)
        report.update(
            ready=ready,
            blockers=list(validation.blockers),
            broken_image_rows=len(validation.broken_images),
            mapped_findings=len(findings),
            unmapped_errors=unmapped,
            split_replacements=split_replacements,
        )
        return _REPORT.validate_json(json.dumps(report))

    def persist(  # noqa: PLR0913, PLR0917 - immutable persistence boundary.
        self,
        directory: Path,
        captured: CapturedManagedInput,
        record: ManagedRecord,
        payload: Mapping[str, bytes],
        report: dict[str, JsonValue],
        broken_images: pd.DataFrame,
    ) -> None:
        """Create a new preparation with the record completion marker written last."""
        if directory.exists() or directory.is_symlink():
            raise ManagedError(f"Preparation directory already exists: {directory}")
        try:
            directory.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(
                prefix=".cveta2-managed-", dir=directory.parent
            ) as temporary:
                staged = Path(temporary)
                (staged / "transformed.csv").write_bytes(captured.input_content)
                (staged / "source-snapshot.yaml").write_bytes(captured.source_content)
                (staged / "report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                broken_images.to_csv(
                    staged / "broken-images.csv", index=False, lineterminator="\n"
                )
                for name, content in payload.items():
                    if name not in _PAYLOAD:
                        raise ManagedError(f"Unexpected managed payload file: {name}")
                    (staged / name).write_bytes(content)
                record_bytes = (record.model_dump_json(indent=2) + "\n").encode("utf-8")
                (staged / "preparation.json").write_bytes(record_bytes)
                (staged / "preparation.sha256").write_text(
                    hashlib.sha256(record_bytes).hexdigest() + "\n", encoding="ascii"
                )
                directory.mkdir(exist_ok=False)
                for name in (
                    "transformed.csv",
                    "source-snapshot.yaml",
                    "report.json",
                    "broken-images.csv",
                    *_PAYLOAD,
                    "preparation.json",
                    "preparation.sha256",
                ):
                    if (staged / name).is_file():
                        os.link(staged / name, directory / name)
        except OSError as error:
            raise ManagedError(
                f"Cannot persist managed preparation: {directory}"
            ) from error

    def load_prepared(self, directory: Path) -> LoadedManagedPreparation:
        """Reject edited records, inputs or payload and hold stable captured bytes."""
        try:
            if directory.is_symlink() or not directory.is_dir():
                raise ManagedError(
                    f"Expected a nonsymlink preparation directory: {directory}"
                )
            record_bytes = _regular_bytes(directory / "preparation.json")
            if (
                hashlib.sha256(record_bytes).hexdigest().encode("ascii")
                != _regular_bytes(directory / "preparation.sha256").strip()
            ):
                raise ManagedError(
                    "Managed preparation record checksum mismatch; prepare again"
                )
            record = ManagedRecord.model_validate_json(record_bytes)
            input_content = _regular_bytes(directory / "transformed.csv")
            source_content = _regular_bytes(directory / "source-snapshot.yaml")
            if (
                hashlib.sha256(input_content).hexdigest() != record.input_hash
                or hashlib.sha256(source_content).hexdigest() != record.source_hash
            ):
                raise ManagedError(
                    "Managed input or source snapshot changed; prepare again"
                )
            source_snapshot = _parse_snapshot(source_content)
            expected_snapshot = source_snapshot.model_copy(
                update={
                    "assignments": record.snapshot.assignments,
                    "image_hashes": record.snapshot.image_hashes,
                }
            )
            if (
                expected_snapshot != record.snapshot
                or record.definition_hash != source_snapshot.definition_hash
                or record.registry_hash != source_snapshot.registry_hash
                or record.parent_id != source_snapshot.parent_id
            ):
                raise ManagedError(
                    "Managed source binding is inconsistent; prepare again"
                )
            payload = _read_payload(directory, record)
            metadata, tasks, frame = _parse_payload(payload)
            if tasks is not None and tasks.managed != record.snapshot:
                raise ManagedError("Managed task snapshot changed; prepare again")
            if metadata is not None and (
                metadata.managed is None
                or metadata.managed.definition_hash != record.definition_hash
            ):
                raise ManagedError("Managed metadata binding changed; prepare again")
            report = _REPORT.validate_json(_regular_bytes(directory / "report.json"))
            return LoadedManagedPreparation(
                directory=directory,
                record=record,
                frame=frame,
                metadata=metadata,
                tasks=tasks,
                payload=payload,
                input_content=input_content,
                source_content=source_content,
                report=report,
            )
        except (OSError, ValidationError) as error:
            raise ManagedError(
                f"Cannot load managed preparation: {directory}: {error}"
            ) from error

    @contextmanager
    def stage_payload(self, payload: Mapping[str, bytes]) -> Iterator[Path]:
        """Publish private captured bytes rather than rereading mutable local files."""
        if set(payload) != set(_PAYLOAD):
            raise ManagedError(
                "Managed publication requires exactly three payload files"
            )
        with TemporaryDirectory(prefix="cveta2-managed-publish-") as temporary:
            directory = Path(temporary)
            for name, content in payload.items():
                (directory / name).write_bytes(content)
            yield directory


def _read_payload(directory: Path, record: ManagedRecord) -> dict[str, bytes]:
    expected = set(_PAYLOAD) if record.ready else set()
    if set(record.payload_hashes) != expected:
        raise ManagedError("Invalid managed payload inventory; prepare again")
    payload = {name: _regular_bytes(directory / name) for name in record.payload_hashes}
    if {
        name: hashlib.sha256(content).hexdigest() for name, content in payload.items()
    } != record.payload_hashes:
        raise ManagedError("Managed payload checksum mismatch; prepare again")
    return payload


def _parse_payload(
    payload: Mapping[str, bytes],
) -> tuple[DatasetMetadata | None, TaskManifest | None, pd.DataFrame]:
    if not payload:
        return None, None, pd.DataFrame()
    metadata = DatasetMetadata.model_validate(
        _yaml(payload["dataset.yaml"], "dataset.yaml")
    )
    tasks = TaskManifest.model_validate(_yaml(payload["tasks.yaml"], "tasks.yaml"))
    frame = read_csv_bytes(payload["dataset.csv"], source="dataset.csv")
    return metadata, tasks, frame
