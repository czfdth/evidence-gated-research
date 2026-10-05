"""Extract text from a rendered PDF and find unresolved reference markers.

The rendered PDF is the baseline, not the compile log: a citation that failed
to resolve leaves a literal '?' in the output even when the build succeeded.
PyMuPDF is optional at runtime -- when it is unavailable this module returns
None, and the caller must report the check as skipped, never as passing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ccfa.cli import Problem

Reader = Callable[[Path], str]

# A run of '?' bounded by non-word characters is a marker. Requiring boundary
# characters on both sides of each '?' missed the canonical unresolved-ref
# marker "??", because neither question mark in the run had boundaries outside
# both sides.
_MARKER = re.compile(r"(?<![\w])\?+(?![\w])")


def extract_text(pdf: Path, reader: Reader | None = None) -> str | None:
    pdf = Path(pdf)
    if reader is not None:
        return reader(pdf)
    try:
        import pymupdf
    except ImportError:
        return None
    try:
        with pymupdf.open(str(pdf)) as document:
            return "".join(page.get_text() for page in document)
    except Exception:
        # Any failure to read means "text unavailable" -- the caller reports a
        # skipped check. A corrupt PDF must never crash the tool, and must
        # never be mistaken for a passing check.
        return None


def find_unresolved_markers(text: str, path: str) -> list[Problem]:
    problems: list[Problem] = []
    for match in _MARKER.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        problems.append(
            Problem("unresolved-marker", path, line, "PDF 文本中存在未解析的引用标记 '?'")
        )
    return problems
