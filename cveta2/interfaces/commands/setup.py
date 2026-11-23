"""Implementation of the ``cveta2 setup`` and ``cveta2 setup-cache`` commands."""

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from loguru import logger
from pydantic import ValidationError

from cveta2.composition.configuration import (
    PERSONAL_WORKSPACE_TITLE,
    CacheConfig,
    CacheProjectSettings,
    CvatConfig,
    ImageCacheConfig,
    LocalOverrides,
    activate_migration,
    apply_local_overrides,
    attach_existing_project_config,
    attach_project_config,
    cache_dir_for_project,
    create_global_config,
    find_project_key,
    get_projects_cache_path,
    global_config_from_env,
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
from cveta2.interfaces.commands._bootstrap import open_client
from cveta2.interfaces.commands._helpers import (
    config_path_from_args,
    global_config_from_args,
    resolve_project_from_args,
)
from cveta2.interfaces.commands._parsers import add_config_arg, add_global_config_arg, add_list_arg, add_project_arg
from cveta2.interfaces.commands.interactive import primitives, wizard

if TYPE_CHECKING:
    import argparse

    from cveta2.domain.managed.models import ProjectConfig
    from cveta2.domain.models import ProjectInfo


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


def _first(requested: list[SetupOption], scopes: tuple[str, ...]) -> SetupOption | None:
    return next((option for option in requested if option.scope in scopes), None)


def validate_setup_request(args: "argparse.Namespace", *, attached: bool) -> None:  # noqa: C901 - one check per row of the documented error table
    """Refuse option combinations ``setup`` cannot write, before anything is written.

    *attached* says whether a global file is selected, or will be once this
    run attaches or creates it. Every row applies to ``--unset`` operands as
    to the option flags of the same name.
    """
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


def configure_setup_cache(parser: "argparse.ArgumentParser") -> None:
    """Declare the ``setup-cache`` command arguments."""
    add_config_arg(parser)
    parser.add_argument(
        "--reset",
        action="store_true",
        help=("Re-ask path for every project using cache_root/project_name as default (ignore existing paths)."),
    )
    add_list_arg(parser, "List current image cache paths and exit.")


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

    Every refusal happens before the first write: the request is validated
    as if the file it attaches or creates were already selected.
    """
    config_path = config_path_from_args(args)
    global_path = global_config_from_args(args)
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
        selected = attach_project_config(config_path, global_path)
        logger.info(f"Общая конфигурация подключена: {selected}")
    if _given(args) or _unset(args):
        apply_setup_options(args, config_path, global_path)
    elif target is None and not attaching:
        _run_wizard(config_path)


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
    images_name = _image_cache_name(args, config_path, global_path, personal)
    local = [(option, value) for option, value in changes if option.scope == "publication"]
    if local:
        _write_local(args, config_path, global_path, local)
    if personal:
        _write_personal(config_path, personal, password=password, images_name=images_name)


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
    spec: str = args.project
    key = find_project_key(load_global_config(config_path, global_path), spec)
    if key is not None:
        return key, {}
    if all(value is None for value in fields.values()):
        # Removing from a project that has no definition must not create one.
        raise Cveta2Error(f"Нет описания проекта {spec} в общей конфигурации; удалять нечего.")
    project_id, name = resolve_new_project(config_path, spec)
    key = project_key_for(name, project_id)
    logger.info(f"Новое описание проекта {key}: id={project_id}, name={name}")
    return key, {key: ProjectDefinition(id=project_id, name=name)}


def resolve_new_project(config_path: Path, spec: str) -> tuple[int, str]:
    """Resolve the CVAT ID and name of *spec* (decimal ID or name) for a new definition.

    The local project list (``projects.yaml``) is asked first, then CVAT,
    which needs credentials. A project without a name is refused: a
    definition without one would never match the readers.
    """
    spec = spec.strip()
    refusal = f"Не удалось определить имя проекта {spec}; проверьте ID или учётные данные CVAT."
    by_id = spec.isascii() and spec.isdecimal()
    cached = {
        (project.id, project.name)
        for project in load_projects_cache(get_projects_cache_path(config_path))
        if (project.id == int(spec) if by_id else project.name == spec)
    }
    if len(cached) == 1:
        ((project_id, name),) = cached
        if name:
            return project_id, name
    try:
        with open_client(config_path) as client:
            resolved = resolve_project_from_args(client, spec)
    except ProjectNotFoundError as error:
        raise Cveta2Error(refusal) from error
    if resolved is None or not resolved[1]:
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
    """Refuse a leaf removal that would leave this project's override block invalid.

    Whether overrides are allowed at all is a separate question, so the
    switch is treated as on here.
    """
    current = overrides.projects.get(key)
    if current is None or key not in raw_global.projects:
        return
    remaining = current.model_dump(exclude_none=True)
    for field in fields:
        _remove_dotted(remaining, field.split("."))
    try:
        apply_local_overrides(
            raw_global.model_copy(update={"local_overrides": True}),
            LocalOverrides.model_validate({"projects": {key: remaining}}),
        )
    except ManagedError as error:
        raise Cveta2Error(
            f"Без {', '.join(fields)} локальное переопределение проекта {key} станет некорректным: {error}. "
            f"Удалите весь блок: cveta2 setup --project {spec} --unset publication"
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
        raise Cveta2Error(
            f"Нет описания проекта {spec} в общей конфигурации; добавьте его: cveta2 setup --global --project {spec}"
        )
    if removing and "publication" not in fields:
        _check_remaining_override(raw_global, overrides, key, fields, spec)
    written = write_local_overrides(config_path, key, fields, global_path=global_path)
    names = ", ".join(f"overrides.projects.{key}.{field}" for field in fields)
    logger.info(f"{_written(list(fields.values()), shared=False)} {written}: {names}")


def _image_cache_name(
    args: "argparse.Namespace", config_path: Path, global_path: Path | None, changes: list[_Change]
) -> str | None:
    """Return the project name ``image_cache`` is keyed by, resolved before anything is written."""
    if not any(option.key == "image_cache" for option, _ in changes):
        return None
    spec: str = args.project
    raw_global = optional_global_config(config_path, global_path)
    key = find_project_key(raw_global, spec) if raw_global is not None else None
    if raw_global is not None and key is not None:
        return raw_global.projects[key].name or key
    if spec in ImageCacheConfig.load(config_path).projects:
        return spec
    return resolve_new_project(config_path, spec)[1]


def _write_personal(
    config_path: Path, changes: list[_Change], *, password: str | None, images_name: str | None
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
    if images and images_name is not None:
        image_cache = ImageCacheConfig.load(config_path)
        if images[0] is None:
            image_cache.projects.pop(images_name, None)
        else:
            image_cache.set_cache_dir(images_name, cast("Path", images[0]))
        image_cache.save(config_path)
        names.append(f"image_cache.{images_name}")
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


def _run_wizard(config_path: Path) -> None:
    """Interactively ask for CVAT credentials and core settings."""
    require_interactive(wizard.SETUP_HINT)
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


def run_setup_cache(args: "argparse.Namespace") -> None:
    """Interactively configure image cache directories for all known projects."""
    config_path = config_path_from_args(args)
    if args.list_only:
        _list_cache_paths(config_path)
        return

    require_interactive(wizard.CACHE_HINT)

    projects = _ensure_projects_list(config_path)
    if not projects:
        raise Cveta2Error("Нет доступных проектов.")

    image_cache = ImageCacheConfig.load(config_path)
    cache_root = wizard.prompt_cache_root()

    if _setup_image_cache_dirs(projects, image_cache, cache_root, config_path, reset=args.reset):
        logger.info("Пути кэширования изображений обновлены.")

    if _setup_cache_settings(projects, cache_root, config_path):
        logger.info("Настройки кэша обновлены.")
    logger.info("Готово!")


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


def _setup_cache_settings(
    projects: "list[ProjectInfo]",
    cache_root: "Path | None",
    config_path: "Path",
) -> bool:
    """Interactive ``cache`` section stage; returns True when saved."""
    cache_cfg = CacheConfig.load(config_path)
    changed = False

    if cache_root is not None and cache_cfg.images_root != cache_root:
        cache_cfg.images_root = cache_root
        changed = True

    tasks_root = wizard.prompt_tasks_root(cache_cfg.tasks_root)
    if tasks_root is not None and tasks_root != cache_cfg.tasks_root:
        cache_cfg.tasks_root = tasks_root
        changed = True

    if wizard.confirm_project_cache_settings():
        for project in projects:
            changed |= _prompt_project_cache_settings(cache_cfg, project.name)

    if changed:
        cache_cfg.save(config_path)
    return changed


def _prompt_project_cache_settings(cache_cfg: CacheConfig, name: str) -> bool:
    """Prompt one project's ignored_prefix / task_cache_s3. True if changed."""
    current = cache_cfg.projects.get(name) or CacheProjectSettings()
    ignored = wizard.prompt_ignored_prefix(name, current.ignored_prefix)
    task_cache_s3 = wizard.prompt_task_cache_s3(name, current.task_cache_s3)
    if ignored == current.ignored_prefix and task_cache_s3 == current.task_cache_s3:
        return False
    cache_cfg.projects[name] = current.model_copy(update={"ignored_prefix": ignored, "task_cache_s3": task_cache_s3})
    return True


def _list_cache_paths(config_path: "Path") -> None:
    """Print current image_cache paths and cache settings, then exit."""
    image_cache = ImageCacheConfig.load(config_path)
    cache_cfg = CacheConfig.load(config_path)
    if not image_cache.projects and not cache_cfg.model_dump(exclude_defaults=True):
        logger.info("Пути кэша не заданы.")
        return
    for name, path in sorted(image_cache.projects.items()):
        logger.info(f"  {name}: {path}")
    if cache_cfg.images_root is not None:
        logger.info(f"  images_root: {cache_cfg.images_root}")
    if cache_cfg.tasks_root is not None:
        logger.info(f"  tasks_root: {cache_cfg.tasks_root}")
    for name, settings in sorted(cache_cfg.projects.items()):
        if settings.ignored_prefix:
            logger.info(f"  {name}: ignored_prefix: {settings.ignored_prefix}")
        if settings.task_cache_s3:
            logger.info(f"  {name}: task_cache_s3: {settings.task_cache_s3}")
        if settings.images_root is not None:
            logger.info(f"  {name}: images_root: {settings.images_root}")
        if settings.tasks_root is not None:
            logger.info(f"  {name}: tasks_root: {settings.tasks_root}")


def _apply_root_to_all_projects(
    projects: "list[ProjectInfo]",
    image_cache: ImageCacheConfig,
    cache_root: "Path",
    *,
    reset: bool,
) -> bool:
    """Show derived paths for all projects; assign them all on confirmation."""
    defaults = {
        project.name: _default_cache_path(project, image_cache, cache_root, reset=reset) for project in projects
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
    if not reset and image_cache.get_cache_dir(project.name) is not None:
        return image_cache.get_cache_dir(project.name)
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
        image_cache.set_cache_dir(project.name, resolved)
        logger.info(f"    → {resolved}")
        return True
    if default_path is not None:
        image_cache.set_cache_dir(project.name, default_path)
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
