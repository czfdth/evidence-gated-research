"""Small shared helpers for versioned YAML audit ledgers."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import yaml

from ccfa.cli import Problem

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_ledger(
    path: Path,
    *,
    version: int = 1,
    code: str = "ledger-invalid",
) -> tuple[object | None, list[Problem]]:
    path = Path(path)
    if not path.is_file():
        return None, [
            Problem(code, str(path), None, "台账不存在")
        ]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [
            Problem(code, str(path), None, f"台账不可读: {exc}")
        ]
    if not isinstance(payload, dict):
        return None, [
            Problem(code, str(path), None, "台账顶层必须是映射")
        ]
    if type(payload.get("version")) is not int or payload.get("version") != version:
        return None, [
            Problem(code, str(path), None, f"台账 version 必须是 {version}")
        ]
    return payload, []


def is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value) is None:
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def missing_fields(mapping: dict, fields: tuple[str, ...]) -> list[str]:
    return [field for field in fields if field not in mapping]


def problem(
    code: str,
    path: Path | str,
    line: int | None,
    message: str,
) -> Problem:
    return Problem(code, str(path), line, message)
