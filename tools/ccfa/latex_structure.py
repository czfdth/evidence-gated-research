"""Structural checks for LaTeX sources.

Read-only. Comments are stripped before braces or environments are counted,
because a brace inside a comment is not document structure. The shared
strip_comment implements the even-backslash rule, so a line ending in a
literal backslash before '%' is still treated as a real comment.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ccfa.bib import load_entries
from ccfa.cli import Problem
from ccfa.texcomment import is_escaped, strip_comment
from ccfa.texscan import find_cited_keys

_ENV = re.compile(r"\\(begin|end)\{([^}]+)\}")


def _stripped_lines(path: Path) -> list[str]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [strip_comment(line) for line in text.splitlines()]


def check_braces(path: Path) -> list[Problem]:
    path = Path(path)
    problems: list[Problem] = []
    depth = 0
    for number, line in enumerate(_stripped_lines(path), start=1):
        index = 0
        while index < len(line):
            char = line[index]
            if char in "{}":
                if is_escaped(line, index):
                    index += 1
                    continue
                if char == "{":
                    depth += 1
                else:
                    depth -= 1
                    if depth < 0:
                        problems.append(
                            Problem("unbalanced-brace", str(path), number, "多余的 '}'")
                        )
                        depth = 0
            index += 1
    if depth > 0:
        problems.append(
            Problem("unbalanced-brace", str(path), None, f"有 {depth} 个 '{{' 未闭合")
        )
    return problems


def check_environments(path: Path) -> list[Problem]:
    path = Path(path)
    problems: list[Problem] = []
    stack: list[tuple[str, int]] = []
    for number, line in enumerate(_stripped_lines(path), start=1):
        for match in _ENV.finditer(line):
            kind, name = match.group(1), match.group(2)
            if kind == "begin":
                stack.append((name, number))
                continue
            if not stack:
                problems.append(
                    Problem(
                        "unmatched-environment",
                        str(path),
                        number,
                        f"\\end{{{name}}} 没有对应的 \\begin",
                    )
                )
                continue
            open_name, open_line = stack.pop()
            if open_name != name:
                problems.append(
                    Problem(
                        "unmatched-environment",
                        str(path),
                        number,
                        f"\\end{{{name}}} 与 line {open_line} 的 \\begin{{{open_name}}} 不匹配",
                    )
                )
    for name, open_line in stack:
        problems.append(
            Problem(
                "unmatched-environment",
                str(path),
                open_line,
                f"\\begin{{{name}}} 从未闭合",
            )
        )
    return problems


def scan_structure(path: Path) -> list[Problem]:
    path = Path(path)
    return check_braces(path) + check_environments(path)


_INCLUDE = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\]\s*)?\{([^}]+)\}")
_FIGURE_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".eps")


def check_citations(paths: Iterable[Path], bib_path: Path) -> list[Problem]:
    cited = find_cited_keys(paths)
    entries = load_entries(Path(bib_path))
    problems: list[Problem] = []
    for key, locations in sorted(cited.items()):
        if key in entries:
            continue
        for location in dict.fromkeys(locations):
            problems.append(
                Problem(
                    "missing-cite-key",
                    location.path,
                    location.line,
                    f"引用键不在文献表中: {key}",
                )
            )
    return problems


def check_figures(paths: Iterable[Path], figures_root: Path) -> list[Problem]:
    root = Path(figures_root)
    problems: list[Problem] = []
    for path in paths:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, raw_line in enumerate(text.splitlines(), start=1):
            line = strip_comment(raw_line)
            for match in _INCLUDE.finditer(line):
                name = match.group(1).strip()
                candidates = [root / name]
                if not Path(name).suffix:
                    candidates += [root / (name + suffix) for suffix in _FIGURE_SUFFIXES]
                if not any(candidate.exists() for candidate in candidates):
                    problems.append(
                        Problem(
                            "missing-figure",
                            str(path),
                            number,
                            f"图片文件不存在: {name}",
                        )
                    )
    return problems


def find_stray_percent(path: Path) -> list[Problem]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[Problem] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = strip_comment(line)
        if stripped == line:
            continue
        if not stripped.strip():
            continue
        if line[len(stripped) + 1:].strip():
            found.append(
                Problem(
                    "stray-percent",
                    str(path),
                    number,
                    f"行内未转义 '%' 会截断该行: {line.strip()[:60]}",
                )
            )
    return found
