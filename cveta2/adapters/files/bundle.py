"""Stable byte snapshots, strict YAML and local prepared-bundle persistence."""

import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from cveta2.adapters.files.archive import pack_sources, unpack_sources
from cveta2.adapters.files.verification import read_csv_bytes, report_dict
from cveta2.domain.bundle.draft import DatasetDraft
from cveta2.domain.bundle.models import (
    DatasetMetadata,
    FetchTables,
    Publication,
    TaskManifest,
    UploadError,
)
from cveta2.domain.bundle.preparation import (
    SOURCE_NAMES,
    SOURCES_ARCHIVE,
    BundleProposal,
    CurrentBundle,
    PreparedDataset,
    SourceSnapshot,
    VerifyRecord,
)
from cveta2.domain.managed.models import ClearMLDestination
from cveta2.domain.verification.models import DatasetInputError

# The bundle files ``read_bundle`` captures and ``stage_publication`` publishes as read.
_CAPTURED_NAMES = ("dataset.csv", "dataset.yaml", SOURCES_ARCHIVE)


def _yaml_children(node: Node) -> list[Node]:
    """Return a node's values after rejecting duplicate or nontext mapping keys."""
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key, _value in node.value:
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise UploadError("YAML mapping keys must be strings.")
            if key.value in keys:
                raise UploadError(f"Duplicate YAML key: {key.value!r}")
            keys.add(key.value)
        return [value for _key, value in node.value]
    if isinstance(node, SequenceNode):
        return list(node.value)
    return []


def _check_yaml_nodes(root: Node) -> None:
    """Reject duplicate/nontext mapping keys and recursive YAML aliases.

    The walk is iterative so nesting depth cannot exhaust the call stack. A node
    reused through an alias is checked once; ``active`` holds the current path.
    """
    active: set[int] = set()
    checked: set[int] = set()
    pending: list[tuple[Node, bool]] = [(root, False)]
    while pending:
        node, leaving = pending.pop()
        if leaving:
            active.remove(id(node))
            checked.add(id(node))
            continue
        if id(node) in checked:
            continue
        if id(node) in active:
            raise UploadError("Recursive YAML aliases are not supported.")
        active.add(id(node))
        pending.append((node, True))
        pending.extend((child, False) for child in reversed(_yaml_children(node)))


def _error_details(error: OSError | ValidationError) -> str:
    """Describe a failure without echoing input, whose repr may be exponential under YAML aliases."""
    if isinstance(error, OSError):
        return str(error)
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors(include_input=False, include_url=False)
    )


def _yaml_error(error: yaml.YAMLError) -> str:
    """Describe a YAML error by its problem and place, never by the source line, which may hold credentials."""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None)
    if isinstance(error, yaml.MarkedYAMLError) and problem and mark is not None:
        return f"{problem} (line {mark.line + 1}, column {mark.column + 1})"
    return type(error).__name__


def _yaml(content: bytes, name: str) -> object:
    try:
        text = content.decode("utf-8")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        if node is not None:
            _check_yaml_nodes(node)
        result: object = yaml.safe_load(text)
    except yaml.YAMLError as error:
        # The original error text holds the source line: keep it out of the traceback too.
        raise UploadError(f"Cannot parse {name}: {_yaml_error(error)}") from None
    except UnicodeError as error:
        raise UploadError(f"Cannot parse {name}: {error}") from error
    except RecursionError as error:
        raise UploadError(f"Cannot parse {name}: YAML nesting is too deep") from error
    else:
        return result


def _tables(content: dict[str, bytes]) -> FetchTables:
    tables = []
    for name in SOURCE_NAMES:
        frame = read_csv_bytes(content[name], source=name)
        missing = {"task_id", "image_name"} - set(frame.columns)
        if missing:
            raise UploadError(f"Source {name} lacks required columns: {sorted(missing)}")
        tables.append(frame)
    return FetchTables(*tables)


def _tasks_yaml(tasks: TaskManifest) -> bytes:
    return yaml.safe_dump(tasks.model_dump(), allow_unicode=True, sort_keys=False).encode("utf-8")


def _bookkeeping(metadata: DatasetMetadata, tasks: TaskManifest) -> dict[str, bytes]:
    """Serialize ``dataset.yaml`` and ``tasks.yaml`` as every payload writes them."""
    return {
        "dataset.yaml": yaml.safe_dump(metadata.model_dump(), allow_unicode=True, sort_keys=False).encode("utf-8"),
        "tasks.yaml": _tasks_yaml(tasks),
    }


def _payload(frame: pd.DataFrame, metadata: DatasetMetadata, tasks: TaskManifest) -> dict[str, bytes]:
    return {
        "dataset.csv": frame.to_csv(index=False, lineterminator="\n").encode("utf-8"),
        **_bookkeeping(metadata, tasks),
    }


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise UploadError(f"Expected a regular, nonsymlink file: {path}")
    return path.read_bytes()


def _json(path: Path) -> object:
    """Parse one regular JSON file; raises UploadError, OSError or ValueError."""
    result: object = json.loads(_regular_bytes(path))
    return result


def _recorded_parent(report: dict[str, object]) -> tuple[str | None, str | None] | None:
    """``(id, version)`` of the recorded parent, ``(None, None)`` for ``null``, None when absent or malformed."""
    if "parent" not in report:
        return None
    parent = report["parent"]
    if parent is None:
        return None, None
    if isinstance(parent, dict):
        parent_id, version = parent.get("id"), parent.get("version")
        if isinstance(parent_id, str) and (version is None or isinstance(version, str)):
            return parent_id, version
    return None


def _recorded(directory: Path) -> VerifyRecord | None:
    """Return the destination and parent ``verify`` wrote in ``report.json``, or None when unusable."""
    try:
        report = _json(directory / "report.json")
    except (UploadError, OSError, ValueError):
        return None
    if not isinstance(report, dict) or not isinstance(destination := report.get("destination"), dict):
        return None
    project, dataset = destination.get("project"), destination.get("dataset")
    parent = _recorded_parent(report)
    if not isinstance(project, str) or not isinstance(dataset, str) or parent is None:
        return None
    return VerifyRecord(project, dataset, *parent)


def _previous_publication(directory: Path) -> dict[str, object] | None:
    """Return ``publication.json``: None when absent, ``{}`` when it is not a readable JSON object."""
    path = directory / "publication.json"
    if not path.exists() and not path.is_symlink():
        return None
    try:
        record = _json(path)
    except (UploadError, OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _report(proposal: BundleProposal) -> bytes:
    report = report_dict(proposal.validation.result)
    report.pop("metadata_columns", None)
    parent = proposal.parent
    report.update(
        blockers=list(proposal.blockers),
        ready=proposal.ready,
        pending=list(proposal.pending),
        destination={"project": proposal.destination.project, "dataset": proposal.destination.dataset},
        parent=None if parent is None else {"id": parent.dataset_id, "version": parent.version},
        class_changes=[asdict(change) for change in proposal.changes],
        class_marks=[asdict(mark) for mark in proposal.mark_changes],
        dropped_local_roots=list(proposal.dropped_local_roots),
        broken_image_rows=len(proposal.validation.broken_images),
        split_prefilled=proposal.split_prefilled,
    )
    return (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class LocalBundleFiles:
    """Write only new destinations and publish from a private stable snapshot."""

    def read_source(self, directory: Path) -> SourceSnapshot:
        """Capture all four source CSVs before parsing or validation."""
        try:
            content = {name: _regular_bytes(directory / name) for name in SOURCE_NAMES}
            return SourceSnapshot(directory.resolve(), content, _tables(content))
        except OSError as error:
            raise UploadError(f"Cannot read fetch output {directory}: {error}") from error

    def read_metadata(self, path: Path) -> DatasetMetadata:
        """Read strict metadata from the latest finalized parent."""
        try:
            return DatasetMetadata.model_validate(_yaml(path.read_bytes(), str(path)))
        except (OSError, ValidationError) as error:
            raise UploadError(f"Invalid dataset metadata {path}: {_error_details(error)}") from error

    def default_directory(self, source: Path) -> Path:
        """Return the first sibling of the resolved source, ``-prepared`` then ``-prepared-2``…, not yet taken."""
        base = source.resolve()
        candidate, number = base.parent / f"{base.name}-prepared", 1
        while candidate.exists() or candidate.is_symlink():
            number += 1
            candidate = base.parent / f"{base.name}-prepared-{number}"
        return candidate

    def read_draft(self, directory: Path) -> DatasetDraft | None:
        """Read the strict draft; None when there is no ``dataset.yaml``."""
        path = directory / "dataset.yaml"
        if not path.exists() and not path.is_symlink():
            return None
        try:
            content = _regular_bytes(path)
        except OSError as error:
            raise UploadError(f"Cannot read dataset draft {path}: {error}") from error
        try:
            return DatasetDraft.model_validate(_yaml(content, str(path)))
        except ValidationError as error:
            raise UploadError(f"Invalid dataset draft {path}: {_error_details(error)}") from error

    def write_draft(self, directory: Path, draft: DatasetDraft) -> bool:
        """Write the draft; a different existing file is first kept as ``dataset.yaml.bak``."""
        path = directory / "dataset.yaml"
        data = draft.model_dump(mode="json", exclude_none=True)
        images = {key: value for key, value in data.get("images", {}).items() if value}
        data.pop("images", None)
        if images:
            data["images"] = images
        content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")
        try:
            backed_up = False
            if path.exists() or path.is_symlink():
                if path.read_bytes() == content:
                    return False
                path.replace(directory / "dataset.yaml.bak")
                backed_up = True
            path.write_bytes(content)
        except OSError as error:
            raise UploadError(f"Cannot write dataset draft {path}: {error}") from error
        return backed_up

    def save_preparation(self, directory: Path, proposal: BundleProposal) -> PreparedDataset:
        """Write a new bundle with one rename, never replacing an existing file."""
        try:
            self._save(directory, proposal)
        except OSError as error:
            raise UploadError(f"Cannot create preparation {directory}: {error}") from error
        return PreparedDataset(
            directory=directory,
            ready=proposal.ready,
            validation=proposal.validation,
            metadata=proposal.metadata,
            tasks=proposal.tasks,
            blockers=proposal.blockers,
            pending=proposal.pending,
            changes=proposal.changes,
            mark_changes=proposal.mark_changes,
            dropped_local_roots=proposal.dropped_local_roots,
            split_prefilled=proposal.split_prefilled,
            parent=proposal.parent,
        )

    @staticmethod
    def _save(directory: Path, proposal: BundleProposal) -> None:
        if directory.exists() or directory.is_symlink():
            raise UploadError(f"Preparation directory already exists: {directory}")
        if directory.resolve().is_relative_to(proposal.source.base_dir):
            raise UploadError("Preparation must be outside the source directory.")
        directory.parent.mkdir(parents=True, exist_ok=True)
        files = {SOURCES_ARCHIVE: pack_sources(proposal.source.content), "report.json": _report(proposal)}
        if proposal.ready:
            files.update(_payload(proposal.validation.result.clean, proposal.metadata, proposal.tasks))
        holder = Path(tempfile.mkdtemp(prefix=".cveta2-prepare-", dir=directory.parent))
        try:
            # mkdtemp's directory is private (0700); the bundle inside it comes from
            # a plain mkdir, so it gets the permissions any new directory would.
            staged = holder / directory.name
            staged.mkdir()
            for name, content in files.items():
                (staged / name).write_bytes(content)
            proposal.validation.broken_images.to_csv(staged / "broken-images.csv", index=False)
            if directory.exists() or directory.is_symlink():
                raise UploadError(f"Preparation directory already exists: {directory}")
            # One rename makes the whole bundle appear: an interrupted write leaves nothing.
            os.rename(staged, directory)  # noqa: PTH104 - the single atomic step the interruption test patches.
        finally:
            shutil.rmtree(holder, ignore_errors=True)

    def read_bundle(self, directory: Path) -> CurrentBundle:
        """Read ``dataset.csv``, ``dataset.yaml`` and ``sources.tar.gz`` once and parse the captured bytes."""
        try:
            content = {name: _regular_bytes(directory / name) for name in _CAPTURED_NAMES}
        except OSError as error:
            raise UploadError(f"Cannot read prepared bundle {directory}: {error}") from error
        metadata_path = directory / "dataset.yaml"
        try:
            metadata = DatasetMetadata.model_validate(_yaml(content["dataset.yaml"], str(metadata_path)))
        except ValidationError as error:
            raise UploadError(f"Invalid dataset metadata {metadata_path}: {_error_details(error)}") from error
        try:
            dataset = read_csv_bytes(content["dataset.csv"], source=str(directory / "dataset.csv"))
        except DatasetInputError as error:
            raise UploadError(str(error)) from error
        sources = unpack_sources(content[SOURCES_ARCHIVE])
        try:
            tables = _tables(sources)
        except DatasetInputError as error:
            raise UploadError(f"{SOURCES_ARCHIVE}: {error}") from error
        return CurrentBundle(
            directory=directory,
            source=SourceSnapshot(directory.resolve(), sources, tables),
            metadata=metadata,
            dataset=dataset,
            content=content,
            recorded=_recorded(directory),
            previous_publication=_previous_publication(directory),
        )

    def read_rows(self, path: Path) -> pd.DataFrame:
        """Read a downloaded parent ``dataset.csv`` without lexical inference."""
        try:
            return read_csv_bytes(path.read_bytes(), source=str(path))
        except (OSError, DatasetInputError) as error:
            raise UploadError(f"Не удалось прочитать dataset.csv родителя {path}: {error}") from error

    def write_tasks(self, directory: Path, tasks: TaskManifest) -> None:
        """Replace ``tasks.yaml`` with one rename, never writing through a symlink."""
        path, temporary = directory / "tasks.yaml", directory / ".tasks.yaml.tmp"
        try:
            temporary.unlink(missing_ok=True)
            try:
                # Exclusive creation never follows a planted link and keeps the usual file mode.
                with temporary.open("xb") as stream:
                    stream.write(_tasks_yaml(tasks))
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError as error:
            raise UploadError(f"Не удалось записать {path}: {error}") from error

    @contextmanager
    def stage_publication(self, bundle: CurrentBundle, tasks: TaskManifest) -> Iterator[Path]:
        """Hold the bytes ``read_bundle`` captured and ``tasks.yaml`` in a private directory."""
        with TemporaryDirectory(prefix="cveta2-publish-") as temporary:
            staging = Path(temporary)
            try:
                for name, content in bundle.content.items():
                    (staging / name).write_bytes(content)
                (staging / "tasks.yaml").write_bytes(_tasks_yaml(tasks))
            except OSError as error:
                raise UploadError(f"Cannot stage publication files: {error}") from error
            yield staging

    def write_publication(self, directory: Path, publication: Publication, destination: ClearMLDestination) -> None:
        """Write ``publication.json``: the published version, its destination and time, no hashes."""
        record = {
            "dataset_id": publication.dataset_id,
            "version": publication.version,
            "project": destination.project,
            "dataset": destination.dataset,
            "published_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        (directory / "publication.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
