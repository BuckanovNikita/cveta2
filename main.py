"""Backwards-compatible entry point.  Prefer ``python -m cveta2`` or ``cveta2`` CLI."""

from cveta2.cli import main

if __name__ == "__main__":
    main()
