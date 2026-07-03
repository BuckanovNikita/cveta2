"""Tests for the interactive ``setup`` and ``setup-cache`` commands."""

from __future__ import annotations

import getpass
from typing import TYPE_CHECKING

import pytest
import yaml

from cveta2.commands import setup as setup_cmd
from cveta2.commands.setup import run_setup, run_setup_cache
from cveta2.config import CvatConfig, load_image_cache_config
from cveta2.models import ProjectInfo

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def interactive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure interactive prompts are allowed regardless of outer env."""
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)


def feed_inputs(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    """Replace builtins.input with scripted answers; return prompt log."""
    prompts: list[str] = []
    answers_iter = iter(answers)

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers_iter)

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def run_setup_with_inputs(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    answers: list[str],
) -> list[str]:
    """Run run_setup with scripted input answers; return prompt log."""
    prompts = feed_inputs(monkeypatch, answers)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "secret")
    run_setup(config_path)
    return prompts


def test_setup_empty_org_confirmed_saves_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts = run_setup_with_inputs(monkeypatch, config_path, ["", "", "y", "user1"])

    saved = CvatConfig.from_file(config_path)
    assert saved.organization is None
    assert saved.username == "user1"
    assert any("нет организации" in prompt for prompt in prompts)
    assert not any("необязательно" in prompt for prompt in prompts)


def test_setup_empty_org_rejected_reprompts_until_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts = run_setup_with_inputs(
        monkeypatch, config_path, ["", "", "n", "acme", "user1"]
    )

    saved = CvatConfig.from_file(config_path)
    assert saved.organization == "acme"
    slug_prompts = [prompt for prompt in prompts if prompt.startswith("Slug")]
    assert len(slug_prompts) == 2


def test_setup_direct_org_slug_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts = run_setup_with_inputs(monkeypatch, config_path, ["", "acme", "user1"])

    saved = CvatConfig.from_file(config_path)
    assert saved.organization == "acme"
    assert not any("нет организации" in prompt for prompt in prompts)


def test_setup_existing_org_kept_on_enter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {
                    "host": "http://localhost:8080",
                    "organization": "old-org",
                    "username": "user1",
                    "password": "pw",
                }
            }
        ),
        encoding="utf-8",
    )
    prompts = run_setup_with_inputs(monkeypatch, config_path, ["", "", ""])

    saved = CvatConfig.from_file(config_path)
    assert saved.organization == "old-org"
    assert not any("нет организации" in prompt for prompt in prompts)


@pytest.fixture
def two_projects(monkeypatch: pytest.MonkeyPatch) -> list[ProjectInfo]:
    projects = [ProjectInfo(id=1, name="alpha"), ProjectInfo(id=2, name="beta")]
    monkeypatch.setattr(setup_cmd, "load_projects_cache", lambda: projects)
    return projects


def write_cache_config(config_path: Path, image_cache: dict[str, str]) -> None:
    config_path.write_text(
        yaml.safe_dump(
            {
                "cvat": {"host": "http://localhost:8080"},
                "image_cache": image_cache,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_root_applied_to_all_without_per_project_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    prompts = feed_inputs(monkeypatch, [str(root), ""])

    run_setup_cache(config_path)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == root / "alpha"
    assert saved.get_cache_dir("beta") == root / "beta"
    assert any("Применить ко всем проектам" in prompt for prompt in prompts)
    assert not any("id=1" in prompt for prompt in prompts)


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_root_rejected_falls_back_to_per_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    custom = tmp_path / "custom-alpha"
    prompts = feed_inputs(monkeypatch, [str(root), "n", str(custom), ""])

    run_setup_cache(config_path)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == custom
    assert saved.get_cache_dir("beta") == root / "beta"
    assert any("id=1" in prompt for prompt in prompts)
    assert any("id=2" in prompt for prompt in prompts)


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_no_root_keeps_per_project_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    custom = tmp_path / "custom-alpha"
    prompts = feed_inputs(monkeypatch, ["", str(custom), ""])

    run_setup_cache(config_path)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == custom
    assert saved.get_cache_dir("beta") is None
    assert not any("Применить ко всем проектам" in prompt for prompt in prompts)


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_root_apply_keeps_existing_paths_without_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    existing = tmp_path / "existing-alpha"
    write_cache_config(config_path, {"alpha": str(existing)})
    root = tmp_path / "cache"
    feed_inputs(monkeypatch, [str(root), ""])

    run_setup_cache(config_path)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == existing
    assert saved.get_cache_dir("beta") == root / "beta"


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_root_apply_overrides_existing_paths_with_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {"alpha": str(tmp_path / "existing-alpha")})
    root = tmp_path / "cache"
    feed_inputs(monkeypatch, [str(root), ""])

    run_setup_cache(config_path, reset=True)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == root / "alpha"
    assert saved.get_cache_dir("beta") == root / "beta"
