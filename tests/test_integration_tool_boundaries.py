"""Integration tooling stays outside the runtime package, and vice versa.

``tests/integration/stand_tls.py`` is imported by the stand scripts and the live
fixtures to classify certificate-trust failures. It must stay a standard-library
helper (no cveta2 runtime module, no SDK), and no runtime module may import test
or integration tooling, which is not packaged.

``tests/integration/lifecycle.py`` resolves the run before pytest and before the
k8s-infra environment exists, so it imports only the standard library too.
"""

import ast
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STAND_TLS = ROOT / "tests" / "integration" / "stand_tls.py"
RUNTIME = ROOT / "cveta2"

LIFECYCLE = ROOT / "tests" / "integration" / "lifecycle.py"

STAND_TLS_ALLOWED = frozenset({"ssl"})
RUNTIME_FORBIDDEN = ("tests", "scripts")


def imported_roots(source: str) -> set[str]:
    """Top-level package of every absolute import in ``source``, local ones too."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def stand_tls_violations(source: str) -> set[str]:
    return imported_roots(source) - STAND_TLS_ALLOWED


def lifecycle_violations(source: str) -> set[str]:
    return imported_roots(source) - set(sys.stdlib_module_names)


def runtime_violations(source: str) -> set[str]:
    return {root for root in imported_roots(source) if root in RUNTIME_FORBIDDEN}


def test_stand_tls_imports_only_the_standard_library_ssl_module() -> None:
    assert stand_tls_violations(STAND_TLS.read_text(encoding="utf-8")) == set()


def test_lifecycle_imports_only_the_standard_library() -> None:
    assert lifecycle_violations(LIFECYCLE.read_text(encoding="utf-8")) == set()


def test_no_runtime_module_imports_test_or_script_tooling() -> None:
    offenders = {
        str(path.relative_to(ROOT)): found
        for path in sorted(RUNTIME.rglob("*.py"))
        if (found := runtime_violations(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


@pytest.mark.parametrize(
    ("check", "source", "violation"),
    [
        (stand_tls_violations, "import cveta2.adapters.cvat.sdk_adapter\n", "cveta2"),
        (stand_tls_violations, "def f() -> None:\n    import urllib3\n", "urllib3"),
        (lifecycle_violations, "from clearml import Task\n", "clearml"),
        (lifecycle_violations, "from tests.integration import stand_tls\n", "tests"),
        (runtime_violations, "from tests.integration import stand_tls\n", "tests"),
        (
            runtime_violations,
            "def f() -> None:\n    import scripts.mutation\n",
            "scripts",
        ),
    ],
)
def test_the_checks_see_absolute_and_nested_imports(
    check: Callable[[str], set[str]], source: str, violation: str
) -> None:
    """The contracts above pass vacuously if a check stops seeing imports."""
    assert violation in check(source)
