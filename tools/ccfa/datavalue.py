"""Decide whether a claimed value matches its live source value.

A manuscript rounds numbers for readability, so exact equality is the wrong
test. A claim written to three decimals implies a half-unit tolerance in the
last place -- that rule is what keeps a correct draft from failing on every
rounded figure, without one hand-picked global tolerance.
"""

from __future__ import annotations

import re

_THOUSANDS = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def _parse_number(value: object) -> float | None:
    text = str(value).strip()
    if _THOUSANDS.match(text):
        text = text.replace(",", "")
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def implied_rounding_tolerance(claimed: str) -> float:
    text = claimed.strip().lstrip("-")
    if "." not in text:
        return 0.0
    decimals = len(text.split(".", 1)[1])
    return 0.5 * (10 ** -decimals)


def values_match(
    claimed: str,
    actual: object,
    tolerance: float = 1e-9,
    rel_tolerance: float = 0.0,
) -> bool:
    claimed_text = claimed.strip()
    actual_text = str(actual).strip()
    if claimed_text == actual_text:
        return True
    claimed_lower = claimed_text.lower()
    actual_lower = actual_text.lower()
    if claimed_lower in ("true", "false") and actual_lower in ("true", "false"):
        return claimed_lower == actual_lower
    claimed_number = _parse_number(claimed_text)
    actual_number = _parse_number(actual_text)
    if claimed_number is None or actual_number is None:
        return False
    difference = abs(claimed_number - actual_number)
    if difference <= tolerance:
        return True
    if rel_tolerance > 0 and difference <= rel_tolerance * max(
        abs(claimed_number), abs(actual_number)
    ):
        return True
    return difference <= implied_rounding_tolerance(claimed_text)
