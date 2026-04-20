__all__ = ['constants', 'paths', 'exitc']

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Type, Final, final


@final
class Constants:
    @dataclass
    class Paths:
        @staticmethod
        def _get_root() -> Path:
            """Traverse up to find the project root (containing pyproject.toml)."""
            curr = Path(__file__).resolve().parent
            while curr != curr.parent:
                if (curr / 'main.py').exists():
                    return curr
                curr = curr.parent
            # Fallback to current directory if not found
            return Path.cwd()

        ROOT: Final[Path] = _get_root()
        """Resolved path to the project root directory."""

        PACKAGE: Final[Path] = ROOT / 'cairn'
        """Resolved path to the 'orcdbl/' directory."""

    class ExitCodes(IntEnum):
        # SUCCESS = 0
        ABORTED = 1


constants: Final[Constants] = Constants()
paths: Final[Constants.Paths] = constants.Paths()
exitc: Final[Type[Constants.ExitCodes]] = constants.ExitCodes
