# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the paper workbench.

Only the GUI app is bundled: the workbench talks to the research workflow over
the CLI, so no ``ccfa`` module is collected here. The installed app therefore
expects the workflow repository path to be configured (settings dialog or
``CCFA_WORKFLOW_ROOT``).
"""

from pathlib import Path

APP_DIR = Path(SPECPATH)

a = Analysis(
    [str(APP_DIR / "ccfa_workbench.py")],
    pathex=[str(APP_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "ccfa_core.atomic",
        "ccfa_core.checks",
        "ccfa_core.engines.base",
        "ccfa_core.engines.codex_exec",
        "ccfa_core.engines.openai_compat",
        "ccfa_core.http_tools",
        "ccfa_core.projects",
        "ccfa_core.secrets",
        "ccfa_core.settings",
        "ccfa_core.tools_bridge",
        "ccfa_core.workflow",
        "ccfa_gui.chat_panel",
        "ccfa_gui.settings_dialog",
        "ccfa_gui.window",
        "keyring.backends.Windows",
        # Declared explicitly: PyInstaller's PySide6 hook did not infer
        # QtWidgets here, and the frozen app then failed with
        # "DLL load failed while importing QtWidgets" because Qt6Widgets.dll
        # never made it into the bundle.
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ccfa-workbench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ccfa-workbench",
)
