"""Resolve a tagged source path and key path against a live data file.

Source paths come from the manuscript text, so the base directory is a real
containment boundary: absolute paths and '..' escapes are refused rather
than silently re-rooted. JSON/YAML key paths are dot-separated, with '\\.'
escaping a literal dot; CSV key paths are '<row>.<column>' over 0-indexed
data rows (the header row is not counted).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ccfa.cli import ToolEnvironmentError

try:
    import yaml
except ImportError:  # pragma: no cover - only reachable without PyYAML
    yaml = None


class SourceError(Exception):
    """A tag's source could not be read, parsed, or navigated."""


def resolve_within_base_dir(source_path: str, base_dir: Path | None) -> Path:
    if Path(source_path).is_absolute():
        raise SourceError(f"source path must be relative: {source_path}")
    base = Path(base_dir or Path.cwd()).resolve()
    resolved = (base / source_path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise SourceError(
            f"source path '{source_path}' escapes base dir '{base}'"
        ) from None
    return resolved


def load_source(path: Path) -> tuple[str, object]:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return "json", json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SourceError(f"JSON 解析失败: {exc}") from exc
    if suffix in (".yaml", ".yml"):
        if yaml is None:
            raise ToolEnvironmentError("PyYAML 未安装，无法读取 YAML 源")
        try:
            return "yaml", yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise SourceError(f"YAML 解析失败: {exc}") from exc
    if suffix == ".csv":
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                return "csv", list(csv.DictReader(handle))
        except csv.Error as exc:
            raise SourceError(f"CSV 解析失败: {exc}") from exc
    raise SourceError(f"不支持的源文件类型: {path.suffix}")


def split_key_path(key_path: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(key_path):
        char = key_path[index]
        if char == "\\" and index + 1 < len(key_path) and key_path[index + 1] == ".":
            current.append(".")
            index += 2
            continue
        if char == ".":
            parts.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def navigate(kind: str, data: object, key_path: str) -> object:
    if kind in ("json", "yaml"):
        node = data
        for part in split_key_path(key_path):
            if isinstance(node, list):
                node = node[int(part)]
            elif isinstance(node, dict):
                if part not in node:
                    raise SourceError(f"key '{part}' not found (path: {key_path})")
                node = node[part]
            else:
                raise SourceError(
                    f"cannot navigate into {type(node).__name__} with '{part}'"
                )
        return node
    if kind == "csv":
        parts = key_path.split(".", 1)
        if len(parts) != 2:
            raise SourceError(
                f"CSV key path must be '<row>.<column>', got '{key_path}'"
            )
        row_text, column = parts
        try:
            row_index = int(row_text)
        except ValueError:
            raise SourceError(f"CSV row index is not an integer: {row_text!r}") from None
        if not isinstance(data, list):
            raise SourceError("CSV data is not a list of rows")
        if row_index < 0 or row_index >= len(data):
            raise SourceError(f"row {row_index} out of range (0..{len(data) - 1})")
        row = data[row_index]
        if column not in row:
            raise SourceError(f"column '{column}' not found")
        return row[column]
    raise SourceError(f"unknown source kind: {kind}")
