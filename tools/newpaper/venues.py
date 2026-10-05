"""Resolve a venue name to its LaTeX template directory."""

from __future__ import annotations

import os
from pathlib import Path


class VenueNotFound(Exception):
    """Raised when no template directory matches the requested venue."""


def templates_root() -> Path:
    codex_home = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")
    return Path(codex_home) / "skills" / "ccf-latex-templates"


def available_venues() -> list[str]:
    root = templates_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def resolve_venue(venue: str) -> Path:
    root = templates_root()
    target = venue.strip().lower()
    for candidate in available_venues():
        if candidate.lower() == target:
            return root / candidate
    options = ", ".join(available_venues())
    raise VenueNotFound(
        f"找不到 venue {venue!r} 的模板。模板根: {root}。"
        f"可用示例: {options or '模板根不存在'}"
    )
