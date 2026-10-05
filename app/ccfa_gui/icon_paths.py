"""Vector icon geometry, shared by the Qt chrome and the design mockups.

Lucide-style 24x24 stroke icons (ISC licensed geometry, re-expressed here so the
app ships no new dependency). Kept free of Qt imports on purpose: the mockup
generator loads this file directly with any interpreter.
"""

from __future__ import annotations

ICONS: dict[str, tuple[str, ...]] = {
    "refresh": (
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>',
        '<path d="M21 3v5h-5"/>',
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>',
        '<path d="M8 16H3v5"/>',
    ),
    "settings": (
        '<line x1="21" x2="14" y1="4" y2="4"/>',
        '<line x1="10" x2="3" y1="4" y2="4"/>',
        '<line x1="21" x2="12" y1="12" y2="12"/>',
        '<line x1="8" x2="3" y1="12" y2="12"/>',
        '<line x1="21" x2="16" y1="20" y2="20"/>',
        '<line x1="12" x2="3" y1="20" y2="20"/>',
        '<line x1="14" x2="14" y1="2" y2="6"/>',
        '<line x1="8" x2="8" y1="10" y2="14"/>',
        '<line x1="16" x2="16" y1="18" y2="22"/>',
    ),
    "folder": (
        '<path d="m6 14 1.45-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 '
        '6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 '
        '1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    ),
    "milestones": (
        '<path d="m3 17 2 2 4-4"/>',
        '<path d="m3 7 2 2 4-4"/>',
        '<path d="M13 6h8"/>',
        '<path d="M13 12h8"/>',
        '<path d="M13 18h8"/>',
    ),
    # A bare check reads better than a circled one at 16px on the accent fill.
    "validate": ('<path d="M20 6 9 17l-5-5"/>',),
    "checkpoints": (
        '<path d="M2 21a8 8 0 0 1 13.292-6"/>',
        '<circle cx="10" cy="8" r="5"/>',
        '<path d="m16 19 2 2 4-4"/>',
    ),
    "readiness": (
        '<path d="m12 14 4-4"/>',
        '<path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    ),
    # Stage transitions run both ways, so the glyph is a two-headed arrow.
    "stages": (
        '<path d="m16 3 4 4-4 4"/>',
        '<path d="M20 7H4"/>',
        '<path d="m8 21-4-4 4-4"/>',
        '<path d="M4 17h16"/>',
    ),
    # Export writes a file to disk, so the glyph is a download-to-tray arrow.
    "export": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
        '<path d="m7 10 5 5 5-5"/>',
        '<path d="M12 15V3"/>',
    ),
    "send": (
        '<path d="m5 12 7-7 7 7"/>',
        '<path d="M12 19V5"/>',
    ),
    "chat": (
        '<path d="M22 17a2 2 0 0 1-2 2H6l-4 4V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/>',
    ),
    "inbox": (
        '<path d="M22 12h-6l-2 3h-4l-2-3H2"/>',
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 '
        '2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    ),
}


def svg(name: str, colour: str, size: int = 16, stroke: float = 1.75) -> str:
    """Return a standalone SVG document for *name* in *colour*."""

    body = "".join(ICONS[name])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{colour}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def mark_svg(colour: str, glyph: str, size: int = 22, radius: int = 6) -> str:
    """Return the app mark: a filled rounded square with three text bars."""

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24">'
        f'<rect x="0" y="0" width="24" height="24" rx="{radius}" fill="{colour}"/>'
        f'<g fill="none" stroke="{glyph}" stroke-width="1.8" stroke-linecap="round">'
        '<path d="M7 8h10"/><path d="M7 12h10"/><path d="M7 16h6"/>'
        "</g></svg>"
    )
