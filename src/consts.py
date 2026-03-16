"""Constants of proxy manager"""

import os
from pathlib import Path
from typing import Final

__all__ = ("PATH", "FILE")


PATH: Final[Path] = Path(__file__).parent.parent
FILE: Final[str] = os.path.join(PATH, "proc")
