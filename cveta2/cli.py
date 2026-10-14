"""Compatible public exports from canonical implementations."""

from cveta2.interfaces.cli import (
    CliApp,
    CommandSpec,
    main,
)

__all__ = ["CliApp", "CommandSpec", "main"]


if __name__ == "__main__":
    main()
