"""Launch the workbench shell.

Run from the ``app`` directory with ``PYTHONPATH`` pointing at ``tools``::

    app/.venv/Scripts/python.exe -m ccfa_gui.main
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def create_window(
    repo_root: Path | None = None,
    *,
    secret_store=None,
    settings_path: Path | None = None,
) -> MainWindow:
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
    return MainWindow(
        root,
        secret_store=secret_store,
        settings_path=settings_path,
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="论文工作台")
    parser.add_argument("--repo-root")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = create_window(args.repo_root)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
