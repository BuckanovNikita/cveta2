"""Tests for the interactive wizards of ``cveta2 setup``."""

from __future__ import annotations

import os
import resource
import signal
import stat
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import yaml

from cveta2.adapters.config.project import (
    SharedConfigConflictError,
    activate_migration,
    load_global_config,
    load_project_config,
    migration_proposal,
    write_shared_project_fields,
)
from cveta2.adapters.config.settings import CacheConfig, CvatConfig, ImageCacheConfig
from cveta2.domain.errors import Cveta2Error, InteractiveModeRequiredError
from cveta2.domain.managed.overrides import LocalOverridesDisabledError
from cveta2.domain.models import ProjectInfo
from cveta2.interfaces.commands import setup as setup_cmd
from cveta2.interfaces.commands.interactive import _questionary, primitives, wizard
from cveta2.interfaces.commands.setup import run_setup
from tests.helpers import parse_cli_args, write_config_yaml

if TYPE_CHECKING:
    import argparse
    from collections.abc import Iterator
    from pathlib import Path


def _args(config_path: Path, *extra: str) -> argparse.Namespace:
    """Parse a ``setup`` command line with the real CLI parser."""
    return parse_cli_args("setup", "--config", str(config_path), *extra)


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

    def fake_text(message: str, **_kwargs: object) -> str:
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


@pytest.mark.parametrize("argv", [["setup"], ["setup", "--global"]])
def test_setup_commands_refuse_non_interactive_with_wizard_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    """The top-level guard names the same hint the wizard prompts would."""
    monkeypatch.setenv("CVETA2_NO_INTERACTIVE", "true")
    with pytest.raises(InteractiveModeRequiredError) as excinfo:
        run_setup(parse_cli_args(*argv, "--config", str(tmp_path / "config.yaml")))
    assert str(excinfo.value).endswith(wizard.SETUP_HINT)


def patch_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(primitives, "prompt_password", lambda _prompt: "secret")


def test_setup_wizard_reads_projects_beside_custom_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "profile" / "config.yaml"
    config_path.parent.mkdir()
    seen: list[Path] = []

    def load_projects(path: Path) -> list[ProjectInfo]:
        seen.append(path)
        return [ProjectInfo(id=1, name="alpha")]

    monkeypatch.setattr(setup_cmd, "load_projects_cache", load_projects)
    patch_password(monkeypatch)
    # Unattached: host, organization slug, username, no global file; then cache root, alpha, tasks root.
    feed_inputs(monkeypatch, ["", "acme", "user1", "", "", "", ""])

    run_setup(_args(config_path))

    assert seen == [config_path.parent / "projects.yaml"]


# Unattached wizard answers after the credentials: no global file, no cache root, alpha's path, tasks root.
_SKIPPED_CACHE = ["", "", "", ""]


def run_setup_with_inputs(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
    answers: list[str],
) -> list[str]:
    """Run the personal wizard with scripted credential answers; skip the rest."""
    prompts = feed_inputs(monkeypatch, [*answers, *_SKIPPED_CACHE])
    monkeypatch.setattr(setup_cmd, "load_projects_cache", lambda _path: [ProjectInfo(id=1, name="alpha")])
    patch_password(monkeypatch)
    run_setup(_args(config_path))
    return prompts


def test_setup_empty_org_confirmed_saves_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    prompts = run_setup_with_inputs(monkeypatch, config_path, ["", "", "y", "user1"])

    saved = CvatConfig.from_file(config_path)
    assert saved.organization is None
    assert saved.username == "user1"
    assert any("нет организации" in prompt for prompt in prompts)
    assert not any("необязательно" in prompt for prompt in prompts)


def test_setup_empty_org_rejected_reprompts_until_slug(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    prompts = run_setup_with_inputs(monkeypatch, config_path, ["", "", "n", "acme", "user1"])

    saved = CvatConfig.from_file(config_path)
    assert saved.organization == "acme"
    slug_prompts = [prompt for prompt in prompts if prompt.startswith("Slug")]
    assert len(slug_prompts) == 2


def test_setup_direct_org_slug_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    prompts = run_setup_with_inputs(monkeypatch, config_path, ["", "acme", "user1"])

    saved = CvatConfig.from_file(config_path)
    assert saved.organization == "acme"
    assert not any("нет организации" in prompt for prompt in prompts)


def test_setup_existing_org_kept_on_enter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_setup_rerun_keeps_existing_request_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={
            "host": "http://localhost:8080",
            "organization": "old-org",
            "username": "user1",
            "password": "pw",
            "request_timeout": 300,
        },
    )
    run_setup_with_inputs(monkeypatch, config_path, ["", "", ""])

    saved = CvatConfig.from_file(config_path)
    assert saved.request_timeout == 300
    assert saved.host == "http://localhost:8080"
    assert saved.organization == "old-org"
    assert saved.username == "user1"


@pytest.fixture
def two_projects(monkeypatch: pytest.MonkeyPatch) -> list[ProjectInfo]:
    projects = [ProjectInfo(id=1, name="alpha"), ProjectInfo(id=2, name="beta")]
    monkeypatch.setattr(setup_cmd, "load_projects_cache", lambda *_args: projects)
    return projects


def write_cache_config(config_path: Path, image_cache: dict[str, str]) -> None:
    write_config_yaml(
        config_path,
        cvat={"host": "http://localhost:8080"},
        image_cache=image_cache,
    )
    write_config_yaml(
        config_path.parent / "projects.yaml",
        organizations=[
            {
                "slug": "",
                "projects": [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}],
            }
        ],
    )
    activate_migration(migration_proposal(config_path))


def run_wizard(monkeypatch: pytest.MonkeyPatch, config_path: Path, answers: list[str], *extra: str) -> list[str]:
    """Run ``setup`` without option flags; the password prompt is patched."""
    prompts = feed_inputs(monkeypatch, answers)
    patch_password(monkeypatch)
    run_setup(_args(config_path, *extra))
    return prompts


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_applies_cache_root_to_all_projects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    tasks_root = tmp_path / "tasks"
    # Username, cache root, apply to all (default yes), tasks root.
    prompts = run_wizard(monkeypatch, config_path, ["", str(root), "", str(tasks_root)])

    saved = ImageCacheConfig.load(config_path)
    assert saved.get_cache_dir("alpha") == root / "alpha"
    assert saved.get_cache_dir("beta") == root / "beta"
    assert any("Применить ко всем проектам" in prompt for prompt in prompts)
    assert not any("id=1" in prompt for prompt in prompts)
    cache = CacheConfig.load(config_path)
    assert cache.images_root == root
    assert cache.tasks_root == tasks_root


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_cache_root_rejected_falls_back_to_per_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    root = tmp_path / "cache"
    custom = tmp_path / "custom-alpha"
    prompts = run_wizard(monkeypatch, config_path, ["", str(root), "n", str(custom), "", ""])

    saved = ImageCacheConfig.load(config_path)
    assert saved.get_cache_dir("alpha") == custom
    assert saved.get_cache_dir("beta") == root / "beta"
    assert any("id=1" in prompt for prompt in prompts)
    assert any("id=2" in prompt for prompt in prompts)


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_without_cache_root_asks_per_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    custom = tmp_path / "custom-alpha"
    prompts = run_wizard(monkeypatch, config_path, ["", "", str(custom), "", ""])

    saved = ImageCacheConfig.load(config_path)
    assert saved.get_cache_dir("alpha") == custom
    assert saved.get_cache_dir("beta") is None
    assert not any("Применить ко всем проектам" in prompt for prompt in prompts)


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_keeps_existing_cache_paths_without_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    existing = tmp_path / "existing-alpha"
    write_cache_config(config_path, {"alpha": str(existing)})
    root = tmp_path / "cache"
    run_wizard(monkeypatch, config_path, ["", str(root), "", ""])

    saved = ImageCacheConfig.load(config_path)
    assert saved.get_cache_dir("alpha") == existing
    assert saved.get_cache_dir("beta") == root / "beta"


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_reset_reasks_cache_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {"alpha": str(tmp_path / "existing-alpha")})
    root = tmp_path / "cache"
    run_wizard(monkeypatch, config_path, ["", str(root), "", ""], "--reset")

    saved = ImageCacheConfig.load(config_path)
    assert saved.get_cache_dir("alpha") == root / "alpha"
    assert saved.get_cache_dir("beta") == root / "beta"


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_asks_credentials_then_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    prompts = run_wizard(monkeypatch, config_path, ["user1", "", "", "", ""])

    def first(fragment: str) -> int:
        return next(index for index, prompt in enumerate(prompts) if fragment in prompt)

    assert first("Имя пользователя") < first("Корневая директория кэша") < first("Локальный кэш аннотаций задач")
    assert not any("игнорируемый префикс" in prompt for prompt in prompts)
    assert CvatConfig.from_file(config_path).username == "user1"


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_project_limits_cache_prompts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})
    custom = tmp_path / "custom-beta"
    prompts = run_wizard(monkeypatch, config_path, ["", "", str(custom), ""], "-p", "beta")

    saved = ImageCacheConfig.load(config_path)
    assert saved.get_cache_dir("beta") == custom
    assert saved.get_cache_dir("alpha") is None
    assert any("id=2" in prompt for prompt in prompts)
    assert not any("id=1" in prompt for prompt in prompts)


@pytest.mark.usefixtures("two_projects")
def test_setup_wizard_refuses_unknown_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_cache_config(config_path, {})

    with pytest.raises(Cveta2Error, match="gamma"):
        run_wizard(monkeypatch, config_path, [""], "-p", "gamma")


# Per project: ignored prefix, task cache S3, ClearML project, dataset name, class API URL, excluded classes.
_ALPHA_TEAM_ANSWERS = [
    "data/alpha",
    "s3://ml-cache/alpha",
    "Retail/Datasets",
    "alpha-ds",
    "https://classes.example.com/api",
    "12, 13",
]
_KEEP_ALL = ["", "", "", "", "", ""]


def test_global_wizard_writes_team_options(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    write_cache_config(cfg, {})
    personal = cfg.read_bytes()
    beta_before = load_global_config(cfg).projects["beta"]

    run_wizard(monkeypatch, cfg, [*_ALPHA_TEAM_ANSWERS, *_KEEP_ALL], "--global")

    loaded = load_global_config(cfg)
    alpha = loaded.projects["alpha"]
    assert alpha.ignored_prefix == "data/alpha"
    assert alpha.task_cache_s3 == "s3://ml-cache/alpha"
    assert alpha.publication is not None
    assert alpha.publication.clearml.project == "Retail/Datasets"
    assert alpha.publication.clearml.dataset == "alpha-ds"
    assert alpha.publication.api_url == "https://classes.example.com/api"
    assert alpha.publication.empty_classes == [12, 13]
    assert loaded.projects["beta"] == beta_before
    assert cfg.read_bytes() == personal


def test_global_wizard_adds_a_new_project_definition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    write_cache_config(cfg, {})
    known = [ProjectInfo(id=1, name="alpha"), ProjectInfo(id=2, name="beta"), ProjectInfo(id=3, name="gamma")]
    monkeypatch.setattr(setup_cmd, "load_projects_cache", lambda _path: known)

    run_wizard(monkeypatch, cfg, _ALPHA_TEAM_ANSWERS, "--global", "-p", "3")

    gamma = load_global_config(cfg).projects["gamma"]
    assert (gamma.id, gamma.name, gamma.ignored_prefix) == (3, "gamma", "data/alpha")
    assert gamma.publication is not None
    assert gamma.publication.clearml.dataset == "alpha-ds"
    assert gamma.publication.empty_classes == [12, 13]


def test_global_wizard_without_changes_leaves_the_file_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    write_cache_config(cfg, {})
    global_file = tmp_path / "project-config.yaml"
    global_file.write_text(f"# team file\n{global_file.read_text(encoding='utf-8')}", encoding="utf-8")
    before = global_file.read_bytes()

    run_wizard(monkeypatch, cfg, [*_KEEP_ALL, *_KEEP_ALL], "--global")

    assert global_file.read_bytes() == before


def test_global_wizard_partial_publication_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    write_cache_config(cfg, {})
    global_file = tmp_path / "project-config.yaml"
    before = global_file.read_bytes()

    with pytest.raises(Cveta2Error) as caught:
        run_wizard(monkeypatch, cfg, ["", "", "Retail/Datasets", "", "", ""], "--global", "-p", "alpha")

    assert "--dataset-name" in str(caught.value)
    assert "--api-url" in str(caught.value)
    assert "--clearml-project" not in str(caught.value)
    assert global_file.read_bytes() == before


def test_global_wizard_refuses_concurrent_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    write_cache_config(cfg, {})

    def task_cache_s3(project_name: str, default: str | None) -> str | None:
        # Another writer changes the leaf this run is about to change.
        write_shared_project_fields(cfg, {project_name: {"ignored_prefix": f"other/{project_name}"}})
        return default

    monkeypatch.setattr(wizard, "prompt_task_cache_s3", task_cache_s3)
    # The task cache prompt is patched: five answers remain for alpha.
    answers = ["data/alpha", "", "", "", ""]

    with pytest.raises(SharedConfigConflictError):
        run_wizard(monkeypatch, cfg, answers, "--global", "-p", "alpha")

    assert load_global_config(cfg).projects["alpha"].ignored_prefix == "other/alpha"


def test_global_wizard_without_global_file_shows_creation_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = write_config_yaml(tmp_path / "config.yaml", cvat={"host": "http://localhost:8080"})

    with pytest.raises(Cveta2Error, match="cveta2 setup --global --global-config PATH --host URL"):
        run_wizard(monkeypatch, cfg, [], "--global")


def test_global_wizard_works_while_overrides_are_not_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The team wizard reads the raw global file, so disallowed overrides do not lock it out."""
    cfg = tmp_path / "config.yaml"
    write_cache_config(cfg, {})
    personal = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    personal["overrides"] = {"projects": {"alpha": {"publication": {"clearml": {"dataset": "mine"}}}}}
    cfg.write_text(yaml.safe_dump(personal), encoding="utf-8")

    run_wizard(monkeypatch, cfg, _ALPHA_TEAM_ANSWERS, "--global", "-p", "alpha")

    publication = load_global_config(cfg).projects["alpha"].publication
    assert publication is not None
    assert publication.clearml.dataset == "alpha-ds"
    # The overrides stay; still not allowed by the global file.
    assert "overrides" in yaml.safe_load(cfg.read_text(encoding="utf-8"))
    with pytest.raises(LocalOverridesDisabledError):
        load_project_config(cfg)


@pytest.fixture
def default_umask() -> Iterator[None]:
    """Run under the common 022 umask that leaves new files world-readable."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.mark.usefixtures("default_umask")
def test_setup_saves_the_personal_config_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    run_setup_with_inputs(monkeypatch, config_path, ["", "acme", "user1"])

    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    assert CvatConfig.from_file(config_path).password == "secret"


def test_password_config_loads_on_platforms_without_posix_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "personal.yaml"
    path.write_text("cvat: {username: alice, password: secret}\n", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setattr("cveta2.adapters.config.settings.os", SimpleNamespace(name="nt"))

    assert CvatConfig.from_file(path).password == "secret"


@pytest.mark.usefixtures("default_umask")
def test_existing_world_readable_password_file_is_tightened_on_load(tmp_path: Path) -> None:
    config_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080", "username": "user1", "password": "pw"},
    )
    config_path.chmod(0o644)

    assert CvatConfig.load(config_path).password == "pw"

    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_failed_personal_save_keeps_the_previous_file(tmp_path: Path) -> None:
    config_path = write_config_yaml(
        tmp_path / "config.yaml",
        cvat={"host": "http://localhost:8080", "username": "user1", "password": "pw"},
        image_cache={"alpha": "/data/alpha"},
    )
    original = config_path.read_bytes()
    oversized = CvatConfig(host="http://localhost:8080", username="user1", password="x" * 65536)
    # The file-size limit makes the kernel refuse the write part-way, like a full disk.
    previous_handler = signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    previous_limit = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (4096, previous_limit[1]))
    try:
        with pytest.raises(Cveta2Error) as caught:
            oversized.save_to_file(config_path)
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, previous_limit)
        signal.signal(signal.SIGXFSZ, previous_handler)

    assert str(config_path) in str(caught.value)
    assert config_path.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == ["config.yaml"]


def test_attached_setup_does_not_persist_one_run_environment_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shared = write_config_yaml(
        tmp_path / "project-config.yaml",
        schema_version=1,
        cvat={"host": "https://cvat.example", "organization": None},
        projects={},
        datasets={},
    )
    config_path = write_config_yaml(
        tmp_path / "config.yaml",
        schema_version=1,
        project_config=str(shared),
        cvat={"username": "alice", "password": "file-password"},
    )
    monkeypatch.setenv("CVAT_PASSWORD", "one-run-token")
    monkeypatch.setenv("CVETA2_DATA_TIMEOUT", "7")
    # Username, then no cache root, alpha's path and tasks root.
    feed_inputs(monkeypatch, ["", "", "", ""])
    monkeypatch.setattr(setup_cmd, "load_projects_cache", lambda _path: [ProjectInfo(id=1, name="alpha")])
    monkeypatch.setattr(primitives, "prompt_password", lambda _prompt: "")

    run_setup(_args(config_path))

    saved = CvatConfig.from_file(config_path)
    assert saved.password == "file-password"
    assert saved.request_timeout is None
    assert saved.username == "alice"


def _closed_stdin(*_args: object, **_kwargs: object) -> None:
    raise EOFError


@pytest.mark.parametrize("seam", ["prompt", "password"])
def test_setup_with_closed_stdin_is_a_typed_interactive_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    """A cron job that forgot CVETA2_NO_INTERACTIVE gets the typed hint, not EOFError."""
    if seam == "prompt":
        monkeypatch.setattr("questionary.text", _closed_stdin)
    else:
        feed_inputs(monkeypatch, ["", "acme", "user1"])
        monkeypatch.setattr("getpass.getpass", _closed_stdin)

    with pytest.raises(InteractiveModeRequiredError) as caught:
        run_setup(_args(tmp_path / "config.yaml"))

    assert "CVETA2_NO_INTERACTIVE=true." not in str(caught.value)
    assert not (tmp_path / "config.yaml").exists()
