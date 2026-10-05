"""Scan LaTeX sources for \\dataval tags.

A tag is ``\\dataval{source_path:key_path}{claimed_value}``. Tags inside
comments do not count, and an escaped percent does not truncate a line.
Scanning is read-only and never touches the files it reads.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, NamedTuple

from ccfa.texcomment import strip_comment


class Tag(NamedTuple):
    path: str
    line: int
    source_path: str
    key_path: str
    claimed: str


class Untagged(NamedTuple):
    path: str
    line: int
    text: str


_TAG = re.compile(r"\\dataval\{([^:}]+):([^}]+)\}\{([^}]*)\}")


def find_tags(paths: Iterable[Path]) -> list[Tag]:
    tags: list[Tag] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = strip_comment(raw_line)
            for match in _TAG.finditer(line):
                tags.append(
                    Tag(
                        str(path),
                        number,
                        match.group(1).strip(),
                        match.group(2).strip(),
                        match.group(3).strip(),
                    )
                )
    return tags


_YEAR = re.compile(r"^(19|20)\d{2}$")
_REF_CONTEXT = re.compile(
    r"(Table|Figure|Fig\.|Section|Sec\.|Eq\.|Equation|Chapter|Appendix|Step|Page|pp?\.|No\.|ref)\s*$",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?<![\w.])-?\d+\.\d+(?![\w])"
    r"|(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])"
    r"|(?<![\w.,])-?\d{2,}(?![\w.,])"
)
_BRACKET_CITATION = re.compile(r"\[\d+(,\s*\d+)*\]")


def find_untagged(path: Path) -> list[Untagged]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[Untagged] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = strip_comment(raw_line)
        tagged = [(match.start(), match.end()) for match in _TAG.finditer(line)]
        for match in _NUMBER.finditer(line):
            if any(start <= match.start() < end for start, end in tagged):
                continue
            if _YEAR.match(match.group(0)):
                continue
            before = line[max(0, match.start() - 15):match.start()]
            if _REF_CONTEXT.search(before):
                continue
            if match.start() > 0 and _BRACKET_CITATION.match(
                line[match.start() - 1:match.end() + 1]
            ):
                continue
            found.append(Untagged(str(path), number, line.strip()))
    return found
