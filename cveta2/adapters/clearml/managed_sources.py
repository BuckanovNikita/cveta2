"""Immutable ClearML source-snapshot retrieval without sibling adapter IO."""

from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from cveta2.adapters.clearml.bundle import _sdk_errors
from cveta2.domain.managed.models import ManagedError, ManagedSnapshot


class _Dataset(Protocol):
    @property
    def id(self) -> str: ...
    def is_final(self) -> bool: ...
    def list_files(self) -> list[str]: ...
    def get_local_copy(
        self,
        *,
        files: list[str],
        use_soft_links: bool,  # noqa: F841, RUF100 - external SDK keyword contract.
        raise_on_error: bool,  # noqa: F841, RUF100 - external SDK keyword contract.
    ) -> str: ...


class _Factory(Protocol):
    def get(
        self,
        *,
        dataset_id: str,
        only_completed: bool,  # noqa: F841, RUF100 - external SDK keyword contract.
        auto_create: bool,  # noqa: F841, RUF100 - external SDK keyword contract.
    ) -> _Dataset: ...


def _factory() -> _Factory:
    try:
        # Keep the optional SDK lazy and opaque at its outgoing boundary.
        return cast("_Factory", import_module("clearml").Dataset)
    except ImportError as error:
        raise ManagedError("Install cveta2[clearml] to read published dataset evidence") from error


def _check_yaml(node: Node, active: set[int]) -> None:
    """Reject duplicate/nontext keys and cycles before safe construction."""
    if id(node) in active:
        raise ManagedError("Recursive aliases in published tasks.yaml")
    active.add(id(node))
    if isinstance(node, MappingNode):
        keys: set[str] = set()
        for key, value in node.value:
            if not isinstance(key, ScalarNode) or key.tag != "tag:yaml.org,2002:str":
                raise ManagedError("Published tasks.yaml mapping keys must be strings")
            if key.value in keys:
                raise ManagedError(f"Duplicate published tasks.yaml key: {key.value}")
            keys.add(key.value)
            _check_yaml(value, active)
    elif isinstance(node, SequenceNode):
        for value in node.value:
            _check_yaml(value, active)
    active.remove(id(node))


class ClearMLSources:
    """Retrieve only requested regular files from one finalized immutable id."""

    @staticmethod
    def _dataset(dataset_id: str) -> _Dataset:
        dataset = _factory().get(dataset_id=dataset_id, only_completed=True, auto_create=False)
        if dataset.id != dataset_id or not dataset.is_final():
            raise ManagedError("ClearML returned a different or unfinished dataset")
        return dataset

    @staticmethod
    def _read_files(dataset: _Dataset, names: tuple[str, ...]) -> dict[str, bytes]:
        if not set(names).issubset(dataset.list_files()):
            raise ManagedError("Published dataset lacks required payload files")
        directory = Path(dataset.get_local_copy(files=list(names), use_soft_links=False, raise_on_error=True))
        content = {}
        for name in names:
            path = directory / name
            if path.is_symlink() or not path.is_file():
                raise ManagedError(f"Missing regular published payload file: {name}")
            content[name] = path.read_bytes()
        return content

    def read_files(self, dataset_id: str, names: tuple[str, ...]) -> dict[str, bytes]:
        """Require exact dataset identity and a complete requested inventory."""
        if not names or any(name not in {"dataset.csv", "dataset.yaml", "tasks.yaml"} for name in names):
            raise ManagedError("Only the three public payload files can be retrieved")
        with _sdk_errors("Cannot read published managed dataset"):
            return self._read_files(self._dataset(dataset_id), names)

    def read_snapshot(self, dataset_id: str) -> ManagedSnapshot | None:
        """Read managed source evidence; legacy task manifests return None."""
        with _sdk_errors("Cannot read published source snapshot"):
            dataset = self._dataset(dataset_id)
            if "tasks.yaml" not in dataset.list_files():
                return None
            content = self._read_files(dataset, ("tasks.yaml",))["tasks.yaml"]
        try:
            node = yaml.compose(content, Loader=yaml.SafeLoader)
            if node is not None:
                _check_yaml(node, set())
            parsed = yaml.safe_load(content)
            if not isinstance(parsed, dict):
                raise ManagedError("Published tasks.yaml is not a mapping")
            if "managed" not in parsed:
                return None
            return ManagedSnapshot.model_validate(parsed["managed"])
        except (yaml.YAMLError, ValidationError) as error:
            raise ManagedError("Invalid managed source snapshot in published tasks.yaml") from error
