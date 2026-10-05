"""Escape-aware helpers for LaTeX line scanning.

A character is escaped when the run of backslashes immediately before it is
odd in number. Counting the whole run, rather than looking at one preceding
character, is what makes a literal backslash behave correctly: after two
backslashes a following percent or brace is real, after one it is escaped.
"""

from __future__ import annotations


def is_escaped(text: str, index: int) -> bool:
    """True when the character at *index* is escaped by an odd backslash run."""
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def strip_comment(line: str) -> str:
    for index, char in enumerate(line):
        if char == "%" and not is_escaped(line, index):
            return line[:index]
    return line
