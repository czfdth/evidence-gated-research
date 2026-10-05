"""Append-only workflow change log with a fail-closed coverage check."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.test_impact import collect_changed_paths


LOG_JSONL = "docs/workflow-change-log.jsonl"
LOG_MARKDOWN = "docs/workflow-change-log.md"
REQUIRED_FIELDS = (
    "id",
    "timestamp",
    "summary",
    "reason",
    "files",
    "tests",
    "status",
    "author",
)
STATUSES = {"complete", "pending", "blocked"}
EXCLUDED_PREFIXES = (
    "papers/",
    "library/",
    "ccfa-workfiles/",
    "build/",
    "dist/",
    ".git/",
    ".ruff_cache/",
)
EXCLUDED_FILES = {
    LOG_JSONL,
    LOG_MARKDOWN,
}
LOG_RELEVANT_FILES = {
    "README.md",
    "AGENTS.md",
    "ccfa.yaml.template",
    "ruff.toml",
    "SECURITY.md",
    "CITATION.cff",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize(path: str) -> str:
    normalized = str(path).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _is_workflow_file(path: str) -> bool:
    normalized = _normalize(path)
    if normalized in EXCLUDED_FILES:
        return False
    if normalized in LOG_RELEVANT_FILES:
        return True
    if normalized.startswith(EXCLUDED_PREFIXES):
        return False
    return normalized.startswith(
        (
            ".github/",
            "app/",
            "automation/",
            "checklists/",
            "docs/",
            "scripts/",
            "tools/",
        )
    )


def _load_entries(repo_root: Path) -> tuple[list[dict], list[Problem]]:
    path = Path(repo_root) / LOG_JSONL
    if not path.is_file():
        return [], [
            Problem("change-log-missing", str(path), None, "变更日志不存在")
        ]
    entries: list[dict] = []
    problems: list[Problem] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(
                Problem(
                    "change-log-malformed",
                    str(path),
                    line_number,
                    f"JSON 非法: {exc}",
                )
            )
            continue
        if not isinstance(entry, dict):
            problems.append(
                Problem(
                    "change-log-malformed",
                    str(path),
                    line_number,
                    "entry 必须是对象",
                )
            )
            continue
        missing = [field for field in REQUIRED_FIELDS if field not in entry]
        if missing:
            problems.append(
                Problem(
                    "change-log-malformed",
                    str(path),
                    line_number,
                    f"entry 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        if entry.get("status") not in STATUSES:
            problems.append(
                Problem(
                    "change-log-malformed",
                    str(path),
                    line_number,
                    f"status 非法: {entry.get('status')!r}",
                )
            )
        for field in ("id", "timestamp", "summary", "reason", "author"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                problems.append(
                    Problem(
                        "change-log-malformed",
                        str(path),
                        line_number,
                        f"{field} 必须是非空字符串",
                    )
                )
        for field in ("files", "tests"):
            values = entry.get(field)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value.strip() for value in values
            ):
                problems.append(
                    Problem(
                        "change-log-malformed",
                        str(path),
                        line_number,
                        f"{field} 必须是非空字符串数组",
                    )
                )
        entries.append(entry)
    return entries, problems


def load_entries(repo_root: Path) -> tuple[list[dict], list[Problem]]:
    """Public read-only access to the append-only change log entries."""
    return _load_entries(Path(repo_root))


def render_markdown(entries: list[dict]) -> str:
    lines = [
        "# Workflow Change Log",
        "",
        "Generated from `docs/workflow-change-log.jsonl`. Append-only; do not",
        "rewrite historical entries.",
        "",
    ]
    for entry in entries:
        lines.extend(
            [
                f"## {entry.get('id')} - {entry.get('summary')}",
                "",
                f"- timestamp: `{entry.get('timestamp')}`",
                f"- status: `{entry.get('status')}`",
                f"- author: `{entry.get('author')}`",
                f"- reason: {entry.get('reason')}",
                "- files:",
            ]
        )
        lines.extend(f"  - `{path}`" for path in entry.get("files", []))
        lines.append("- tests:")
        lines.extend(f"  - `{test}`" for test in entry.get("tests", []))
        if entry.get("notes"):
            lines.append(f"- notes: {entry['notes']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def add_entry(
    repo_root: Path,
    *,
    summary: str,
    reason: str,
    files: list[str],
    tests: list[str],
    author: str = "codex",
    status: str = "complete",
    notes: str = "",
) -> dict:
    repo_root = Path(repo_root).resolve()
    if status not in STATUSES:
        raise ValueError(f"status 非法: {status!r}")
    if not summary.strip() or not reason.strip():
        raise ValueError("summary/reason 不能为空")
    normalized_files = sorted(
        {_normalize(path) for path in files if path.strip()}
    )
    normalized_tests = sorted(
        {test.strip() for test in tests if test.strip()}
    )
    if not normalized_files or not normalized_tests:
        raise ValueError("files 与 tests 都必须非空")
    timestamp = _now_iso()
    digest = hashlib.sha256(
        json.dumps(
            {
                "timestamp": timestamp,
                "summary": summary,
                "files": normalized_files,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:10]
    entry = {
        "id": f"WC-{timestamp.replace(':', '').replace('-', '')}-{digest}",
        "timestamp": timestamp,
        "summary": summary.strip(),
        "reason": reason.strip(),
        "files": normalized_files,
        "tests": normalized_tests,
        "status": status,
        "author": author.strip() or "unknown",
        "notes": notes.strip(),
    }
    path = repo_root / LOG_JSONL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    entries, problems = _load_entries(repo_root)
    if problems:
        raise ValueError(problems[0].message)
    save_text_atomically(
        repo_root / LOG_MARKDOWN,
        render_markdown(entries),
        description="workflow change log",
    )
    return entry


def check(
    repo_root: Path,
    *,
    base: str | None = None,
    changed: list[str] | None = None,
) -> tuple[list[Problem], list[Problem]]:
    repo_root = Path(repo_root).resolve()
    entries, problems = _load_entries(repo_root)
    if changed is None:
        changed = list(
            collect_changed_paths(
                repo_root,
                base=base,
                include_worktree=True,
            )
        )
    relevant = sorted(
        {
            _normalize(path)
            for path in changed
            if _is_workflow_file(_normalize(path))
        }
    )
    covered = {
        _normalize(path)
        for entry in entries
        for path in entry.get("files", [])
    }
    for path in relevant:
        if path not in covered:
            problems.append(
                Problem(
                    "change-log-missing-entry",
                    str(repo_root / LOG_JSONL),
                    None,
                    f"工作流改动没有日志覆盖: {path}",
                )
            )
    return problems, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="workflow change log")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add")
    add.add_argument("--summary", required=True)
    add.add_argument("--reason", required=True)
    add.add_argument("--file", dest="files", action="append", required=True)
    add.add_argument("--test", dest="tests", action="append", required=True)
    add.add_argument("--author", default="codex")
    add.add_argument("--status", choices=sorted(STATUSES), default="complete")
    add.add_argument("--notes", default="")
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--base")
    check_parser.add_argument("--changed", action="append")
    sub.add_parser("render")
    sub.add_parser("list")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    repo_root = Path(args.repo_root)
    try:
        if args.command == "add":
            entry = add_entry(
                repo_root,
                summary=args.summary,
                reason=args.reason,
                files=args.files,
                tests=args.tests,
                author=args.author,
                status=args.status,
                notes=args.notes,
            )
            print(json.dumps(entry, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "render":
            entries, problems = _load_entries(Path(repo_root).resolve())
            if problems:
                return emit(problems, [])
            save_text_atomically(
                Path(repo_root).resolve() / LOG_MARKDOWN,
                render_markdown(entries),
                description="workflow change log",
            )
            return 0
        if args.command == "list":
            entries, problems = _load_entries(Path(repo_root).resolve())
            if problems:
                return emit(problems, [])
            for entry in entries:
                print(
                    f"{entry['id']} {entry['status']} {entry['summary']}"
                )
            return 0
        problems, advisories = check(
            repo_root,
            base=args.base,
            changed=args.changed,
        )
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
