"""Detect a file's real byte format and flag extension mismatches.

A figure re-encoded to another format, or simply renamed, breaks downstream
tooling while looking fine in a directory listing; only the byte signature is
honest. Files whose bytes cannot be identified are never convicted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ccfa.cli import Problem

_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"%PDF", ".pdf"),
)
JPEG_SUFFIXES = (".jpg", ".jpeg")
_IMAGE_SUFFIXES = (".png",) + JPEG_SUFFIXES + (".gif",)


def sniff(path: Path) -> str | None:
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    for signature, suffix in _MAGIC:
        if head.startswith(signature):
            return suffix
    return None


def check_figure_formats(paths: Iterable[Path]) -> list[Problem]:
    problems: list[Problem] = []
    for path in paths:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in _IMAGE_SUFFIXES:
            continue
        actual = sniff(path)
        if actual is None:
            continue
        if actual == suffix or (actual == ".jpg" and suffix in JPEG_SUFFIXES):
            continue
        problems.append(
            Problem(
                "figure-format",
                str(path),
                None,
                f"文件字节是 {actual.lstrip('.')}，扩展名却是 {suffix.lstrip('.')}"
                f"（应重新编码，不要改名）",
            )
        )
    return problems
