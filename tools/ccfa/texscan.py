"""Scan .tex files for citation keys.

Comment handling matters: a commented-out \\cite must not count as a real
reference, and an escaped percent (\\%) must not start a comment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple

from ccfa.texcomment import strip_comment


class Location(NamedTuple):
    path: str
    line: int


_CITE = re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}")


def iter_tex_files(root: Path) -> list[Path]:
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.tex"))


def find_cited_keys(paths: Iterable[Path]) -> dict[str, list[Location]]:
    found: dict[str, list[Location]] = {}
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = strip_comment(raw_line)
            for match in _CITE.finditer(line):
                for key in match.group(1).split(","):
                    key = key.strip()
                    if key:
                        found.setdefault(key, []).append(Location(str(path), number))
    return found
