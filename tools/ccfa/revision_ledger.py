"""Check reviews/revision-ledger.md against the seven-column contract.

The disposition column carries the reason for a 不采纳 decision. The checker
is read-only and reports problems with real markdown line numbers.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, tool_error

EXPECTED_HEADER = (
    "Concern ID",
    "来源",
    "类型",
    "需要的新证据",
    "处置",
    "承诺风险",
    "状态",
)
VALID_TYPES = frozenset({"证据不足", "表述不清", "需要新实验", "误解"})
VALID_STATUSES = frozenset({"待处理", "已处理", "不采纳"})
VALID_RISKS = frozenset({"是", "否"})
_SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")


def _split_row(line: str) -> list[str]:
    text = line.strip()
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            if char == "|":
                current.append("|")
            else:
                current.append("\\")
                current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())

    if text.startswith("|") and cells and cells[0] == "":
        cells = cells[1:]
    if text.endswith("|") and cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_CELL.fullmatch(cell) for cell in cells)


def _find_table(lines: list[str]) -> tuple[int, int] | None:
    for index in range(1, len(lines)):
        if "|" not in lines[index]:
            continue
        separator_cells = _split_row(lines[index])
        if not _is_separator(separator_cells):
            continue
        header_index = index - 1
        while header_index >= 0 and not lines[header_index].strip():
            header_index -= 1
        if header_index >= 0 and "|" in lines[header_index]:
            return header_index, index
    return None


def _find_header_without_separator(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        if tuple(_split_row(line)) == EXPECTED_HEADER:
            return index
    return None


def check_ledger(path: Path) -> list[Problem]:
    """Return schema problems; an absent table is a legal empty ledger."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取审稿意见矩阵 {path}: {exc}") from exc

    lines = text.splitlines()
    table = _find_table(lines)
    if table is None:
        header_index = _find_header_without_separator(lines)
        if header_index is not None:
            return [
                Problem(
                    "ledger-header",
                    str(path),
                    header_index + 1,
                    "表头后缺少分隔行",
                )
            ]
        return []

    header_index, separator_index = table
    header_cells = _split_row(lines[header_index])
    separator_cells = _split_row(lines[separator_index])
    if (
        tuple(header_cells) != EXPECTED_HEADER
        or len(separator_cells) != len(EXPECTED_HEADER)
    ):
        expected = " | ".join(EXPECTED_HEADER)
        actual = " | ".join(header_cells)
        return [
            Problem(
                "ledger-header",
                str(path),
                header_index + 1,
                f"表头必须按顺序为 [{expected}]，实际为 [{actual}]",
            )
        ]

    problems: list[Problem] = []
    seen_ids: set[str] = set()
    for index in range(separator_index + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            break
        if "|" not in line:
            break

        cells = _split_row(line)
        if len(cells) != len(EXPECTED_HEADER):
            problems.append(
                Problem(
                    "ledger-row-shape",
                    str(path),
                    index + 1,
                    f"行必须有 {len(EXPECTED_HEADER)} 列，实际 {len(cells)} 列",
                )
            )
            continue

        concern_id, _source, type_, evidence, disposition, risk, status = cells
        if not concern_id:
            problems.append(
                Problem(
                    "ledger-empty-id",
                    str(path),
                    index + 1,
                    f"第 {index + 1} 行 Concern ID 不能为空",
                )
            )
            continue

        concern_id_key = concern_id.casefold()
        if concern_id_key in seen_ids:
            problems.append(
                Problem(
                    "ledger-duplicate-id",
                    str(path),
                    index + 1,
                    f"Concern ID 重复: {concern_id}",
                )
            )
        else:
            seen_ids.add(concern_id_key)

        if type_ not in VALID_TYPES:
            problems.append(
                Problem(
                    "ledger-invalid-type",
                    str(path),
                    index + 1,
                    f"类型非法: {type_!r}",
                )
            )
        if status not in VALID_STATUSES:
            problems.append(
                Problem(
                    "ledger-invalid-status",
                    str(path),
                    index + 1,
                    f"状态非法: {status!r}",
                )
            )
        elif status == "不采纳" and not disposition.strip():
            problems.append(
                Problem(
                    "ledger-missing-reason",
                    str(path),
                    index + 1,
                    "不采纳必须在处置列写明理由",
                )
            )
        if risk not in VALID_RISKS:
            problems.append(
                Problem(
                    "ledger-invalid-risk",
                    str(path),
                    index + 1,
                    f"承诺风险非法: {risk!r}",
                )
            )
        elif risk == "是" and evidence.strip() in {"", "无"}:
            problems.append(
                Problem(
                    "ledger-risk-without-evidence",
                    str(path),
                    index + 1,
                    "承诺风险=是 时必须填写新的证据（不能为空或'无'）",
                )
            )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="检查审稿意见矩阵的七列契约与承诺风险一致性"
    )
    parser.add_argument(
        "--ledger",
        required=True,
        help="reviews/revision-ledger.md 路径",
    )
    args = parser.parse_args(argv[1:])
    try:
        problems = check_ledger(Path(args.ledger))
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return emit(problems)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
