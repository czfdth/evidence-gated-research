"""Choose which theme mode the workbench runs in.

Follows the operating system's colour scheme, with an explicit escape hatch for
tests and screenshots: ``CCFA_THEME=light|dark`` wins over the system. Unknown
schemes fall back to light rather than guessing.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from . import theme

MODE_ENV = "CCFA_THEME"


def current_mode() -> str:
    override = os.environ.get(MODE_ENV, "").strip().casefold()
    if override in {"light", "dark"}:
        return override
    if QGuiApplication.instance() is None:
        return theme.DEFAULT_MODE
    scheme = getattr(Qt, "ColorScheme", None)
    hints = QGuiApplication.styleHints()
    read = getattr(hints, "colorScheme", None)
    if scheme is None or not callable(read):
        return theme.DEFAULT_MODE
    try:
        return "dark" if read() == scheme.Dark else theme.DEFAULT_MODE
    except Exception:  # noqa: BLE001 - a missing scheme must not break startup
        return theme.DEFAULT_MODE


def watch(callback) -> bool:
    """Call *callback* when the OS changes scheme. Returns whether it hooked."""

    if QGuiApplication.instance() is None:
        return False
    hints = QGuiApplication.styleHints()
    signal = getattr(hints, "colorSchemeChanged", None)
    if signal is None:
        return False
    try:
        signal.connect(lambda _scheme: callback())
    except (TypeError, RuntimeError):
        return False
    return True
