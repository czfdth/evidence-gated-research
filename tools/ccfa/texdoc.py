"""Locate the main LaTeX file inside a manuscript directory."""

from __future__ import annotations

from pathlib import Path

CONVENTIONAL_STEMS = {"main", "paper"}


def find_main_tex(manuscript_dir: Path) -> Path:
    """Return the .tex file that contains \\documentclass.

    Raises FileNotFoundError when no such file exists.
    """
    root = Path(manuscript_dir)
    candidates: list[Path] = []
    for tex in sorted(root.rglob("*.tex")):
        try:
            text = tex.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\\documentclass" in text:
            candidates.append(tex)

    if not candidates:
        raise FileNotFoundError(
            f"在 {root} 中找不到包含 \\documentclass 的 .tex 文件"
        )

    for candidate in candidates:
        if candidate.stem.lower() in CONVENTIONAL_STEMS:
            return candidate
    return candidates[0]
