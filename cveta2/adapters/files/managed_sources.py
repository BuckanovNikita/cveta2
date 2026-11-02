"""Strict CSV/source snapshot parsing and fresh candidate export."""

import hashlib
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yaml
from pydantic import ValidationError

from cveta2.adapters.files.bundle import _yaml
from cveta2.adapters.files.verification import read_csv_bytes
from cveta2.domain.managed.models import (
    ManagedError,
    ManagedSnapshot,
    SourceSnapshot,
    TaskSnapshot,
)
from cveta2.domain.models import CSV_COLUMNS, DeletedImage
from cveta2.domain.partition import partition_annotations_df

TABLE_NAMES = ("dataset.csv", "obsolete.csv", "in_progress.csv", "deleted.csv")
PROVENANCE_COLUMNS = (
    "source_id",
    "source_project_id",
    "source_task_id",
    "source_frame_id",
    "source_row_id",
)
ANNOTATION_COLUMNS = (
    "image_name",
    "image_path",
    "instance_label",
    "bbox_x_tl",
    "bbox_y_tl",
    "bbox_x_br",
    "bbox_y_br",
)


def _csv(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n")


def _table(text: str, source: str) -> pd.DataFrame:
    return read_csv_bytes(text.encode("utf-8"), source=source)


def _integer(value: object, column: str) -> int:
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise ManagedError(
            f"Invalid {column} in CVAT source evidence: {value!r}"
        ) from error
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 0:
        raise ManagedError(f"Invalid {column} in CVAT source evidence: {value!r}")
    return int(parsed)


def _typed_rows(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy(deep=True)
    if "task_id" in result:
        result["task_id"] = result["task_id"].map(
            lambda value: _integer(value, "task_id")
        )
    if "task_completed" in result:
        result["task_completed"] = result["task_completed"].map(
            lambda value: (
                value.casefold() == "true" if isinstance(value, str) and value else None
            )
        )
    return result


def _deleted_records(frame: pd.DataFrame) -> list[DeletedImage]:
    records: list[DeletedImage] = []
    for values in frame.to_dict(orient="records"):
        cleaned = {key: value for key, value in values.items() if value != ""}
        try:
            records.append(DeletedImage.model_validate(cleaned))
        except ValidationError as error:
            raise ManagedError("Invalid deleted-frame source evidence") from error
    return records


class LocalSourceFiles:
    """Keep complete original per-task data separate from transformed outputs."""

    def project_tables(self, tasks: list[TaskSnapshot]) -> dict[str, str]:
        """Repartition all live task evidence, retaining superseded source rows."""
        annotations: list[pd.DataFrame] = []
        deleted: list[DeletedImage] = []
        for task in tasks:
            if set(task.tables) != set(TABLE_NAMES):
                raise ManagedError(f"Incomplete source tables for task {task.id}")
            for name in TABLE_NAMES:
                table = _typed_rows(_table(task.tables[name], f"task {task.id}/{name}"))
                required = {
                    "image_name",
                    "task_id",
                    "frame_id",
                    "job_stage",
                    "job_state",
                }
                if missing := required - set(table.columns):
                    raise ManagedError(
                        f"CVAT source table lacks required columns: {sorted(missing)}"
                    )
                if not table.empty and (
                    "task_id" not in table
                    or any(value != task.id for value in table["task_id"])
                ):
                    raise ManagedError(
                        f"Task source evidence has mismatching task identity: {task.id}"
                    )
                if name == "deleted.csv":
                    deleted.extend(_deleted_records(table))
                else:
                    annotations.append(table)
        all_rows = (
            pd.concat(annotations, ignore_index=True, sort=False)
            if annotations
            else pd.DataFrame(columns=list(CSV_COLUMNS))
        )
        partitions = partition_annotations_df(all_rows, deleted)
        return {
            "dataset.csv": _csv(partitions.dataset),
            "obsolete.csv": _csv(partitions.obsolete),
            "in_progress.csv": _csv(partitions.in_progress),
            "deleted.csv": _csv(
                pd.DataFrame(
                    [record.to_csv_row() for record in partitions.deleted_images],
                    columns=list(CSV_COLUMNS),
                )
            ),
        }

    def csv_tables(self, content: bytes, source: str) -> dict[str, str]:
        """Require annotation fields but leave value validation to preparation."""
        frame = read_csv_bytes(content, source=source)
        missing = set(ANNOTATION_COLUMNS) - set(frame.columns)
        if missing:
            raise ManagedError(
                f"S3 annotation CSV lacks required columns: {sorted(missing)}"
            )
        if conflicts := set(PROVENANCE_COLUMNS).intersection(frame.columns):
            raise ManagedError(
                f"Source CSV contains reserved provenance columns: {sorted(conflicts)}"
            )
        empty = _csv(frame.iloc[0:0])
        return {
            "dataset.csv": content.decode("utf-8-sig"),
            "obsolete.csv": empty,
            "in_progress.csv": empty,
            "deleted.csv": empty,
        }

    def source_frame(self, snapshot: SourceSnapshot) -> pd.DataFrame:
        """Attach provenance only from trusted source identity and captured rows."""
        if set(snapshot.tables) != set(TABLE_NAMES):
            raise ManagedError(f"Incomplete tables in source {snapshot.name}")
        frame = _table(snapshot.tables["dataset.csv"], snapshot.name)
        if conflicts := set(PROVENANCE_COLUMNS).intersection(frame.columns):
            raise ManagedError(
                f"Source {snapshot.name} contains reserved fields: {sorted(conflicts)}"
            )
        frame["source_id"] = snapshot.name
        frame["source_project_id"] = (
            "" if snapshot.project_id is None else str(snapshot.project_id)
        )
        for target, column in (
            ("source_task_id", "task_id"),
            ("source_frame_id", "frame_id"),
        ):
            frame[target] = (
                frame[column] if snapshot.type == "cvat" and column in frame else ""
            )
        occurrences: dict[str, int] = {}
        identities = []
        for record in frame.to_dict(orient="records"):
            digest = hashlib.sha256(
                json.dumps(record, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            offset = occurrences.get(digest, 0)
            occurrences[digest] = offset + 1
            identities.append(f"{snapshot.name}:{digest}:{offset}")
        frame["source_row_id"] = identities
        return frame

    def read_snapshot(self, path: Path) -> ManagedSnapshot:
        """Read the local capture or the managed extension in published tasks."""
        source = path / "source-snapshot.yaml" if path.is_dir() else path
        try:
            if source.is_symlink() or not source.is_file():
                raise ManagedError(f"Expected a regular source snapshot: {source}")
            parsed = _yaml(source.read_bytes(), str(source))
            if isinstance(parsed, dict) and "managed" in parsed:
                parsed = parsed["managed"]
            return ManagedSnapshot.model_validate(parsed)
        except (OSError, ValidationError) as error:
            raise ManagedError(
                f"Cannot read managed source snapshot: {source}"
            ) from error

    def export(
        self, directory: Path, snapshot: ManagedSnapshot, frame: pd.DataFrame
    ) -> None:
        """Write all evidence first and the completion snapshot last."""
        if directory.exists() or directory.is_symlink():
            raise ManagedError(f"Candidate directory already exists: {directory}")
        for source in snapshot.sources:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", source.name):
                raise ManagedError(f"Unsafe source name in snapshot: {source.name!r}")
            if set(source.tables) != set(TABLE_NAMES):
                raise ManagedError(f"Incomplete source tables: {source.name}")
        directory.parent.mkdir(parents=True, exist_ok=True)
        try:
            with TemporaryDirectory(
                prefix=".cveta2-source-", dir=directory.parent
            ) as temporary:
                staged = Path(temporary)
                (staged / "dataset.csv").write_text(_csv(frame), encoding="utf-8")
                for source in snapshot.sources:
                    target = staged / "sources" / source.name
                    target.mkdir(parents=True)
                    for name in TABLE_NAMES:
                        (target / name).write_text(
                            source.tables[name], encoding="utf-8"
                        )
                (staged / "source-snapshot.yaml").write_text(
                    yaml.safe_dump(
                        snapshot.model_dump(mode="json"),
                        allow_unicode=True,
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                directory.mkdir(exist_ok=False)
                for source in snapshot.sources:
                    target = directory / "sources" / source.name
                    target.mkdir(parents=True)
                    for name in TABLE_NAMES:
                        os.link(staged / "sources" / source.name / name, target / name)
                os.link(staged / "dataset.csv", directory / "dataset.csv")
                os.link(
                    staged / "source-snapshot.yaml", directory / "source-snapshot.yaml"
                )
        except OSError as error:
            raise ManagedError(
                f"Cannot export managed source candidate: {directory}"
            ) from error
