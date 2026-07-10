"""Tests for the interactive ``setup`` and ``setup-cache`` commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cveta2.commands import setup as setup_cmd
from cveta2.commands.interactive import _questionary, primitives
from cveta2.commands.setup import run_setup, run_setup_cache
from cveta2.config import CvatConfig, load_cache_config, load_image_cache_config
from cveta2.models import ProjectInfo
from tests.helpers import write_config_yaml

if TYPE_CHECKING:
    from pathlib import Path

# Yes/No tokens the wizard treats as an affirmative confirm answer.
_CONFIRM_YES = {"y", "yes", "да"}


@pytest.fixture(autouse=True)
def interactive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure interactive prompts are allowed regardless of outer env."""
    monkeypatch.delenv("CVETA2_NO_INTERACTIVE", raising=False)


def feed_inputs(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    """Script the interactive text/confirm prompts; return the prompt log.

    Each scripted answer feeds the next ``text``/``confirm`` prompt in order.
    A ``confirm`` prompt consumes a ``y``/``n`` style token and yields a bool.
    """
    prompts: list[str] = []
    answers_iter = iter(answers)

    def fake_text(
        message: str,
        *,
        validate: object = None,  # noqa: ARG001
    ) -> str:
        prompts.append(message)
        return next(answers_iter)

    def fake_confirm(message: str, *, default: bool = False) -> bool:
        prompts.append(message)
        answer = next(answers_iter).strip().lower()
        if not answer:
            return default
        return answer in _CONFIRM_YES

    monkeypatch.setattr(_questionary, "ask_text", fake_text)
    monkeypatch.setattr(_questionary, "ask_confirm", fake_confirm)
    return prompts


def run_setup_with_inputs(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    answers: list[str],
) -> list[str]:
    """Run run_setup with scripted input answers; return prompt log."""
    prompts = feed_inputs(monkeypatch, answers)
    monkeypatch.setattr(primitives, "prompt_password", lambda _prompt: "secret")
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
    config_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={
            "host": "http://localhost:8080",
            "organization": "old-org",
            "username": "user1",
            "password": "pw",
        },
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
    write_config_yaml(
        config_path,
        cvat={"host": "http://localhost:8080"},
        image_cache=image_cache,
    )


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_root_applied_to_all_without_per_project_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    prompts = feed_inputs(monkeypatch, [str(root), "", "", ""])

    run_setup_cache(config_path)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == root / "alpha"
    assert saved.get_cache_dir("beta") == root / "beta"
    assert any("Применить ко всем проектам" in prompt for prompt in prompts)
    assert not any("id=1" in prompt for prompt in prompts)
    assert load_cache_config(config_path).images_root == root


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_root_rejected_falls_back_to_per_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    custom = tmp_path / "custom-alpha"
    prompts = feed_inputs(monkeypatch, [str(root), "n", str(custom), "", "", ""])

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
    prompts = feed_inputs(monkeypatch, ["", str(custom), "", "", ""])

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
    feed_inputs(monkeypatch, [str(root), "", "", ""])

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
    feed_inputs(monkeypatch, [str(root), "", "", ""])

    run_setup_cache(config_path, reset=True)

    saved = load_image_cache_config(config_path)
    assert saved.get_cache_dir("alpha") == root / "alpha"
    assert saved.get_cache_dir("beta") == root / "beta"


@pytest.mark.usefixtures("two_projects")
def test_setup_cache_saves_tasks_root_and_project_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    tasks_root = tmp_path / "tasks"
    answers = [
        str(root),  # image cache root
        "",  # apply to all -> default yes
        str(tasks_root),  # tasks_root
        "y",  # configure per-project settings
        "data/alpha",  # alpha ignored_prefix
        "s3://ml-cache/alpha",  # alpha task_cache_s3
        "",  # beta ignored_prefix (skip)
        "",  # beta task_cache_s3 (skip)
    ]
    feed_inputs(monkeypatch, answers)

    run_setup_cache(config_path)

    cache_cfg = load_cache_config(config_path)
    assert cache_cfg.images_root == root
    assert cache_cfg.tasks_root == tasks_root
    alpha = cache_cfg.for_project("alpha")
    assert alpha.ignored_prefix == "data/alpha"
    assert alpha.task_cache_s3 == "s3://ml-cache/alpha"
    beta = cache_cfg.for_project("beta")
    assert beta.ignored_prefix is None
    assert beta.task_cache_s3 is None
    assert beta.tasks_root == tasks_root
