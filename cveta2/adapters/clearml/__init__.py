"""Optional ClearML SDK adapters.

Only modules in this package import ``clearml``, and only lazily inside the call that
needs it, so cveta2 imports and verifies CSV files without the ``clearml`` extra.
Ordinary project and task fetch never reaches these adapters.
"""
