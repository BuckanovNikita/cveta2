"""Detect the optional publishing SDK at its adapter boundary."""


def is_clearml_available() -> bool:
    """Return True if the ``clearml`` package is importable."""
    try:
        import clearml  # noqa: F401, PLC0415
    except ImportError:
        return False
    return True
