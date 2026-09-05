"""Checks that keep the documentation from drifting away from the code.

The `fetch_annotations` examples in README.md survived the method's deletion
because nothing ever compared the docs to the code. These three checks are
that comparison: every documented Python call must match a real signature,
every command/flag/env var/config key must be documented somewhere, and every
relative link and in-page anchor must resolve.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pytest
from pydantic import BaseModel

import cveta2
from cveta2 import config as config_module
from cveta2.cli import CliApp
from cveta2.client import CvatClient

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent

# mutmut runs the suite from `mutants/`, a partial copy of the tree that carries
# `cveta2/` and `tests/` but none of the markdown. There is nothing to check
# there, and reading a file that was never copied would fail the clean-test run
# that gates every mutation.
pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "README.md").exists(),
    reason="documentation tree not present (running from a copied source tree)",
)
USER_DOCS = [REPO_ROOT / "README.md", *sorted((REPO_ROOT / "docs").glob("*.md"))]
ALL_DOCS = [
    *sorted(REPO_ROOT.glob("*.md")),
    *sorted((REPO_ROOT / "docs").glob("*.md")),
    REPO_ROOT / "scripts" / "README.md",
]
AGENT_INSTRUCTIONS = REPO_ROOT / "AGENTS.md"
SKILL_DOCS = sorted(
    (REPO_ROOT / ".claude" / "skills" / "running-integration-tests").glob("*.md")
)
# The integration tests once ran a per-run MinIO/ClearML Compose stack on this
# host with hand-picked ports and a user-derived tag. Every doc that still
# names a piece of it sends a reader to a stack that no longer exists.
RETIRED_STACK_TOKENS = (
    "docker compose",
    "docker-compose",
    "Compose",
    "9989",
    "9990",
    "8880",
    "8881",
    "8882",
    "192.168.65.254",
    "cveta2-tests",
    "nkt-cvat",
    "9988",
    "INTEGRATION_USER",
    "MINIO_PORT",
    "CLEARML_API_PORT",
)

_PYTHON_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)


class _DocumentedCall(NamedTuple):
    """One ``cveta2``/client call lifted out of a fenced example."""

    doc: Path
    block: int
    node: ast.Call
    attribute: str
    owner_name: str

    @property
    def owner(self) -> object:
        return cveta2 if self.owner_name == "cveta2" else CvatClient


_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _user_docs_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in USER_DOCS)


def _heading_slug(heading: str) -> str:
    """Approximate GitHub's anchor slug for a markdown heading."""
    text = re.sub(r"[`*_\[\]()]", "", heading.strip().lower())
    kept = "".join(c for c in text if unicodedata.category(c)[0] in "LN" or c in " -")
    return re.sub(r"\s+", "-", kept.strip())


def _documented_python_calls() -> Iterator[_DocumentedCall]:
    """Yield every ``cveta2.*`` / ``client.*`` call in a documented example."""
    for doc in USER_DOCS:
        for number, code in enumerate(
            _PYTHON_BLOCK.findall(doc.read_text(encoding="utf-8")), start=1
        ):
            for node in ast.walk(ast.parse(code)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute):
                    continue
                base = func.value
                if isinstance(base, ast.Name) and base.id in {
                    "cveta2",
                    "client",
                    "CvatClient",
                }:
                    yield _DocumentedCall(doc, number, node, func.attr, base.id)


class TestDocumentedExamplesMatchTheCode:
    """Every call a reader could copy out of the docs must be callable."""

    def test_every_documented_call_targets_a_real_attribute(self) -> None:
        missing = [
            f"{c.doc.name} block {c.block}: {c.owner_name}.{c.attribute} does not exist"
            for c in _documented_python_calls()
            if getattr(c.owner, c.attribute, None) is None
        ]
        assert not missing, "\n".join(missing)

    def test_every_documented_call_matches_its_signature(self) -> None:
        problems: list[str] = []
        for c in _documented_python_calls():
            function = getattr(c.owner, c.attribute, None)
            if function is None or not callable(function):
                continue
            args = [ast.unparse(a) for a in c.node.args]
            if c.owner is CvatClient and c.owner_name == "client":
                bound = inspect.getattr_static(CvatClient, c.attribute, None)
                if not isinstance(bound, staticmethod):
                    args.insert(0, "<self>")
            keywords = {kw.arg: kw.value for kw in c.node.keywords if kw.arg}
            try:
                inspect.signature(function).bind_partial(*args, **keywords)
            except TypeError as e:
                problems.append(
                    f"{c.doc.name} block {c.block}: {c.attribute}(...) — {e}"
                )
        assert not problems, "\n".join(problems)


class TestTheDocsCoverTheWholeSurface:
    """A command, flag, env var or config key nobody documented is a gap."""

    def test_every_command_and_flag_is_documented(self) -> None:
        docs = _user_docs_text()
        missing: list[str] = []

        def walk(name: str, parser: argparse.ArgumentParser) -> None:
            if name not in docs:
                missing.append(f"command: {name}")
            nested = next(
                (
                    a
                    for a in parser._actions
                    if isinstance(a, argparse._SubParsersAction)
                ),
                None,
            )
            if nested is not None:
                for sub_name, sub_parser in nested.choices.items():
                    walk(f"{name} {sub_name}", sub_parser)
                return
            for action in parser._actions:
                options = [o for o in action.option_strings if o != "--help"]
                if not options or "-h" in action.option_strings:
                    continue
                if not any(o in docs for o in options):
                    missing.append(f"flag: {name} {options[0]}")

        root = CliApp()._parser
        subparsers = next(
            a for a in root._actions if isinstance(a, argparse._SubParsersAction)
        )
        for name, parser in subparsers.choices.items():
            walk(name, parser)
        assert not missing, "\n".join(missing)

    def test_every_env_var_the_code_reads_is_documented(self) -> None:
        docs = _user_docs_text()
        pattern = re.compile(
            r'(?:environ(?:\.get)?|getenv)\(\s*"((?:CVAT|CVETA2)_[A-Z_]+)"'
        )
        names: set[str] = set()
        for source in (REPO_ROOT / "cveta2").rglob("*.py"):
            names |= set(pattern.findall(source.read_text(encoding="utf-8")))
        assert names, "the scan found no env vars at all — the pattern rotted"
        assert sorted(n for n in names if n not in docs) == []

    def test_every_config_field_is_documented(self) -> None:
        docs = _user_docs_text()
        missing: list[str] = []
        for name in dir(config_module):
            obj = getattr(config_module, name)
            if not isinstance(obj, type) or not issubclass(obj, BaseModel):
                continue
            if name.startswith("_") or name in {"BaseModel", "SectionConfig"}:
                continue
            for field in obj.model_fields:
                if field == "projects":  # the mapping key, not a documented name
                    continue
                if not re.search(rf"\b{re.escape(field)}\b", docs):
                    missing.append(f"{name}.{field}")
        assert not missing, "\n".join(missing)


class TestEveryDocumentedLinkResolves:
    """A split that leaves a dead anchor behind is worse than no split."""

    @staticmethod
    def _anchors() -> dict[Path, set[str]]:
        return {
            doc: {
                _heading_slug(h)
                for h in re.findall(
                    r"(?m)^#{1,6}\s+(.*)$", doc.read_text(encoding="utf-8")
                )
            }
            for doc in ALL_DOCS
            if doc.exists()
        }

    def test_no_relative_link_or_anchor_is_dead(self) -> None:
        anchors = self._anchors()
        broken: list[str] = []
        for doc in ALL_DOCS:
            if not doc.exists():
                continue
            for match in _MARKDOWN_LINK.finditer(doc.read_text(encoding="utf-8")):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                relative, _, fragment = target.partition("#")
                resolved = (doc.parent / relative).resolve() if relative else doc
                if relative and not resolved.exists():
                    broken.append(f"{doc.name}: missing file → {target}")
                    continue
                if fragment and fragment not in anchors.get(resolved, set()):
                    broken.append(f"{doc.name}: dead anchor → {target}")
        assert not broken, "\n".join(broken)


@pytest.mark.parametrize(
    "doc",
    [p for p in ALL_DOCS if p.exists() and p.name != "README.md"],
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_only_readme_files_and_user_docs_are_russian(doc: Path) -> None:
    """CONTRIBUTING.md and docs/ are user-facing Russian; the rest is English."""
    russian_is_allowed = doc.name == "CONTRIBUTING.md" or doc.parent.name == "docs"
    if russian_is_allowed:
        return
    assert not re.search(r"[А-Яа-я]", doc.read_text(encoding="utf-8"))


class TestTheAgentInstructionsFollowTheSharedInfraConvention:
    """AGENTS.md is the file, CLAUDE.md its symlink, and the block is present."""

    def test_claude_md_is_a_symlink_to_agents_md(self) -> None:
        claude = REPO_ROOT / "CLAUDE.md"
        assert AGENT_INSTRUCTIONS.is_file()
        assert not AGENT_INSTRUCTIONS.is_symlink()
        assert claude.is_symlink()
        assert claude.readlink() == Path("AGENTS.md")

    def test_agents_md_carries_the_shared_infra_block(self) -> None:
        text = AGENT_INSTRUCTIONS.read_text(encoding="utf-8")
        assert "\n## Shared infra\n" in text
        assert "infra.py newtag --project cveta2 --slug <what>" in text
        assert 'cleanup --prefix "$INFRA_RUN_TAG"' in text


@pytest.mark.parametrize(
    "doc",
    [p for p in [*ALL_DOCS, *SKILL_DOCS] if p.exists() and p.name != "CHANGELOG.md"],
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_no_doc_describes_the_retired_compose_stack(doc: Path) -> None:
    """CHANGELOG.md is release history and may name what was retired."""
    text = doc.read_text(encoding="utf-8")
    found = [token for token in RETIRED_STACK_TOKENS if token in text]
    assert found == [], f"{doc.name} still names the retired per-run stack: {found}"
