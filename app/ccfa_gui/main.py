"""Launch the workbench shell.

Run from source::

    app/.venv/Scripts/python.exe -m ccfa_gui.main

The installed build has no repository to fall back on, so it resolves settings
from ``%APPDATA%`` and expects the workflow directory to be configured in the
settings dialog (or via ``CCFA_WORKFLOW_ROOT``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .window import MainWindow


def self_check(args) -> int:
    """Report what the frozen app found, without starting the GUI.

    Packaging needs a scriptable answer to "did the install land next to a
    usable workflow": this resolves the same discovery path the window uses and
    runs the workflow's own probe.
    """

    from ccfa_core.settings import default_settings_path
    from ccfa_core.workflow import WorkflowClient

    root = (
        Path(args.repo_root)
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    settings_path = (
        Path(args.settings)
        if args.settings
        else default_settings_path(root)
    )
    client = WorkflowClient()
    ok, detail = client.probe()
    print(
        json.dumps(
            {
                "repo_root": str(root),
                "settings_path": str(settings_path),
                "workflow_root": str(client.root),
                "workflow_python": str(client.python) if client.python else None,
                "probe_ok": bool(ok),
                "probe_detail": detail,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


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
    parser.add_argument(
        "--settings",
        help="settings.json 路径（默认：源码运行用 app/settings.json，"
        "安装版用 %APPDATA%/ccfa-workbench/settings.json）",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="不启动界面：打印工作流发现结果与连接测试，供安装后冒烟",
    )
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check(args)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = create_window(
        args.repo_root,
        settings_path=Path(args.settings) if args.settings else None,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
