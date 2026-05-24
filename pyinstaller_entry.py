"""Entry point used by PyInstaller's `SteamPadBridge.spec`.

`src/__main__.py` uses package-relative imports (`from .app import ...`) which
require a parent-package context that PyInstaller doesn't synthesize when you
point it directly at the file. This shim imports the package proper, then
calls into it — same code path as `python -m src`.
"""

from __future__ import annotations

import sys

from src.__main__ import main


if __name__ == "__main__":
    sys.exit(main())
