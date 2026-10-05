"""Render the shared icon geometry into QIcon / QPixmap.

Qt's stock icons are OS themed and looked dated next to the rest of the
workbench, so the chrome uses the vector set in ``icon_paths`` instead. At 2x
device pixel ratio the result stays crisp.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import icon_paths
from . import theme


def pixmap(name: str, *, colour: str = theme.INK, size: int = 16) -> QPixmap:
    """Render one icon to a transparent pixmap at 2x for HiDPI screens."""

    if name not in icon_paths.ICONS:
        return QPixmap()
    scale = 2
    renderer = QSvgRenderer(
        icon_paths.svg(name, colour, size=size * scale).encode("utf-8")
    )
    image = QPixmap(QSize(size * scale, size * scale))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    image.setDevicePixelRatio(scale)
    return image


def icon(name: str, *, colour: str = theme.INK, size: int = 16) -> QIcon:
    result = pixmap(name, colour=colour, size=size)
    return QIcon(result) if not result.isNull() else QIcon()


def app_mark(size: int = 22, *, colour: str = theme.ACCENT) -> QPixmap:
    scale = 2
    renderer = QSvgRenderer(
        icon_paths.mark_svg(colour, "#ffffff", size=size * scale).encode("utf-8")
    )
    image = QPixmap(QSize(size * scale, size * scale))
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    image.setDevicePixelRatio(scale)
    return image
