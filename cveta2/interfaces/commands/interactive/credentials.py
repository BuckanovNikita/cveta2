"""Interactive CVAT credential prompting.

Moved out of ``_bootstrap`` so all prompting lives in the interactive package.
``open_client`` calls :func:`prompt_credentials` for the single credential
prompt shared by every network command.
"""

from loguru import logger

from cveta2.composition.configuration import CvatConfig, require_interactive
from cveta2.interfaces.commands.interactive import primitives


def prompt_credentials(cfg: CvatConfig) -> CvatConfig:
    """Prompt interactively for missing credentials.  Returns updated copy."""
    username = cfg.username
    password = cfg.password

    if not username:
        require_interactive("Задайте CVAT_USERNAME/CVAT_PASSWORD.")
        logger.info("Учётные данные не указаны. Введите логин CVAT:")
        username = primitives.text(
            "Имя пользователя:",
            hint="Задайте CVAT_USERNAME/CVAT_PASSWORD.",
            allow_empty=True,
        )
    if not password:
        require_interactive("Задайте CVAT_PASSWORD.")
        password = primitives.prompt_password(f"Пароль для {username}: ")

    return cfg.model_copy(update={"username": username, "password": password})
