"""ClearML configuration inspection for ``cveta2 doctor``; the SDK is imported lazily.

The check stays offline. Logging in through the SDK session retries 240 times with
backoff and can wait forever on server maintenance, so it is not a bounded probe.
"""

from pathlib import Path

from loguru import logger

from cveta2.domain.errors import Cveta2Error

_FIX = (
    "Создайте файл конфигурации ClearML (~/clearml.conf или путь в CLEARML_CONFIG_FILE) "
    "или задайте переменные CLEARML_API_HOST, CLEARML_API_ACCESS_KEY и CLEARML_API_SECRET_KEY."
)


def _config_files() -> list[str]:
    """Return the existing configuration files the SDK merges, in its own order.

    A set ``CLEARML_CONFIG_FILE`` replaces the home-directory files even when the
    file it names does not exist, exactly as ``Config._reload`` does.
    """
    from clearml.backend_config.defs import (  # noqa: PLC0415 - the SDK stays lazy
        LOCAL_CONFIG_FILE_OVERRIDE_VAR,
        LOCAL_CONFIG_FILES,
    )

    override = LOCAL_CONFIG_FILE_OVERRIDE_VAR.get()
    candidates = [Path(override).expanduser()] if override else [Path(item) for item in LOCAL_CONFIG_FILES]
    return [str(path) for path in candidates if path.is_file()]


def _check_clearml_configuration() -> bool:
    """Check that the ClearML SDK resolves an API server and credentials.

    Returns ``True`` when credentials are found. Never prints a key.
    """
    logger.info("doctor: checking ClearML configuration …")

    from clearml.backend_api import Session, load_config  # noqa: PLC0415 - the SDK stays lazy
    from clearml.backend_api.session.defs import (  # noqa: PLC0415 - the SDK stays lazy
        ENV_ACCESS_KEY,
        ENV_AUTH_TOKEN,
        ENV_HOST,
        ENV_SECRET_KEY,
    )

    files = _config_files()
    # A fresh configuration, not the SDK's process-wide one, so the files are read now.
    config = load_config()
    # The SDK's own session passes its Config here although the parameter is annotated ConfigTree.
    host = Session.get_api_server_host(config=config)  # type: ignore[arg-type]
    token = ENV_AUTH_TOKEN.get()
    access_key = ENV_ACCESS_KEY.get(default=config.get("api.credentials.access_key", None) or Session.default_key)
    secret_key = ENV_SECRET_KEY.get(default=config.get("api.credentials.secret_key", None) or Session.default_secret)

    if not token and not (access_key and secret_key):
        missing = []
        if not access_key:
            missing.append("ключ доступа (CLEARML_API_ACCESS_KEY или api.credentials.access_key)")
        if not secret_key:
            missing.append("секретный ключ (CLEARML_API_SECRET_KEY или api.credentials.secret_key)")
        logger.warning(f"ClearML: не настроен — не найдены: {', '.join(missing)}. {_FIX}")
        return False

    sources = [f"файл {path}" for path in files]
    if any(entry.get() for entry in (ENV_HOST, ENV_ACCESS_KEY, ENV_SECRET_KEY, ENV_AUTH_TOKEN)):
        sources.append("переменные окружения")
    configured_host = ENV_HOST.get() or config.get("api.api_server", None) or config.get("api.host", None)
    host_note = "" if configured_host else " (адрес SDK по умолчанию)"
    logger.info(f"ClearML: настроен — сервер API {host}{host_note}, источник: {', '.join(sources)}")
    return True


def check_clearml_configuration() -> bool:
    """Report whether ClearML is configured, translating SDK failures at this boundary.

    The error names the files and the error class only: the parser message can quote
    the file, and the file holds the secret key.
    """
    from clearml.backend_config import ConfigurationError  # noqa: PLC0415 - the SDK stays lazy
    from clearml.utilities.pyhocon.exceptions import ConfigException  # noqa: PLC0415 - the SDK stays lazy

    try:
        return _check_clearml_configuration()
    except (ConfigurationError, ConfigException) as error:
        files = ", ".join(_config_files())
        raise Cveta2Error(f"ClearML: файл конфигурации не читается ({files}): {type(error).__name__}") from error
