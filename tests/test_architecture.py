"""Executable acceptance checks for the canonical architecture."""

from pathlib import Path
from typing import Any, cast

import pytest
from grimp import ImportGraph

PACKAGE = Path(__file__).parents[1] / "cveta2"


@pytest.mark.parametrize(
    "layer", ["domain", "application", "adapters", "composition", "interfaces"]
)
def test_canonical_layers_are_explicit_packages(layer: str) -> None:
    assert (PACKAGE / layer / "__init__.py").is_file()


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ("from os import environ as env\nx = env.get('SECRET')", "effect import os"),
        ("from pathlib import Path as P\nP('x').read_text()", "external effect"),
        (
            "from time import monotonic as clock\nclock()",
            "external effect time.monotonic",
        ),
        ("from builtins import open as read\nread('x')", "external effect"),
        ("import pandas as pd\npd.read_csv('x')", "external effect pandas.read_csv"),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import cvat_sdk",
            "effect import cvat_sdk",
        ),
        ("def hidden():\n    import threading", "effect import threading"),
        ("from cveta2 import CvatClient", "canonical import of public root"),
        ("import cveta2 as public", "canonical import of public root"),
    ],
)
def test_inner_effect_negative_fixtures(source: str, fragment: str) -> None:
    from scripts.check_architecture import inspect_source

    assert any(
        fragment in item for item in inspect_source(source, "cveta2.application.probe")
    )


def test_pure_lexical_paths_and_dataframe_transforms_are_allowed() -> None:
    from scripts.check_architecture import inspect_source

    source = (
        "from pathlib import Path\n"
        "x = Path('root') / 'image.jpg'\n"
        "y = str(x).replace('a', 'b')"
    )
    assert inspect_source(source, "cveta2.domain.probe") == []


def test_canonical_effect_ownership() -> None:
    from scripts.check_architecture import check_tree

    assert check_tree(PACKAGE) == []


def _contracts() -> list[dict[str, Any]]:
    import tomllib

    parsed = tomllib.loads((PACKAGE.parent / "pyproject.toml").read_text())["tool"][
        "importlinter"
    ]["contracts"]
    return cast("list[dict[str, Any]]", parsed)


def _check_contract(config: dict[str, Any], graph: ImportGraph) -> bool:
    import copy

    from importlinter import configuration

    configuration.configure()  # type: ignore[no-untyped-call]  # Upstream config initializer has no annotations.

    from importlinter.contracts.acyclic_siblings import AcyclicSiblingsContract
    from importlinter.contracts.forbidden import ForbiddenContract
    from importlinter.contracts.layers import LayersContract
    from importlinter.contracts.protected import ProtectedContract

    classes: dict[
        str,
        type[
            LayersContract
            | ForbiddenContract
            | ProtectedContract
            | AcyclicSiblingsContract
        ],
    ] = {
        "layers": LayersContract,
        "forbidden": ForbiddenContract,
        "protected": ProtectedContract,
        "acyclic_siblings": AcyclicSiblingsContract,
    }
    options = {
        key: str(value).lower() if isinstance(value, bool) else value
        for key, value in config.items()
        if key not in {"name", "type"}
    }
    contract = classes[config["type"]](
        name=config["name"],
        session_options={
            "root_packages": ["cveta2"],
            "include_external_packages": "true",
        },
        contract_options=options,
    )
    return contract.check(copy.deepcopy(graph), verbose=False).kept


def _synthetic_graph() -> ImportGraph:
    import grimp

    graph = grimp.ImportGraph()
    for path in PACKAGE.rglob("*.py"):
        parts = path.relative_to(PACKAGE.parent).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        graph.add_module(name)
    for name in ("cvat_sdk", "boto3", "botocore", "clearml", "questionary"):
        graph.add_module(name)
    return graph


@pytest.mark.parametrize(
    ("importer", "imported"),
    [
        ("cveta2.domain.models", "cveta2.adapters.s3.utils"),
        ("cveta2.domain.verification.validation", "cveta2.adapters.files.media"),
        ("cveta2.domain.bundle.validation", "cveta2.adapters.files.bundle"),
        (
            "cveta2.application.use_cases.dataset_bundle",
            "cveta2.adapters.clearml.bundle",
        ),
        ("cveta2.application.use_cases.dataset_bundle", "questionary"),
        ("cveta2.adapters.class_api.http", "clearml"),
        ("cveta2.application.ports.cvat", "cveta2.composition.client"),
        ("cveta2.application.client.base", "cveta2.client"),
        ("cveta2.adapters.cvat.sdk_adapter", "cveta2.adapters.s3.utils"),
        ("cveta2.application.use_cases.fetch", "cvat_sdk"),
        ("cveta2.interfaces.api", "boto3"),
        ("cveta2.adapters.s3.upload", "cveta2.application.use_cases.upload"),
        ("cveta2.composition.client", "clearml"),
        ("cveta2.application.use_cases.fetch", "questionary"),
    ],
)
def test_import_contracts_reject_outward_or_sdk_edges(
    importer: str, imported: str
) -> None:
    graph = _synthetic_graph()
    graph.add_import(importer=importer, imported=imported)
    assert any(not _check_contract(config, graph) for config in _contracts())


def test_import_contracts_accept_inward_edges() -> None:
    graph = _synthetic_graph()
    for importer, imported in [
        ("cveta2.interfaces.api", "cveta2.composition.client"),
        ("cveta2.composition.client", "cveta2.adapters.cvat.connection"),
        ("cveta2.application.client.base", "cveta2.application.ports.cvat"),
        ("cveta2.adapters.cvat.sdk_adapter", "cvat_sdk"),
        ("cveta2.adapters.s3.utils", "boto3"),
    ]:
        graph.add_import(importer=importer, imported=imported)
    assert all(_check_contract(config, graph) for config in _contracts())


def test_import_contracts_reject_transitive_outward_path() -> None:
    graph = _synthetic_graph()
    graph.add_import(
        importer="cveta2.application.client.base", imported="cveta2.domain.models"
    )
    graph.add_import(
        importer="cveta2.domain.models", imported="cveta2.adapters.s3.utils"
    )
    assert not _check_contract(_contracts()[0], graph)


def test_import_contracts_reject_unclassified_runtime_module() -> None:
    graph = _synthetic_graph()
    graph.add_module("cveta2.unclassified")
    assert not _check_contract(_contracts()[0], graph)


def test_import_contracts_reject_sibling_cycle() -> None:
    graph = _synthetic_graph()
    graph.add_import(
        importer="cveta2.domain.models", imported="cveta2.domain.partition"
    )
    graph.add_import(
        importer="cveta2.domain.partition", imported="cveta2.domain.models"
    )
    config = next(c for c in _contracts() if c["type"] == "acyclic_siblings")
    assert not _check_contract(config, graph)


def test_inner_imports_do_not_load_optional_or_network_sdks() -> None:
    import subprocess
    import sys

    source = """
import importlib.abc
import sys
class RejectSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = {'cvat_sdk', 'boto3', 'botocore', 'clearml', 'questionary'}
        if fullname.split('.')[0] in blocked:
            raise AssertionError('Inner import reached SDK: ' + fullname)
sys.meta_path.insert(0, RejectSDK())
import cveta2
assert set(cveta2.__all__).issubset(dir(cveta2))
import cveta2.domain.models
import cveta2.domain.partition
import cveta2.application.ports.cvat
import cveta2.application.client
import cveta2.application.use_cases.fetch
import cveta2.application.use_cases.upload
import cveta2.application.use_cases.convert
import cveta2.domain.verification.validation
import cveta2.domain.bundle.validation
import cveta2.application.use_cases.dataset_bundle
"""
    # The isolated interpreter executes only the fixed source fixture above.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", source],
        cwd=PACKAGE.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path as P\np = P('x')\np.rename('y')",
        "from pathlib import Path\ndef rename(p: Path):\n    p.replace('x')",
        "from pathlib import Path\nPath.home()",
        "import urllib.request as network\nnetwork.urlopen('https://example.test')",
        "from time import time as clock\nnow = clock\nnow()",
    ],
)
def test_aliased_and_typed_effect_calls_are_rejected(source: str) -> None:
    from scripts.check_architecture import inspect_source

    assert inspect_source(source, "cveta2.domain.probe")


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("local", "def fetch():\n    import cvat_sdk\n"),
        (
            "typeonly",
            (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    import cvat_sdk\n"
            ),
        ),
    ],
)
def test_grimp_collects_local_and_type_only_sdk_imports(
    name: str, source: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import grimp

    package = f"architecture_fixture_{name}"
    directory = tmp_path / package
    directory.mkdir()
    (directory / "__init__.py").write_text("")
    (directory / "adapter.py").write_text("import cvat_sdk\n")
    (directory / "core.py").write_text(source)
    monkeypatch.syspath_prepend(str(tmp_path))
    graph = grimp.build_graph(
        package,
        include_external_packages=True,
        exclude_type_checking_imports=False,
        cache_dir=None,
    )
    config = {
        "name": "Fixture SDK owner",
        "type": "protected",
        "protected_modules": ["cvat_sdk"],
        "allowed_importers": [f"{package}.adapter"],
    }
    assert not _check_contract(config, graph)


@pytest.mark.parametrize(
    ("public", "canonical", "name"),
    [
        ("cveta2.models", "cveta2.domain.models", "BBoxAnnotation"),
        ("cveta2.exceptions", "cveta2.domain.errors", "Cveta2Error"),
        ("cveta2.image_downloader", "cveta2.domain.storage", "CloudStorageInfo"),
        ("cveta2.config", "cveta2.application.settings", "CacheProjectSettings"),
        ("cveta2.upload_manifest", "cveta2.domain.upload", "UploadManifest"),
        ("cveta2.client", "cveta2.composition.client", "CvatClient"),
        ("cveta2.api", "cveta2.composition.conversion", "convert_to_yolo"),
    ],
)
def test_public_facades_preserve_canonical_identity(
    public: str, canonical: str, name: str
) -> None:
    from importlib import import_module

    assert getattr(import_module(public), name) is getattr(
        import_module(canonical), name
    )


def test_new_runtime_packages_do_not_use_future_annotations() -> None:
    import ast

    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        assert not any(
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
            and any(alias.name == "annotations" for alias in node.names)
            for node in ast.walk(tree)
        ), path
