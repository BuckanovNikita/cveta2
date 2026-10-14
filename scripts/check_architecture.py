"""Check canonical effect ownership beyond import-linter's dependency graph.

This is a source-level guard for known Python effect APIs, not a Python sandbox.
Ports remain responsible for effects: named filesystem methods on a workflow
port are allowed only when their names describe workflow operations.
"""

import ast
import sys
from pathlib import Path

INNER_LAYERS = {"domain", "application"}
CANONICAL_LAYERS = INNER_LAYERS | {"adapters", "composition", "interfaces"}
EFFECT_IMPORTS = {
    "os",
    "io",
    "shutil",
    "tempfile",
    "glob",
    "socket",
    "subprocess",
    "threading",
    "multiprocessing",
    "concurrent",
    "requests",
    "httpx",
    "boto3",
    "botocore",
    "cvat_sdk",
    "clearml",
    "questionary",
}
EFFECT_CALLS = {
    "open",
    "builtins.open",
    "exec",
    "eval",
    "__import__",
    "importlib.import_module",
    "time.time",
    "time.monotonic",
    "time.perf_counter",
    "time.sleep",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "datetime.date.today",
}
FILE_METHODS = {
    "open",
    "read_text",
    "read_bytes",
    "write_text",
    "write_bytes",
    "mkdir",
    "rmdir",
    "unlink",
    "resolve",
    "absolute",
    "expanduser",
    "exists",
    "is_file",
    "is_dir",
    "is_symlink",
    "stat",
    "lstat",
    "iterdir",
    "glob",
    "rglob",
    "touch",
    "chmod",
    "symlink_to",
    "hardlink_to",
    "readlink",
    "home",
    "cwd",
}
PANDAS_IO = {
    "read_csv",
    "read_json",
    "read_pickle",
    "read_parquet",
    "read_excel",
    "read_feather",
    "read_hdf",
    "read_sql",
    "to_csv",
    "to_pickle",
    "to_parquet",
    "to_excel",
    "to_feather",
    "to_hdf",
    "to_sql",
}


def _qualified(node: ast.expr, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return f"{_qualified(node.value, aliases)}.{node.attr}"
    return ""


def _imports(node: ast.Import | ast.ImportFrom) -> list[tuple[str, str]]:
    if isinstance(node, ast.Import):
        return [(a.asname or a.name.split(".")[0], a.name) for a in node.names]
    return [(a.asname or a.name, f"{node.module or ''}.{a.name}") for a in node.names]


def _import_context(
    tree: ast.Module, module: str, *, inner: bool
) -> tuple[dict[str, str], list[str]]:
    aliases: dict[str, str] = {}
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for local, name in _imports(node):
            aliases[local] = name
            if inner and (
                name.split(".")[0] in EFFECT_IMPORTS
                or name.startswith("urllib.request")
            ):
                violations.append(f"{module}:{node.lineno}: effect import {name}")
        root_import = (
            node.module == "cveta2"
            if isinstance(node, ast.ImportFrom)
            else any(a.name == "cveta2" for a in node.names)
        )
        if root_import:
            violations.append(
                f"{module}:{node.lineno}: canonical import of public root"
            )
    return aliases, violations


def _path_expression(node: ast.expr, aliases: dict[str, str], paths: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in paths or aliases.get(node.id) == "pathlib.Path"
    if isinstance(node, ast.Call):
        return _qualified(node.func, aliases) == "pathlib.Path"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _path_expression(node.left, aliases, paths)
    if isinstance(node, ast.Attribute):
        return _path_expression(node.value, aliases, paths)
    return False


def _path_annotation(annotation: ast.expr | None, aliases: dict[str, str]) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        annotation = ast.parse(annotation.value, mode="eval").body
    return any(
        _qualified(node, aliases) == "pathlib.Path"
        for node in ast.walk(annotation)
        if isinstance(node, (ast.Name, ast.Attribute))
    )


def _effect_aliases(tree: ast.Module, aliases: dict[str, str]) -> set[str]:
    paths = {
        node.arg
        for node in ast.walk(tree)
        if isinstance(node, ast.arg) and _path_annotation(node.annotation, aliases)
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _path_annotation(node.annotation, aliases)
        ):
            paths.add(node.target.id)
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if _path_expression(node.value, aliases, paths):
                paths.add(target.id)
            if isinstance(node.value, (ast.Name, ast.Attribute)):
                aliases[target.id] = _qualified(node.value, aliases)
    return paths


def _effect_call(
    call: ast.Call, aliases: dict[str, str], paths: set[str]
) -> str | None:
    name = _qualified(call.func, aliases)
    leaf = name.rsplit(".", 1)[-1]
    if name in EFFECT_CALLS or leaf in FILE_METHODS | PANDAS_IO:
        return name or leaf
    # DataFrame.rename and str.replace are pure; Path operations with these
    # names are effects, identified from constructors, typed arguments or joins.
    if (
        leaf in {"rename", "replace"}
        and isinstance(call.func, ast.Attribute)
        and _path_expression(call.func.value, aliases, paths)
    ):
        return name
    return None


def inspect_source(source: str, module: str) -> list[str]:
    """Return locations for canonical imports and known effect calls."""
    tree = ast.parse(source)
    parts = module.split(".")
    layer = parts[1] if len(parts) > 1 else ""
    if layer not in CANONICAL_LAYERS:
        return []
    inner = layer in INNER_LAYERS
    aliases, violations = _import_context(tree, module, inner=inner)
    if inner:
        paths = _effect_aliases(tree, aliases)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and (
                effect := _effect_call(node, aliases, paths)
            ):
                violations.append(f"{module}:{node.lineno}: external effect {effect}")
    return violations


def check_tree(package: Path) -> list[str]:
    """Inspect canonical modules without importing application code."""
    violations: list[str] = []
    for path in sorted(package.rglob("*.py")):
        module = ".".join(path.relative_to(package.parent).with_suffix("").parts)
        violations.extend(inspect_source(path.read_text(), module))
    return violations


def main() -> int:
    """Report ownership violations for the commit gate."""
    violations = check_tree(Path(__file__).resolve().parents[1] / "cveta2")
    for violation in violations:
        print(violation)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
