"""Stable byte snapshots, strict YAML and local prepared-bundle persistence."""

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from cveta2.adapters.files.verification import read_csv_bytes, report_dict
from cveta2.domain.bundle.models import (
    DatasetMetadata,
    FetchTables,
    TaskManifest,
    UploadError,
)
from cveta2.domain.bundle.preparation import (
    PAYLOAD_NAMES,
    SOURCE_NAMES,
    BundleDraft,
    PreparedDataset,
    PreparedRecord,
    SourceSnapshot,
    StoredBundle,
)


def _check_yaml_nodes(node: Node, active: set[int]) -> None:
    """Reject duplicate/nontext mapping keys and recursive YAML aliases."""
    if id(node) in active:
        raise UploadError("Recursive YAML aliases are not supported.")
    active.add(id(node))
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise UploadError("YAML mapping keys must be strings.")
            if key.value in keys:
                raise UploadError(f"Duplicate YAML key: {key.value!r}")
            keys.add(key.value)
            _check_yaml_nodes(value, active)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _check_yaml_nodes(value, active)
    active.remove(id(node))


def _yaml(content: bytes, name: str) -> object:
    try:
        text = content.decode("utf-8")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        if node is not None:
            _check_yaml_nodes(node, set())
        result: object = yaml.safe_load(text)
    except (yaml.YAMLError, UnicodeError) as error:
        raise UploadError(f"Cannot parse {name}: {error}") from error
    else:
        return result


def _tables(content: dict[str, bytes]) -> FetchTables:
    tables = []
    for name in SOURCE_NAMES:
        frame = read_csv_bytes(content[name], source=name)
        missing = {"task_id", "image_name"} - set(frame.columns)
        if missing:
            raise UploadError(
                f"Source {name} lacks required columns: {sorted(missing)}"
            )
        tables.append(frame)
    return FetchTables(*tables)


def _payload(
    frame: pd.DataFrame, metadata: DatasetMetadata, tasks: TaskManifest
) -> dict[str, bytes]:
    return {
        "dataset.csv": frame.to_csv(index=False, lineterminator="\n").encode("utf-8"),
        "dataset.yaml": yaml.safe_dump(
            metadata.model_dump(), allow_unicode=True, sort_keys=False
        ).encode("utf-8"),
        "tasks.yaml": yaml.safe_dump(
            tasks.model_dump(), allow_unicode=True, sort_keys=False
        ).encode("utf-8"),
    }


def _hashes(content: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(value).hexdigest() for name, value in content.items()}


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise UploadError(f"Expected a regular, nonsymlink file: {path}")
    return path.read_bytes()


def _read_bound(
    directory: Path, names: tuple[str, ...], expected: dict[str, str]
) -> dict[str, bytes]:
    if set(expected) != set(names):
        raise UploadError("Invalid prepared file inventory; prepare again.")
    content = {name: _regular_bytes(directory / name) for name in names}
    if _hashes(content) != expected:
        raise UploadError("Prepared files changed (hash mismatch); prepare again.")
    return content


class LocalBundleFiles:
    """Write only new destinations and publish from a private stable snapshot."""

    def read_source(self, directory: Path) -> SourceSnapshot:
        """Capture all four source CSVs before parsing or validation."""
        try:
            content = {name: _regular_bytes(directory / name) for name in SOURCE_NAMES}
            return SourceSnapshot(directory.resolve(), content, _tables(content))
        except OSError as error:
            raise UploadError(
                f"Cannot read fetch output {directory}: {error}"
            ) from error

    def read_metadata(self, path: Path) -> DatasetMetadata:
        """Read strict metadata from the latest finalized parent."""
        try:
            return DatasetMetadata.model_validate(_yaml(path.read_bytes(), str(path)))
        except (OSError, ValidationError) as error:
            raise UploadError(f"Invalid dataset metadata {path}: {error}") from error

    def save_preparation(self, directory: Path, draft: BundleDraft) -> PreparedDataset:
        """Write reports and copied evidence without replacing any existing file."""
        try:
            self._save(directory, draft)
        except OSError as error:
            raise UploadError(
                f"Cannot create preparation {directory}: {error}"
            ) from error
        return PreparedDataset(
            directory, draft.ready, draft.validation, draft.metadata, draft.tasks
        )

    @staticmethod
    def _save(directory: Path, draft: BundleDraft) -> None:
        if directory.exists() or directory.is_symlink():
            raise UploadError(f"Preparation directory already exists: {directory}")
        if directory.resolve().is_relative_to(draft.source.base_dir):
            raise UploadError("Preparation must be outside the source directory.")
        directory.parent.mkdir(parents=True, exist_ok=True)
        payload = _payload(draft.validation.result.clean, draft.metadata, draft.tasks)
        report = report_dict(draft.validation.result)
        report.pop("metadata_columns", None)
        report.update(
            blockers=list(draft.validation.blockers),
            ready=draft.ready,
            class_changes=[asdict(change) for change in draft.changes],
            broken_image_rows=len(draft.validation.broken_images),
        )
        with TemporaryDirectory(
            prefix=".cveta2-prepare-", dir=directory.parent
        ) as temporary:
            staged = Path(temporary)
            (staged / "sources").mkdir()
            for name, content in draft.source.content.items():
                (staged / "sources" / name).write_bytes(content)
            draft.validation.broken_images.to_csv(
                staged / "broken-images.csv", index=False
            )
            (staged / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if draft.ready:
                for name, content in payload.items():
                    (staged / name).write_bytes(content)
                record = PreparedRecord(
                    options=draft.options,
                    parent_id=draft.parent.dataset_id if draft.parent else None,
                    parent_version=draft.parent.version if draft.parent else None,
                    source_hashes=_hashes(draft.source.content),
                    payload_hashes=_hashes(payload),
                )
                record_bytes = (record.model_dump_json(indent=2) + "\n").encode("utf-8")
                (staged / "preparation.json").write_bytes(record_bytes)
                (staged / "preparation.sha256").write_text(
                    hashlib.sha256(record_bytes).hexdigest() + "\n", encoding="ascii"
                )
            # Claim the destination exclusively; the marker is linked last so a
            # partially failed write can never appear uploadable.
            directory.mkdir(exist_ok=False)
            (directory / "sources").mkdir()
            for name in SOURCE_NAMES:
                os.link(staged / "sources" / name, directory / "sources" / name)
            for name in (
                "broken-images.csv",
                "report.json",
                *PAYLOAD_NAMES,
                "preparation.json",
                "preparation.sha256",
            ):
                if (staged / name).is_file():
                    os.link(staged / name, directory / name)

    @contextmanager
    def stage_prepared(self, directory: Path) -> Iterator[StoredBundle]:
        """Read/hash once, then hold a stable local payload until publication ends."""
        try:
            record_bytes = _regular_bytes(directory / "preparation.json")
            expected_record_hash = _regular_bytes(
                directory / "preparation.sha256"
            ).strip()
            actual_record_hash = (
                hashlib.sha256(record_bytes).hexdigest().encode("ascii")
            )
            if actual_record_hash != expected_record_hash:
                raise UploadError(
                    "Preparation record changed (hash mismatch); prepare again."
                )
            record = PreparedRecord.model_validate_json(record_bytes)
            if not record.options.project.strip() or not record.options.dataset_name:
                raise UploadError("Prepared destination is incomplete; prepare again.")
            if (directory / "sources").is_symlink():
                raise UploadError("Prepared source directory must not be a symlink.")
            source = _read_bound(
                directory / "sources", SOURCE_NAMES, record.source_hashes
            )
            payload = _read_bound(directory, PAYLOAD_NAMES, record.payload_hashes)
            metadata = DatasetMetadata.model_validate(
                _yaml(payload["dataset.yaml"], "dataset.yaml")
            )
            tasks = TaskManifest.model_validate(
                _yaml(payload["tasks.yaml"], "tasks.yaml")
            )
            dataset = read_csv_bytes(payload["dataset.csv"], source="dataset.csv")
            captured = SourceSnapshot(directory.resolve(), source, _tables(source))
            with TemporaryDirectory(prefix="cveta2-publish-") as temporary:
                staging = Path(temporary)
                for name, content in payload.items():
                    (staging / name).write_bytes(content)
                yield StoredBundle(
                    staging, captured, record, metadata, tasks, dataset, payload
                )
        except (OSError, ValidationError) as error:
            raise UploadError(
                f"Cannot read prepared bundle {directory}: {error}"
            ) from error

    def payload_matches(
        self, bundle: StoredBundle, frame: pd.DataFrame, tasks: TaskManifest
    ) -> bool:
        """Require deterministic derivation to equal the bytes actually reviewed."""
        return _payload(frame, bundle.metadata, tasks) == bundle.payload
