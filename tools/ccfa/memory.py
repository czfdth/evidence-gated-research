"""Read and write project-scoped research memory.

Ideas live in ``memory/ideas.md`` and dead ends in ``memory/dead-ends.md``.
Both files are YAML lists with fixed field order. A dead end must include
``reopen_if`` so it can be reconsidered when conditions change.

Search is deterministic substring matching, not semantic retrieval. Claim
status writeback is not implemented in this layer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, save_text_atomically, tool_error

VALID_IDEA_STATUSES = ("active", "abandoned", "merged")
IDEAS_FILE = "memory/ideas.md"
DEAD_ENDS_FILE = "memory/dead-ends.md"

IDEA_FIELDS = ("id", "date", "idea", "status", "notes")
DEAD_END_FIELDS = ("id", "date", "idea", "reason", "evidence", "reopen_if")

_IDEAS_HEADER = "# 研究记忆（脚本读写，勿改字段名）\n"
_DEAD_ENDS_HEADER = "# 反重复记忆（脚本读写，勿改字段名）\n"
_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ID_PATTERN = re.compile(r"^(?:I|DE)[1-9][0-9]*$")
_IDEA_SEARCH_FIELDS = ("idea", "notes")
_DEAD_END_SEARCH_FIELDS = ("idea", "reason", "evidence", "reopen_if")


def load_memory(path: Path) -> list[dict]:
    """Load a YAML list. A missing file is an empty memory."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"无法读取记忆文件 {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"记忆文件不是合法 YAML: {path}: {exc}") from exc
    if data is None:
        return []
    if not isinstance(data, list):
        raise ValueError(f"记忆文件顶层必须是列表: {path}")
    return data


def _ordered_entry(entry: object) -> object:
    if not isinstance(entry, dict):
        return entry
    if any(key in entry for key in ("reason", "evidence", "reopen_if")):
        order = DEAD_END_FIELDS
    else:
        order = IDEA_FIELDS
    ordered = {key: entry[key] for key in order if key in entry}
    for key, value in entry.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def _dump_memory(path: Path, entries: list[dict]) -> str:
    header = (
        _DEAD_ENDS_HEADER
        if Path(path).name == "dead-ends.md"
        else _IDEAS_HEADER
    )
    ordered = [_ordered_entry(entry) for entry in entries]
    body = yaml.safe_dump(
        ordered,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    if not body.endswith("\n"):
        body += "\n"
    return header + body


def save_memory(path: Path, entries: list[dict]) -> None:
    """Atomically write entries with fixed field order."""
    save_text_atomically(
        Path(path),
        _dump_memory(Path(path), entries),
        description="记忆文件",
    )


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} 不能为空")
    return value


def _validate_date(value: object) -> str:
    text = _required_text("date", value)
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"date 必须匹配 YYYY-MM-DD: {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"date 不是合法日期: {text!r}") from exc
    return text


def _next_id(entries: list[dict], prefix: str) -> str:
    pattern = re.compile(rf"^{prefix}([1-9][0-9]*)$")
    numbers: list[int] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str):
            continue
        match = pattern.fullmatch(entry_id)
        if match is not None:
            numbers.append(int(match.group(1)))
    return f"{prefix}{max(numbers, default=0) + 1}"


def _date_is_valid(value: object) -> bool:
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _missing_text(entry: dict, field: str) -> bool:
    if field not in entry:
        return True
    value = entry[field]
    return not isinstance(value, str) or not value.strip()


def _entry_problems(
    path: Path,
    entry: object,
    kind: str,
    duplicate_ids: set[str],
    position: int,
) -> list[Problem]:
    if isinstance(entry, dict):
        entry_id = entry.get("id")
        locator = (
            f"条目 {entry_id}"
            if isinstance(entry_id, str) and entry_id.strip()
            else f"第 {position} 条"
        )
    else:
        locator = f"第 {position} 条"

    if not isinstance(entry, dict):
        return [
            Problem(
                "memory-entry-not-mapping",
                str(path),
                None,
                f"{locator}: 记忆条目必须是映射",
            )
        ]

    problems: list[Problem] = []
    for field in ("id", "date", "idea"):
        if _missing_text(entry, field):
            problems.append(
                Problem(
                    "memory-missing-field",
                    str(path),
                    None,
                    f"{locator}: 记忆条目缺少非空字段: {field}",
                )
            )

    date_value = entry.get("date")
    if "date" in entry and not _date_is_valid(date_value):
        problems.append(
            Problem(
                "memory-invalid-date",
                str(path),
                None,
                f"{locator}: date 必须匹配 YYYY-MM-DD: {date_value!r}",
            )
        )

    entry_id = entry.get("id")
    if "id" in entry and (
        not isinstance(entry_id, str) or _ID_PATTERN.fullmatch(entry_id) is None
    ):
        problems.append(
            Problem(
                "memory-invalid-id",
                str(path),
                None,
                f"{locator}: id 必须匹配 (I|DE)[1-9][0-9]*: {entry_id!r}",
            )
        )
    if isinstance(entry_id, str) and entry_id in duplicate_ids:
        problems.append(
            Problem(
                "memory-duplicate-id",
                str(path),
                None,
                f"{locator}: 同一记忆文件内 id 重复: {entry_id}",
            )
        )

    if kind == "ideas" and entry.get("status") not in VALID_IDEA_STATUSES:
        problems.append(
            Problem(
                "memory-invalid-status",
                str(path),
                None,
                f"{locator}: idea status 非法: {entry.get('status')!r}",
            )
        )

    if kind == "dead-ends":
        for field in ("reason", "evidence"):
            if _missing_text(entry, field):
                problems.append(
                    Problem(
                        "memory-missing-field",
                        str(path),
                        None,
                        f"{locator}: dead-end 缺少非空字段: {field}",
                    )
                )
        reopen_if = entry.get("reopen_if")
        if not isinstance(reopen_if, str) or not reopen_if.strip():
            problems.append(
                Problem(
                    "deadend-missing-reopen-if",
                    str(path),
                    None,
                    f"{locator}: dead-end 缺少非空 reopen_if",
                )
            )
    return problems


def _duplicate_ids(entries: list[object]) -> set[str]:
    counts = Counter(
        entry["id"]
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and _ID_PATTERN.fullmatch(entry["id"]) is not None
    )
    return {entry_id for entry_id, count in counts.items() if count > 1}


def check_memory(paper_root: Path) -> list[Problem]:
    """Read-only audit of ideas and dead-end entries."""
    paper_root = Path(paper_root)
    ideas_path = paper_root / IDEAS_FILE
    dead_ends_path = paper_root / DEAD_ENDS_FILE
    ideas = load_memory(ideas_path)
    dead_ends = load_memory(dead_ends_path)

    problems: list[Problem] = []
    idea_duplicates = _duplicate_ids(ideas)
    problems.extend(
        problem
        for position, entry in enumerate(ideas, start=1)
        for problem in _entry_problems(
            ideas_path,
            entry,
            "ideas",
            idea_duplicates,
            position,
        )
    )
    dead_end_duplicates = _duplicate_ids(dead_ends)
    problems.extend(
        problem
        for position, entry in enumerate(dead_ends, start=1)
        for problem in _entry_problems(
            dead_ends_path,
            entry,
            "dead-ends",
            dead_end_duplicates,
            position,
        )
    )
    return problems


def _searchable(entry: dict, fields: tuple[str, ...], query: str) -> bool:
    for field in fields:
        value = entry.get(field)
        if isinstance(value, str) and query in value.casefold():
            return True
    return False


def search_memory(paper_root: Path, query: str) -> dict:
    """Search ideas and dead ends with case-insensitive substring matching."""
    if not isinstance(query, str):
        raise ValueError("query 必须是字符串")
    query = query.strip()
    if not query:
        raise ValueError("query 不能为空")

    paper_root = Path(paper_root)
    ideas_path = paper_root / IDEAS_FILE
    dead_ends_path = paper_root / DEAD_ENDS_FILE
    ideas = load_memory(ideas_path)
    dead_ends = load_memory(dead_ends_path)
    folded = query.casefold()

    matches: dict[str, list[dict]] = {"ideas": [], "dead_ends": []}
    skipped: list[dict] = []
    for kind, key, path, entries, fields in (
        ("ideas", "ideas", ideas_path, ideas, _IDEA_SEARCH_FIELDS),
        (
            "dead-ends",
            "dead_ends",
            dead_ends_path,
            dead_ends,
            _DEAD_END_SEARCH_FIELDS,
        ),
    ):
        duplicate_ids = _duplicate_ids(entries)
        for position, entry in enumerate(entries, start=1):
            problems = _entry_problems(
                path,
                entry,
                kind,
                duplicate_ids,
                position,
            )
            if problems:
                entry_id = (
                    entry.get("id")
                    if isinstance(entry, dict)
                    and isinstance(entry.get("id"), str)
                    else None
                )
                skipped.append(
                    {
                        "file": path.relative_to(paper_root).as_posix(),
                        "id": entry_id,
                        "codes": [problem.code for problem in problems],
                    }
                )
                continue
            if _searchable(entry, fields, folded):
                matches[key].append(dict(entry))
    return {
        "query": query,
        "ideas": matches["ideas"],
        "dead_ends": matches["dead_ends"],
        "skipped_invalid": len(skipped),
        "skipped": skipped,
    }


def add_idea(
    paper_root: Path,
    *,
    idea: str,
    date: str,
    status: str = "active",
    notes: str | None = None,
) -> dict:
    """Append one idea and return the written entry."""
    idea = _required_text("idea", idea)
    date_text = _validate_date(date)
    if status not in VALID_IDEA_STATUSES:
        raise ValueError(
            f"status 非法: {status!r}，应为 {' / '.join(VALID_IDEA_STATUSES)}"
        )

    path = Path(paper_root) / IDEAS_FILE
    entries = load_memory(path)
    entry = {
        "id": _next_id(entries, "I"),
        "date": date_text,
        "idea": idea,
        "status": status,
        "notes": notes,
    }
    entries.append(entry)
    save_memory(path, entries)
    return entry


def add_dead_end(
    paper_root: Path,
    *,
    idea: str,
    date: str,
    reason: str | None = None,
    evidence: str | None = None,
    reopen_if: str | None = None,
) -> dict:
    """Append one dead end and return the written entry."""
    idea = _required_text("idea", idea)
    reason = _required_text("reason", reason)
    evidence = _required_text("evidence", evidence)
    reopen_if = _required_text("reopen_if", reopen_if)
    date_text = _validate_date(date)

    path = Path(paper_root) / DEAD_ENDS_FILE
    entries = load_memory(path)
    entry = {
        "id": _next_id(entries, "DE"),
        "date": date_text,
        "idea": idea,
        "reason": reason,
        "evidence": evidence,
        "reopen_if": reopen_if,
    }
    entries.append(entry)
    save_memory(path, entries)
    return entry


def list_memory(
    paper_root: Path,
    *,
    kind: str = "all",
    status: str | None = None,
) -> dict:
    """List stored ideas and dead ends, optionally filtered."""
    if kind not in ("all", "ideas", "dead-ends"):
        raise ValueError("kind 必须是 all / ideas / dead-ends")
    if status is not None and status not in VALID_IDEA_STATUSES:
        raise ValueError(
            f"status 非法: {status!r}，应为 {' / '.join(VALID_IDEA_STATUSES)}"
        )

    paper_root = Path(paper_root)
    ideas = (
        load_memory(paper_root / IDEAS_FILE)
        if kind in ("all", "ideas")
        else []
    )
    dead_ends = (
        load_memory(paper_root / DEAD_ENDS_FILE)
        if kind in ("all", "dead-ends")
        else []
    )
    if status is not None:
        ideas = [
            entry
            for entry in ideas
            if isinstance(entry, dict) and entry.get("status") == status
        ]
    return {"ideas": ideas, "dead_ends": dead_ends}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "读写项目研究记忆；claim 状态回写未实现。"
        )
    )
    parser.add_argument(
        "--paper-root",
        default=".",
        help="论文项目根目录（默认: 当前目录）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    idea = subparsers.add_parser("add-idea", help="追加一条选题想法")
    idea.add_argument("--idea", required=True)
    idea.add_argument("--date", required=True)
    idea.add_argument(
        "--status",
        choices=VALID_IDEA_STATUSES,
        default="active",
    )
    idea.add_argument("--notes")

    dead_end = subparsers.add_parser("add-dead-end", help="追加一条反重复死路")
    dead_end.add_argument("--idea", required=True)
    dead_end.add_argument("--reason", required=True)
    dead_end.add_argument("--evidence", required=True)
    dead_end.add_argument("--reopen-if", required=True)
    dead_end.add_argument("--date", required=True)

    listing = subparsers.add_parser("list", help="列出记忆条目")
    listing.add_argument(
        "--kind",
        choices=("all", "ideas", "dead-ends"),
        default="all",
    )
    listing.add_argument("--status", choices=VALID_IDEA_STATUSES)

    subparsers.add_parser(
        "check",
        help="只读审计 ideas/dead-ends 的固定字段和枚举",
        description="读取时逐条重校验；本命令不写盘。",
    )
    search = subparsers.add_parser(
        "search",
        help="用确定性子串匹配检索研究记忆",
        description=(
            "对 ideas 和 dead-ends 做大小写不敏感的确定性子串匹配，"
            "不是语义检索；dead-end 命中会原样携带 reopen_if。"
        ),
    )
    search.add_argument("query")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        paper_root = Path(args.paper_root)
        if args.command == "add-idea":
            result = add_idea(
                paper_root,
                idea=args.idea,
                date=args.date,
                status=args.status,
                notes=args.notes,
            )
        elif args.command == "add-dead-end":
            result = add_dead_end(
                paper_root,
                idea=args.idea,
                reason=args.reason,
                evidence=args.evidence,
                reopen_if=args.reopen_if,
                date=args.date,
            )
        elif args.command == "check":
            return emit(check_memory(paper_root))
        elif args.command == "search":
            result = search_memory(paper_root, args.query)
        else:
            result = list_memory(
                paper_root,
                kind=args.kind,
                status=args.status,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
