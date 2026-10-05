"""Atomic text writes.

Mirrors ``ccfa.cli.save_text_atomically`` so the workbench does not have to
import the workflow for nine lines of generic filesystem code. Write to a
sibling ``.tmp`` file, then ``os.replace`` — a reader never sees a partial
file, and a crash leaves the previous contents intact.
"""

from __future__ import annotations

import os
from pathlib import Path


def save_text_atomically(path, text: str, description: str = "文件") -> None:
    """Write *text* to *path* atomically, folding OSError into ValueError."""

    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        what = f"{description} {path}".strip()
        raise ValueError(f"无法写入 {what}: {exc}") from exc
