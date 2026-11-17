"""Executable acceptance checks for the canonical architecture."""

from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[1] / "cveta2"


@pytest.mark.parametrize("layer", ["domain", "application", "adapters", "composition", "interfaces"])
def test_canonical_layers_are_explicit_packages(layer: str) -> None:
    assert (PACKAGE / layer / "__init__.py").is_file()


def test_canonical_effect_ownership() -> None:
    from tests.architecture_effects import check_tree

    assert check_tree(PACKAGE) == []


INNER_EFFECT_SAMPLES = {
    "time.strftime": "import time\ndef f():\n    return time.strftime('%Y')\n",
    "time.localtime": "import time\ndef f():\n    return time.localtime()\n",
    "time.gmtime": "from time import gmtime\ndef f():\n    return gmtime()\n",
    "time.time_ns": "import time\ndef f():\n    return time.time_ns()\n",
    "time.monotonic_ns": "import time\ndef f():\n    return time.monotonic_ns()\n",
    "time.perf_counter_ns": "import time\ndef f():\n    return time.perf_counter_ns()\n",
    "time.process_time": "import time\ndef f():\n    return time.process_time()\n",
    "datetime.today": "from datetime import datetime\ndef f():\n    return datetime.today()\n",
    "asyncio": "import asyncio\nasync def f():\n    await asyncio.sleep(1)\n",
    "asyncio-from-import": "from asyncio import sleep\nasync def f():\n    await sleep(1)\n",
    "Path.walk": "from pathlib import Path\ndef f(root: Path):\n    return list(root.walk())\n",
}


@pytest.mark.parametrize("effect", sorted(INNER_EFFECT_SAMPLES))
@pytest.mark.parametrize("layer", ["domain", "application"])
def test_effect_checker_flags_inner_layer_effects(effect: str, layer: str) -> None:
    from tests.architecture_effects import inspect_source

    assert inspect_source(INNER_EFFECT_SAMPLES[effect], f"cveta2.{layer}.sample")


def test_effect_checker_keeps_ast_walk_pure() -> None:
    from tests.architecture_effects import inspect_source

    source = "import ast\ndef f(tree: ast.AST):\n    return list(ast.walk(tree))\n"
    assert inspect_source(source, "cveta2.domain.sample") == []


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
def test_public_facades_preserve_canonical_identity(public: str, canonical: str, name: str) -> None:
    from importlib import import_module

    assert getattr(import_module(public), name) is getattr(import_module(canonical), name)
