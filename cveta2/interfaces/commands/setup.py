"""Implementation of the ``cveta2 setup`` command: option flags, ``--list`` and the wizards."""

import copy
import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from loguru import logger
from pydantic import ValidationError

from cveta2.application.use_cases.resolve import resolve_project_spec
from cveta2.composition.configuration import (
    PERSONAL_WORKSPACE_TITLE,
    CacheConfig,
    CvatConfig,
    ImageCacheConfig,
    LocalOverrides,
    activate_migration,
    apply_local_overrides,
    attach_existing_project_config,
    cache_dir_for_project,
    create_global_config,
    find_project_key,
    get_projects_cache_path,
    global_config_from_env,
    list_configuration,
    load_global_config,
    load_projects_cache,
    migration_proposal,
    optional_global_config,
    optional_project_config,
    project_config_path,
    project_key_for,
    read_config,
    read_local_overrides,
    recover_migration,
    require_interactive,
    update_org_projects,
    write_local_overrides,
    write_shared_project_fields,
)
from cveta2.domain.errors import Cveta2Error, ProjectNotFoundError
from cveta2.domain.managed.models import CvatIdentity, ManagedError, ProjectDefinition
from cveta2.domain.models import ProjectInfo
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    config_path_from_args,
    global_config_from_args,
)
from cveta2.interfaces.commands._parsers import add_config_arg, add_global_config_arg, add_list_arg, add_project_arg
from cveta2.interfaces.commands.interactive import primitives, wizard

if TYPE_CHECKING:
    import argparse

    from cveta2.domain.managed.models import ProjectConfig


Scope = Literal["personal", "identity", "switch", "team", "publication"]


@dataclass(frozen=True)
class SetupOption:
    """One option flag of ``cveta2 setup`` and the configuration key it writes.

    ``scope`` decides the file: ``personal`` values go to the personal file;
    ``identity`` (CVAT host and organization) to the global file, or to the
    personal file when no global file is attached; ``switch`` and ``team`` to
    the global file only; ``publication`` to the global file, or to a local
    override without ``--global``. ``key`` is dotted: a personal key, a
    top-level global key, or a path under ``projects.<key>``.
    """

    name: str
    dest: str
    scope: Scope
    key: str
    needs_project: bool

    @property
    def flag(self) -> str:
        """The option as it is typed."""
        return f"--{self.name}"


SETUP_OPTIONS: tuple[SetupOption, ...] = (
    SetupOption("username", "username", "personal", "cvat.username", needs_project=False),
    SetupOption("password", "password", "personal", "cvat.password", needs_project=False),
    SetupOption("images-root", "images_root", "personal", "cache.images_root", needs_project=False),
    SetupOption("tasks-root", "tasks_root", "personal", "cache.tasks_root", needs_project=False),
    SetupOption("images-dir", "images_dir", "personal", "image_cache", needs_project=True),
    SetupOption("host", "host", "identity", "cvat.host", needs_project=False),
    SetupOption("organization", "organization", "identity", "cvat.organization", needs_project=False),
    SetupOption("local-overrides", "local_overrides", "switch", "local_overrides", needs_project=False),
    SetupOption("sync-root", "sync_root", "team", "sync_root", needs_project=True),
    SetupOption("ignored-prefix", "ignored_prefix", "team", "ignored_prefix", needs_project=True),
    SetupOption("task-cache-s3", "task_cache_s3", "team", "task_cache_s3", needs_project=True),
    SetupOption("clearml-project", "clearml_project", "publication", "publication.clearml.project", needs_project=True),
    SetupOption("dataset-name", "dataset_name", "publication", "publication.clearml.dataset", needs_project=True),
    SetupOption("output-uri", "output_uri", "publication", "publication.clearml.output_uri", needs_project=True),
    SetupOption("api-url", "api_url", "publication", "publication.api_url", needs_project=True),
    SetupOption("empty-class", "empty_classes", "publication", "publication.empty_classes", needs_project=True),
    SetupOption("s3-root", "s3_roots", "publication", "publication.s3_roots", needs_project=True),
)
# ``--unset publication`` removes a project's whole publication block; it is no option flag.
_WHOLE_PUBLICATION = SetupOption("publication", "unset", "publication", "publication", needs_project=True)
UNSET_NAMES: tuple[str, ...] = (*(option.name for option in SETUP_OPTIONS), "publication")
_BY_NAME = {option.name: option for option in (*SETUP_OPTIONS, _WHOLE_PUBLICATION)}

_ORIGIN_RU = {
    "default": "по умолчанию",
    "personal": "личная",
    "global": "общая",
    "override": "локальное переопределение",
    "environment": "окружение",
}
_NOT_APPLIED = "не применяется: общая конфигурация не разрешает переопределения"

_CREATION_FORM = "cveta2 setup --global --global-config PATH --host URL [--organization SLUG]"
_HIDDEN_PROMPT_HINT = "Задайте пароль через CVAT_PASSWORD или запустите cveta2 setup --password в терминале."

# A requested change: the option and its value, ``None`` for ``--unset``.
_Change = tuple[SetupOption, object]


def configure_setup(parser: "argparse.ArgumentParser") -> None:
    """Declare the wizard, the attach-only form and the option flags of ``setup``."""
    add_config_arg(parser)
    add_global_config_arg(parser)
    parser.add_argument(
        "--migrate-config",
        action="store_true",
        help="Проверить и разделить прежнюю конфигурацию.",
    )
    parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Записывать в общую конфигурацию команды, а не в личную.",
    )
    add_project_arg(parser, "Проект CVAT: ключ общей конфигурации, имя или ID.")
    add_list_arg(parser, "Показать итоговую конфигурацию и откуда взято каждое значение; ничего не записывает.")
    parser.add_argument(
        "--unset",
        dest="unset",
        nargs="+",
        action="extend",
        choices=UNSET_NAMES,
        metavar="OPTION",
        help=f"Удалить значения из выбранного файла: {', '.join(UNSET_NAMES)}.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Мастер кэша: заново предложить путь каждого проекта, не глядя на сохранённые.",
    )
    _add_option_flags(parser)


def _add_option_flags(parser: "argparse.ArgumentParser") -> None:
    """Declare one flag per entry of :data:`SETUP_OPTIONS`."""
    options = parser.add_argument_group("значения (без вопросов; --unset удаляет)")
    options.add_argument("--username", help="Имя пользователя CVAT (личная конфигурация).")
    options.add_argument(
        "--password",
        action="store_true",
        help="Спросить пароль CVAT скрытым вводом; в командной строке пароль не передаётся.",
    )
    options.add_argument("--images-root", type=Path, help="Корень кэша изображений (cache.images_root).")
    options.add_argument("--tasks-root", type=Path, help="Корень кэша аннотаций (cache.tasks_root).")
    options.add_argument("--images-dir", type=Path, help="Папка изображений проекта --project (image_cache).")
    options.add_argument("--host", help="Адрес CVAT (cvat.host).")
    options.add_argument("--organization", help="Организация CVAT (cvat.organization).")
    options.add_argument(
        "--local-overrides", choices=("on", "off"), help="Разрешить локальные переопределения (с --global)."
    )
    options.add_argument("--sync-root", help="S3-корень изображений проекта (с --global).")
    options.add_argument("--ignored-prefix", help="Игнорируемый префикс путей проекта (с --global).")
    options.add_argument("--task-cache-s3", help="S3-кэш аннотаций проекта (с --global).")
    options.add_argument("--clearml-project", help="Проект ClearML для публикации.")
    options.add_argument("--dataset-name", help="Имя датасета ClearML.")
    options.add_argument("--output-uri", help="Хранилище файлов датасета ClearML.")
    options.add_argument("--api-url", help="URL API классов.")
    options.add_argument(
        "--empty-class",
        dest="empty_classes",
        type=int,
        action="append",
        help="ID исключённого класса; повторяется, заменяет весь список.",
    )
    options.add_argument(
        "--s3-root",
        dest="s3_roots",
        action="append",
        help="S3-корень изображений публикации; повторяется, заменяет весь список.",
    )


def _given(args: "argparse.Namespace") -> list[_Change]:
    """Return the option flags given on the command line, with their values."""
    given: list[_Change] = []
    for option in SETUP_OPTIONS:
        value = getattr(args, option.dest, None)
        if value is not None and value is not False:
            given.append((option, value))
    return given


def _unset(args: "argparse.Namespace") -> list[SetupOption]:
    """Return the ``--unset`` operands, in order and without repeats."""
    return [_BY_NAME[name] for name in dict.fromkeys(getattr(args, "unset", None) or ())]


def _check_migration_alone(args: "argparse.Namespace") -> None:
    if args.migrate_config and (
        _given(args) or _unset(args) or args.global_scope or args.project is not None or args.reset
    ):
        raise Cveta2Error(
            "--migrate-config выполняется отдельно: уберите остальные параметры, кроме --config и --global-config."
        )


def _check_list_alone(args: "argparse.Namespace") -> None:
    """Refuse ``--list`` with anything that writes: it only shows the configuration."""
    if not args.list_only:
        return
    given = _given(args)
    writing = (
        (given[0][0].flag if given else None)
        or ("--unset" if args.unset else None)
        or ("--reset" if args.reset else None)
        or ("--global" if args.global_scope else None)
        or ("--migrate-config" if args.migrate_config else None)
    )
    if writing is not None:
        raise Cveta2Error(f"--list только показывает настройки и не сочетается с {writing}; уберите {writing}.")


def _first(requested: list[SetupOption], scopes: tuple[str, ...]) -> SetupOption | None:
    return next((option for option in requested if option.scope in scopes), None)


def validate_setup_request(args: "argparse.Namespace", *, attached: bool) -> None:  # noqa: C901 - one check per row of the documented error table
    """Refuse option combinations ``setup`` cannot write, before anything is written.

    *attached* says whether a global file is selected, or will be once this
    run attaches or creates it. Every row applies to ``--unset`` operands as
    to the option flags of the same name.
    """
    _check_list_alone(args)
    _check_migration_alone(args)
    given = [option for option, _ in _given(args)]
    requested = [*given, *_unset(args)]
    global_scope: bool = args.global_scope
    if given and args.unset:
        raise Cveta2Error("--unset нельзя сочетать с новыми значениями; выполните их отдельными командами.")
    if args.reset and (requested or global_scope):
        raise Cveta2Error("--reset относится только к мастеру настройки кэша; уберите остальные параметры.")
    if global_scope and (option := _first(requested, ("personal",))):
        raise Cveta2Error(f"{option.flag} относится к личной конфигурации; уберите --global.")
    if not global_scope and (option := _first(requested, ("switch",))):
        raise Cveta2Error(
            f"{option.flag} задаётся только в общей конфигурации: cveta2 setup --global {option.flag} on|off"
        )
    if not global_scope and (option := _first(requested, ("team",))):
        raise Cveta2Error(
            f"{option.flag} задаётся только в общей конфигурации, локально не переопределяется: "
            f"cveta2 setup --global --project P {option.flag} …"
        )
    if not global_scope and not attached and _first(requested, ("publication",)):
        raise Cveta2Error(
            "Настройки публикации хранятся только в общей конфигурации, а она не выбрана; "
            "без неё передайте значения команде verify."
        )
    if args.project is None and (option := next((o for o in requested if o.needs_project), None)):
        raise Cveta2Error(f"{option.flag} относится к проекту; укажите его: --project P")
    if not global_scope and attached and (option := _first(requested, ("identity",))):
        raise Cveta2Error(
            f"{option.flag}: хост и организация CVAT задаются в общей конфигурации: "
            "cveta2 setup --global --host URL [--organization SLUG]"
        )
    if global_scope and requested and not attached:
        raise Cveta2Error(f"Общая конфигурация не выбрана; создайте её: {_CREATION_FORM}")
    selected = global_config_from_args(args) or global_config_from_env()
    if global_scope and args.host is None and selected is not None and not selected.expanduser().exists():
        raise Cveta2Error(f"Файла общей конфигурации {selected} нет; создайте его: {_CREATION_FORM}")
    if global_scope and selected is None:
        _check_saved_global_file(args)


def _check_saved_global_file(args: "argparse.Namespace") -> None:
    """Refuse a ``--global`` run when the personal key names a global file that is gone.

    Checked before any lock is taken: a lock file created beside the missing
    file would keep owner-only access and later lock teammates out of it.
    ``--host`` does not create the file here, only at a path from the flag or
    the environment, so the suggested command names the path.
    """
    saved = project_config_path(config_path_from_args(args))
    if saved is not None and not saved.exists():
        raise Cveta2Error(
            f"Файла общей конфигурации {saved} нет; создайте его: cveta2 setup --global "
            f"--global-config {shlex.quote(str(saved))} --host URL [--organization SLUG]"
        )


def _run_migration(config_path: Path, project_path: Path | None) -> None:
    """Review the exact migration proposal before activation."""
    require_interactive(wizard.SETUP_HINT)
    if recover_migration(config_path):
        logger.info("Прерванное подтверждённое разделение конфигурации завершено.")
        return
    proposal = migration_proposal(config_path, project_path)
    logger.info(json.dumps(proposal.preview(), ensure_ascii=False, indent=2))
    if proposal.unresolved:
        raise Cveta2Error("Сначала устраните неоднозначные настройки из отчёта миграции.")
    if primitives.confirm(
        "Подтвердить показанное разделение конфигурации?",
        hint=wizard.SETUP_HINT,
        default=False,
    ):
        activate_migration(proposal)
        logger.info("Разделение конфигурации завершено.")
    else:
        logger.info("Разделение отменено; конфигурация не изменена.")


def _creation_target(args: "argparse.Namespace", global_path: Path | None) -> Path | None:
    """Return the new global file ``--global --host`` creates, if its path is given and free."""
    if not (args.global_scope and args.host is not None):
        return None
    target = global_path or global_config_from_env()
    if target is None or target.expanduser().exists():
        return None
    return target


def _create_global_file(args: "argparse.Namespace", config_path: Path, target: Path) -> None:
    try:
        identity = CvatIdentity(host=args.host, organization=args.organization)
    except ValidationError as error:
        raise Cveta2Error(f"Некорректный адрес CVAT для --host: {args.host}") from error
    created = create_global_config(config_path, target, identity)
    logger.info(f"Создана и подключена общая конфигурация {created}")


def run_setup(args: "argparse.Namespace") -> None:
    """Write the given option values, attach or create a global file, or run the wizard.

    The option combinations are checked before the first write, as if the file
    this run attaches or creates were already selected. Checks that need the
    written state come later, so three paths write one file and then fail:
    creating a global file and then adding a project that neither
    ``projects.yaml`` nor CVAT knows; attaching a global file and then writing
    a local override it does not allow; and changing the local overrides and
    then saving the personal sections while the personal file still holds
    overrides the global file does not allow. None leaves a state worse than
    the start, and re-running the command after the cause is fixed converges.
    """
    config_path = config_path_from_args(args)
    global_path = global_config_from_args(args)
    if args.list_only:
        # Read-only: dispatched before creation and attachment; --global-config only selects.
        validate_setup_request(args, attached=global_path is not None)
        _print_listing(config_path, global_path, args.project)
        return
    if args.migrate_config:
        _check_migration_alone(args)
        _run_migration(config_path, global_path)
        return
    target = _creation_target(args, global_path)
    attaching = global_path is not None and not args.global_scope
    attached = (
        target is not None
        or global_path is not None
        or global_config_from_env() is not None
        or project_config_path(config_path) is not None
    )
    validate_setup_request(args, attached=attached)
    if target is not None:
        _create_global_file(args, config_path, target)
        # The new file carries host and organization; what is left goes into it.
        args = copy.copy(args)
        args.host = args.organization = None
        global_path = target
    elif attaching and global_path is not None:
        selected = attach_existing_project_config(config_path, global_path)
        logger.info(f"Общая конфигурация подключена: {selected}")
    if _given(args) or _unset(args):
        apply_setup_options(args, config_path, global_path)
    elif target is None and not attaching:
        require_interactive(wizard.SETUP_HINT)
        if args.global_scope:
            _run_global_wizard(config_path, global_path, project=args.project)
        else:
            _run_personal_wizard(config_path, project=args.project, reset=args.reset)


def _print_listing(config_path: Path, global_path: Path | None, project: str | None) -> None:
    name = None
    if project is not None:
        shared = optional_global_config(config_path, global_path)
        if shared is not None and find_project_key(shared, project) is None:
            project_id, name = resolve_setup_project(config_path, project, global_path)
            project = shared.key_for_id(project_id) or name
    listed = list_configuration(config_path, global_path=global_path, project=project, live_name=name)
    selected = project_config_path(config_path, global_path)
    if selected is not None:
        sys.stdout.write(f"Общая конфигурация: {selected}\n")
    for v in listed:
        origin = _ORIGIN_RU[v.origin] if v.applied else f"{_ORIGIN_RU[v.origin]}; {_NOT_APPLIED}"
        sys.stdout.write(f"{v.key} = {v.value}  ({origin})\n")


def apply_setup_options(args: "argparse.Namespace", config_path: Path, global_path: Path | None) -> None:
    """Write the option values and ``--unset`` removals of *args*, at most once per file.

    With ``--global`` everything goes into the global file in one locked
    write. Without it, publication options become local overrides and the
    rest goes to the personal file, one save per personal section.
    """
    changes: list[_Change] = [*_given(args), *((option, None) for option in _unset(args))]
    if args.global_scope:
        _write_global(args, config_path, global_path, changes)
        return
    personal = [(option, value) for option, value in changes if option.scope != "publication"]
    password = _ask_password() if any(option.name == "password" and value for option, value in personal) else None
    images_keys = _image_cache_keys(args, config_path, global_path, personal)
    local = [(option, value) for option, value in changes if option.scope == "publication"]
    if local:
        _write_local(args, config_path, global_path, local)
    if personal:
        _write_personal(config_path, personal, password=password, images_keys=images_keys)


def _ask_password() -> str:
    require_interactive(_HIDDEN_PROMPT_HINT)
    return wizard.prompt_password()


def _written(values: list[object], *, shared: bool) -> str:
    """Start the log line of one written file: removed or written, global or personal."""
    if all(value is None for value in values):
        return "Удалено из общей конфигурации" if shared else "Удалено из личной конфигурации"
    return "Записано в общую конфигурацию" if shared else "Записано в личную конфигурацию"


def _write_global(
    args: "argparse.Namespace", config_path: Path, global_path: Path | None, changes: list[_Change]
) -> None:
    settings: dict[str, object] = {}
    fields: dict[str, object] = {}
    for option, value in changes:
        if option.scope == "switch":
            settings[option.key] = None if value is None else value == "on"
        elif option.scope == "identity":
            settings[option.key] = value
        else:
            fields[option.key] = value
    project_changes: dict[str, dict[str, object]] = {}
    new_projects: dict[str, ProjectDefinition] = {}
    names = list(settings)
    if fields:
        key, new_projects = _global_project_key(args, config_path, global_path, fields)
        project_changes = {key: fields}
        names += [f"projects.{key}.{field}" for field in fields]
    written = write_shared_project_fields(
        config_path, project_changes, settings=settings, new_projects=new_projects, global_path=global_path
    )
    values = [*settings.values(), *fields.values()]
    logger.info(f"{_written(values, shared=True)} {written}: {', '.join(names)}")


def _global_project_key(
    args: "argparse.Namespace", config_path: Path, global_path: Path | None, fields: dict[str, object]
) -> tuple[str, dict[str, ProjectDefinition]]:
    """Return the project's key in the global file, with a new definition when it has none yet."""
    config = load_global_config(config_path, global_path)
    return _setup_project(
        config_path, global_path, config, args.project, create=any(value is not None for value in fields.values())
    )


def _setup_project(
    config_path: Path, global_path: Path | None, config: "ProjectConfig", spec: str, *, create: bool
) -> tuple[str, dict[str, ProjectDefinition]]:
    """Select a stored key/ID offline, or resolve the current CVAT name before applying policy."""
    if (key := find_project_key(config, spec)) is not None:
        return key, {}
    if not create and spec.isdecimal():
        raise Cveta2Error(f"Нет описания проекта {spec} в общей конфигурации.")
    project_id, name = resolve_setup_project(config_path, spec, global_path)
    if (key := config.key_for_id(project_id)) is not None:
        return key, {}
    if not create:
        raise Cveta2Error(
            f"Нет описания проекта {spec} в общей конфигурации; добавьте его: "
            f"cveta2 setup --global --project {shlex.quote(spec)}"
        )
    key = project_key_for(name, project_id)
    logger.info(f"Новое описание проекта {key}: id={project_id}")
    return key, {key: ProjectDefinition(id=project_id)}


def resolve_setup_project(config_path: Path, spec: str, global_path: Path | None = None) -> tuple[int, str]:
    """Read a project's current identity from the selected CVAT server."""
    refusal = f"Не удалось определить имя проекта {spec}; проверьте ID или учётные данные CVAT."
    try:
        with open_client(config_path, project_path=global_path) as client:
            if spec.strip().isdecimal():
                project = client.get_project(int(spec))
                resolved = (project.id, project.name)
            else:
                resolved = resolve_project_spec(client, spec)
    except ProjectNotFoundError as error:
        raise Cveta2Error(refusal) from error
    if not resolved[1]:
        raise Cveta2Error(refusal)
    return resolved


def _remove_dotted(mapping: dict[str, object], path: list[str]) -> None:
    """Remove the leaf at *path* and the parents it leaves empty."""
    head, *rest = path
    child = mapping.get(head)
    if rest and isinstance(child, dict):
        _remove_dotted(cast("dict[str, object]", child), rest)
        if child:
            return
    mapping.pop(head, None)


def _check_remaining_override(
    raw_global: "ProjectConfig", overrides: LocalOverrides, key: str, fields: dict[str, object], spec: str
) -> None:
    """Refuse a leaf removal that would make the overrides that remain invalid.

    All remaining overrides are merged, since a removal can also collide with
    another project's override. Whether overrides are allowed at all is a
    separate question, so the switch is treated as on here. Overrides of
    projects the global file no longer has are left out of both merges. When
    the current overrides are already invalid the removal is never refused,
    so the user can still repair them.
    """
    if key not in raw_global.projects or key not in overrides.projects:
        return
    current = {
        name: override.model_dump(exclude_none=True)
        for name, override in overrides.projects.items()
        if name in raw_global.projects
    }
    remaining = copy.deepcopy(current)
    for field in fields:
        _remove_dotted(remaining[key], field.split("."))
    allowed = raw_global.model_copy(update={"local_overrides": True})
    try:
        apply_local_overrides(allowed, LocalOverrides.model_validate({"projects": current}))
    except ManagedError:
        return
    try:
        apply_local_overrides(allowed, LocalOverrides.model_validate({"projects": remaining}))
    except ManagedError as error:
        # A whole block cannot become incomplete; only a collision with another override remains.
        fix = (
            "Сначала удалите или измените совпадающее переопределение другого проекта."
            if "publication" in fields
            else f"Удалите весь блок: cveta2 setup --project {shlex.quote(spec)} --unset publication; если назначение "
            "совпало с переопределением другого проекта, сначала удалите или измените его."
        )
        raise Cveta2Error(
            f"Без {', '.join(fields)} локальные переопределения станут некорректными: {error}. {fix}"
        ) from error


def _write_local(
    args: "argparse.Namespace", config_path: Path, global_path: Path | None, changes: list[_Change]
) -> None:
    """Write or remove the user's own overrides of one project's publication settings."""
    spec: str = args.project
    raw_global = load_global_config(config_path, global_path)
    overrides = read_local_overrides(read_config(config_path, missing_ok=True))
    fields = {option.key: value for option, value in changes}
    removing = all(value is None for value in fields.values())
    key = find_project_key(raw_global, spec)
    if key is None and removing and spec in overrides.projects:
        # The team removed the project; the user may still clear their stale override.
        key = spec
    if key is None:
        key, _ = _setup_project(config_path, global_path, raw_global, spec, create=False)
    if removing:
        _check_remaining_override(raw_global, overrides, key, fields, spec)
    written = write_local_overrides(config_path, key, fields, global_path=global_path)
    names = ", ".join(f"overrides.projects.{key}.{field}" for field in fields)
    logger.info(f"{_written(list(fields.values()), shared=False)} {written}: {names}")


def _image_cache_keys(
    args: "argparse.Namespace", config_path: Path, global_path: Path | None, changes: list[_Change]
) -> tuple[str, ...]:
    """Select the preferred personal key and any older name binding for the same project."""
    if not any(option.key == "image_cache" for option, _ in changes):
        return ()
    spec: str = args.project
    shared = optional_global_config(config_path, global_path)
    images = ImageCacheConfig.load(config_path, project_path=global_path)
    if shared is not None and (key := find_project_key(shared, spec)) is not None:
        if not (images.projects.keys() - shared.projects.keys()):
            return (key,)
        spec = str(shared.projects[key].id)
    project_id, name = resolve_setup_project(config_path, spec, global_path)
    key = images.project_key(name, project_id)
    return (key, name) if key != name and shared and name not in shared.projects else (key,)


def _write_personal(
    config_path: Path, changes: list[_Change], *, password: str | None, images_keys: tuple[str, ...]
) -> None:
    """One save per personal section: ``cvat``, ``cache`` and ``image_cache``."""
    names: list[str] = []
    cvat = {option.key.removeprefix("cvat."): value for option, value in changes if option.key.startswith("cvat.")}
    if "password" in cvat and cvat["password"] is not None:
        if password:
            cvat["password"] = password
        else:
            logger.info("Пароль не изменён: введена пустая строка.")
            del cvat["password"]
    if cvat:
        _save_cvat(config_path, cvat)
        names += [f"cvat.{field}" for field in cvat]
    cache = {option.key.removeprefix("cache."): value for option, value in changes if option.key.startswith("cache.")}
    if cache:
        section = CacheConfig.load(config_path)
        for field, value in cache.items():
            setattr(section, field, value)
        section.save(config_path)
        names += [f"cache.{field}" for field in cache]
    images = [value for option, value in changes if option.key == "image_cache"]
    if images and images_keys:
        image_cache = ImageCacheConfig.load(config_path)
        for key in images_keys:
            image_cache.projects.pop(key, None)
        if images[0] is not None:
            image_cache.set_cache_dir(images_keys[0], cast("Path", images[0]))
        image_cache.save(config_path)
        names.append(f"image_cache.{images_keys[0]}")
    if names:
        values = [value for option, value in changes]
        logger.info(f"{_written(values, shared=False)} {config_path}: {', '.join(names)}")


def _save_cvat(config_path: Path, updates: dict[str, object]) -> None:
    """Update the personal ``cvat`` section; host and organization follow the global file when attached."""
    existing = CvatConfig.from_file(config_path)
    shared = optional_global_config(config_path)
    values = existing.model_dump()
    if shared is not None:
        values.update(host=shared.cvat.host, organization=shared.cvat.organization)
    for field, value in updates.items():
        values[field] = "" if field == "host" and value is None else value
    CvatConfig.model_validate(values).save_to_file(config_path)


def _run_personal_wizard(config_path: Path, *, project: str | None, reset: bool) -> None:
    """Ask for CVAT credentials, offer a global file, then the image and annotation cache paths.

    *project* (ID or name) limits the cache questions to that project;
    *reset* re-derives every path from the cache root instead of keeping saved ones.
    """
    _ask_credentials(config_path)
    if project is None:
        projects = _ensure_projects_list(config_path)
    else:
        project_id, name = resolve_setup_project(config_path, project)
        projects = [ProjectInfo(id=project_id, name=name)]
    cache_root = wizard.prompt_cache_root()
    if not projects:
        logger.info("Нет доступных проектов; каталоги изображений по проектам не заданы.")
    elif _setup_image_cache_dirs(projects, ImageCacheConfig.load(config_path), cache_root, config_path, reset=reset):
        logger.info("Пути кэширования изображений обновлены.")
    if _setup_cache_roots(cache_root, config_path):
        logger.info("Настройки кэша обновлены.")
    logger.info("Готово!")


def _setup_cache_roots(cache_root: Path | None, config_path: Path) -> bool:
    """Save ``cache.images_root`` (the cache root) and ``cache.tasks_root``; True when saved."""
    cache_cfg = CacheConfig.load(config_path)
    changed = False
    if cache_root is not None and cache_cfg.images_root != cache_root:
        cache_cfg.images_root = cache_root
        changed = True
    tasks_root = wizard.prompt_tasks_root(cache_cfg.tasks_root)
    if tasks_root is not None and tasks_root != cache_cfg.tasks_root:
        cache_cfg.tasks_root = tasks_root
        changed = True
    if changed:
        cache_cfg.save(config_path)
    return changed


# Publication leaves the global wizard asks, with the flag that sets each one.
_PUBLICATION_REQUIRED = {
    "publication.clearml.project": "--clearml-project",
    "publication.clearml.dataset": "--dataset-name",
    "publication.api_url": "--api-url",
}


def _run_global_wizard(config_path: Path, global_path: Path | None, *, project: str | None) -> None:
    """Ask each project's team settings and write the changed ones to the global file at once.

    Defaults come from the global file as written, never from the effective
    view, so local overrides neither leak into the team file nor block it.
    Enter keeps a value; removing one is ``--unset``.
    """
    selected = project_config_path(config_path, global_path)
    if selected is None or not selected.exists():
        raise Cveta2Error(f"Общая конфигурация не выбрана; создайте её: {_CREATION_FORM}")
    raw = load_global_config(config_path, global_path)
    new_projects: dict[str, ProjectDefinition] = {}
    if project is None:
        keys = list(raw.projects)
    else:
        key, new_projects = _setup_project(config_path, global_path, raw, project, create=True)
        keys = [key]
    changes: dict[str, dict[str, object]] = {}
    expected: dict[str, dict[str, object]] = {}
    for key in keys:
        definition = raw.projects.get(key) or new_projects[key]
        stored = _team_values(definition)
        answers = _ask_team_values(key, stored)
        fields = {field: answer for field, answer in answers.items() if answer != _shown_default(field, stored[field])}
        _check_complete_publication(key, definition, fields)
        if fields:
            changes[key] = fields
            expected[key] = {field: stored[field] for field in fields}
    if not changes and not new_projects:
        logger.info("Общая конфигурация не изменена.")
        return
    written = write_shared_project_fields(
        config_path, changes, expected=expected, new_projects=new_projects, global_path=global_path
    )
    names = [f"projects.{key}.{field}" for key, fields in changes.items() for field in fields]
    names += [f"projects.{key}" for key in new_projects if key not in changes]
    logger.info(f"Записано в общую конфигурацию {written}: {', '.join(names)}")


def _team_values(definition: ProjectDefinition) -> dict[str, object]:
    """Return the leaves the global wizard asks, as stored; ``None`` where absent."""
    publication = definition.publication
    return {
        "ignored_prefix": definition.ignored_prefix,
        "task_cache_s3": definition.task_cache_s3,
        "publication.clearml.project": publication.clearml.project if publication else None,
        "publication.clearml.dataset": publication.clearml.dataset if publication else None,
        "publication.api_url": publication.api_url if publication else None,
        "publication.empty_classes": list(publication.empty_classes) if publication else None,
    }


def _shown_default(field: str, stored: object) -> object:
    """Return the default a prompt shows: the stored value, or no excluded classes."""
    return [] if field == "publication.empty_classes" and stored is None else stored


def _ask_team_values(key: str, stored: dict[str, object]) -> dict[str, object]:
    """Ask the six team questions of one project, in order; each answer defaults to the stored value."""
    return {
        "ignored_prefix": wizard.prompt_ignored_prefix(key, cast("str | None", stored["ignored_prefix"])),
        "task_cache_s3": wizard.prompt_task_cache_s3(key, cast("str | None", stored["task_cache_s3"])),
        "publication.clearml.project": wizard.prompt_clearml_project(
            key, cast("str | None", stored["publication.clearml.project"])
        ),
        "publication.clearml.dataset": wizard.prompt_dataset_name(
            key, cast("str | None", stored["publication.clearml.dataset"])
        ),
        "publication.api_url": wizard.prompt_api_url(key, cast("str | None", stored["publication.api_url"])),
        "publication.empty_classes": wizard.prompt_empty_classes(
            key, cast("list[int]", _shown_default("publication.empty_classes", stored["publication.empty_classes"]))
        ),
    }


def _check_complete_publication(key: str, definition: ProjectDefinition, fields: dict[str, object]) -> None:
    """Refuse to start a ``publication`` block without its ClearML project, dataset name and API URL."""
    if definition.publication is not None or not any(field.startswith("publication.") for field in fields):
        return
    missing = [flag for field, flag in _PUBLICATION_REQUIRED.items() if field not in fields]
    if missing:
        raise Cveta2Error(
            f"Для проекта {key} укажите ClearML-проект, имя набора и адрес API классов вместе: "
            f"не хватает {', '.join(missing)}"
        )


def _ask_credentials(config_path: Path) -> None:
    """Interactively ask for CVAT credentials and core settings."""
    shared = optional_project_config(config_path)
    if shared is not None:
        # Validate the effective configuration (e.g. conflicting environment
        # identity) without letting one-run environment values reach the file.
        CvatConfig.load(config_path)
    existing = CvatConfig.from_file(config_path)

    if shared is None:
        host_default = existing.host or "https://app.cvat.ai"
        host = wizard.prompt_host(host_default)
        organization = wizard.prompt_organization(existing.organization)
    else:
        host, organization = shared.cvat.host, shared.cvat.organization

    username = wizard.prompt_username(existing.username or "")
    password = wizard.prompt_password()
    if not password and existing.password:
        password = existing.password
        logger.info("Пароль не изменён (использован существующий).")

    cfg = CvatConfig(
        host=host,
        organization=organization,
        username=username,
        password=password,
        request_timeout=existing.request_timeout,
    )

    saved_path = cfg.save_to_file(config_path)
    logger.info(f"Готово! Конфигурация сохранена в {saved_path}")
    if shared is None:
        _offer_shared_attachment(config_path)


def _offer_shared_attachment(config_path: Path) -> None:
    """Offer a shared path without silently moving newly saved identity fields."""
    project_path = primitives.path("Общий YAML проектов (пусто — пропустить): ", hint=wizard.SETUP_HINT)
    if project_path is not None and project_path.exists():
        # An existing team file is attached, never rewritten; the identity
        # just entered must match it.
        selected = attach_existing_project_config(config_path, project_path)
        logger.info(f"Общая конфигурация подключена: {selected}")
    elif project_path is not None:
        # Legacy host/org must first move through the reviewed migration.
        proposal = migration_proposal(config_path, project_path)
        logger.info(json.dumps(proposal.preview(), ensure_ascii=False, indent=2))
        if proposal.unresolved:
            raise Cveta2Error("Общая конфигурация отличается; выполните setup --migrate-config после согласования.")
        if primitives.confirm(
            "Подтвердить разделение и подключение?",
            hint=wizard.SETUP_HINT,
            default=False,
        ):
            activate_migration(proposal)


def _setup_image_cache_dirs(
    projects: "list[ProjectInfo]",
    image_cache: ImageCacheConfig,
    cache_root: "Path | None",
    config_path: "Path",
    *,
    reset: bool,
) -> bool:
    """Interactive ``image_cache`` stage; returns True when saved."""
    if cache_root is not None and _apply_root_to_all_projects(projects, image_cache, cache_root, reset=reset):
        image_cache.save(config_path)
        return True

    logger.info(f"Найдено проектов: {len(projects)}. Укажите путь кэша для каждого.")
    logger.info("Нажмите Enter, чтобы принять значение по умолчанию или пропустить.\n")

    changed = False
    for project in projects:
        default_path = _default_cache_path(project, image_cache, cache_root, reset=reset)
        changed |= _prompt_project_cache_dir(project, image_cache, default_path)

    if changed:
        image_cache.save(config_path)
    return changed


def _apply_root_to_all_projects(
    projects: "list[ProjectInfo]",
    image_cache: ImageCacheConfig,
    cache_root: "Path",
    *,
    reset: bool,
) -> bool:
    """Show derived paths for all projects; assign them all on confirmation."""
    defaults = {
        image_cache.project_key(project.name, project.id): _default_cache_path(
            project, image_cache, cache_root, reset=reset
        )
        for project in projects
    }
    for name, path in defaults.items():
        logger.info(f"  {name} -> {path}")
    if not wizard.confirm_apply_to_all():
        return False
    for name, path in defaults.items():
        if path is not None:
            image_cache.set_cache_dir(name, path)
    return True


def _default_cache_path(
    project: "ProjectInfo",
    image_cache: ImageCacheConfig,
    cache_root: "Path | None",
    *,
    reset: bool,
) -> "Path | None":
    """Default path: existing config, or cache_root/project_name, or None."""
    if not reset:
        existing = image_cache.get_cache_dir(project.name, project.id)
        if existing is not None:
            return existing
    if cache_root is not None:
        return cache_dir_for_project(cache_root, project.name)
    return None


def _prompt_project_cache_dir(
    project: "ProjectInfo",
    image_cache: ImageCacheConfig,
    default_path: "Path | None",
) -> bool:
    """Prompt for one project's cache dir; update config. Return True if changed."""
    resolved = wizard.prompt_project_cache_dir(f"  {project.name} (id={project.id})", default_path)
    if resolved is not None:
        image_cache.set_cache_dir(image_cache.project_key(project.name, project.id), resolved)
        logger.info(f"    → {resolved}")
        return True
    if default_path is not None:
        image_cache.set_cache_dir(image_cache.project_key(project.name, project.id), default_path)
        logger.info(f"    → {default_path}")
        return True
    return False


def _ensure_projects_list(config_path: "Path") -> "list[ProjectInfo]":
    """Return cached projects; fetch the default org's list if cache is empty."""
    projects_cache_path = get_projects_cache_path(config_path)
    projects = load_projects_cache(projects_cache_path)
    if projects:
        return projects

    logger.info("Кэш проектов пуст. Загружаю список с CVAT...")
    with open_client(config_path) as client:
        projects = client.list_projects()
        org = client.organization or ""

    if projects:
        update_org_projects(org, org or PERSONAL_WORKSPACE_TITLE, projects, projects_cache_path)
        logger.info(f"Загружено проектов: {len(projects)}")
    return projects
