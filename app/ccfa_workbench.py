"""Frozen-build entry point for the paper workbench.

PyInstaller runs its entry script as ``__main__``, so ``ccfa_gui/main.py``
cannot be used directly (its relative imports would fail). This launcher uses
absolute imports instead.

It also puts the bundle's own Qt directories first on the DLL search path.
``shiboken6.abi3.dll`` lives under ``shiboken6/`` while ``QtWidgets.pyd`` lives
under ``PySide6/``, and a stray ``Qt6Core.dll`` on ``PATH`` (MiKTeX ships one)
must not win over the bundled copy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DLL_HANDLES: list = []


def _prefer_bundled_qt() -> None:
    """Put the frozen bundle's Qt directories ahead of anything on PATH."""

    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for name in ("PySide6", "shiboken6"):
        directory = base / name
        if not directory.is_dir():
            continue
        os.environ["PATH"] = (
            str(directory) + os.pathsep + os.environ.get("PATH", "")
        )
        try:
            # Keep the handle alive: when it is collected the directory is
            # dropped from the search path again.
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        except (AttributeError, OSError):
            pass


_prefer_bundled_qt()

from ccfa_gui.main import main  # noqa: E402  (must follow the DLL setup)

if __name__ == "__main__":
    raise SystemExit(main())
