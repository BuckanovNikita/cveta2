"""Runtime modules must not import unpackaged development tooling."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "cveta2"


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


def runtime_violations(source: str) -> set[str]:
    return {root for root in imported_roots(source) if root in RUNTIME_FORBIDDEN}


def test_no_runtime_module_imports_test_or_script_tooling() -> None:
    offenders = {
        str(path.relative_to(ROOT)): found
        for path in sorted(RUNTIME.rglob("*.py"))
        if (found := runtime_violations(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}
