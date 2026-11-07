"""Non-mutating semantic parsers for native and lexical CSV cells."""

from decimal import Decimal, InvalidOperation
from math import isfinite
from numbers import Real

import numpy as np
import pandas as pd


def is_missing(value: object) -> bool:
    """Recognize empty cells, preserving whitespace and literal NA-like text."""
    if value is None or value is pd.NA:
        return True
    if isinstance(value, str):
        return value == ""
    return isinstance(value, (float, np.floating)) and bool(np.isnan(value))


def number(value: object) -> float | None:
    """Parse a finite real value without coercing or replacing the source cell."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (str, Real, Decimal)):
        return None
    try:
        parsed = float(value)
    except (ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def integer(value: object) -> bool:
    """Whether the numeric cell is semantically integral (including 12.0)."""
    if isinstance(value, (str, Decimal)):
        try:
            decimal = Decimal(value)
        except InvalidOperation:
            return False
        return decimal.is_finite() and decimal == decimal.to_integral_value()
    parsed = number(value)
    return parsed is not None and parsed.is_integer()
