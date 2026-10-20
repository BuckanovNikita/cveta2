"""Collect explicit bundle choices outside prompt-free application workflows."""

from pathlib import Path

import questionary

from cveta2.domain.bundle.models import UploadCancelled
from cveta2.domain.bundle.preparation import Decision, PrepareOptions


def collect_decisions(
    options: PrepareOptions, decisions: tuple[Decision, ...]
) -> PrepareOptions:
    """Return new explicit options or cancel without creating remote objects."""
    updates: dict[str, object] = {}
    class_empty = dict(options.class_empty)
    for decision in decisions:
        if decision.kind in {"class_empty", "class_changes"}:
            answer = questionary.confirm(decision.message, default=False).ask()
            if answer is None:
                raise UploadCancelled("Подготовка отменена.")
            if decision.kind == "class_empty" and decision.class_id is not None:
                class_empty[decision.class_id] = answer
            elif not answer:
                raise UploadCancelled("Изменения классов не подтверждены.")
            else:
                updates["accept_class_changes"] = True
        elif decision.kind == "local_roots":
            suggested = sorted({str(Path(path).parent) for path in decision.choices})
            answer = questionary.confirm(
                "Разрешить каталоги:\n" + "\n".join(suggested), default=False
            ).ask()
            if not answer:
                raise UploadCancelled("Корни изображений не подтверждены.")
            updates["local_roots"] = (*options.local_roots, *suggested)
        else:
            text = questionary.text(decision.message).ask()
            if not text or not text.strip():
                raise UploadCancelled("Подготовка отменена.")
            updates[decision.kind] = text.strip()
    updates["class_empty"] = class_empty
    return PrepareOptions.model_validate({**options.model_dump(), **updates})
