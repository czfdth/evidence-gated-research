"""Audit worktree drift against the mandatory workflow change log."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ccfa import change_log
from ccfa.cli import tool_error
from ccfa.test_impact import collect_changed_paths


def audit(repo_root: Path, *, base: str | None = None) -> dict:
    repo_root = Path(repo_root).resolve()
    changed = list(
        collect_changed_paths(repo_root, base=base, include_worktree=True)
    )
    entries, problems = change_log.load_entries(repo_root)
    covered_paths = {
        change_log._normalize(path)
        for entry in entries
        for path in entry.get("files", [])
    }
    relevant = []
    excluded = []
    for path in changed:
        normalized = change_log._normalize(path)
        if change_log._is_workflow_file(normalized):
            relevant.append(normalized)
        else:
            excluded.append(normalized)
    covered = sorted(path for path in relevant if path in covered_paths)
    uncovered = sorted(path for path in relevant if path not in covered_paths)
    return {
        "repo_root": str(repo_root),
        "changed_count": len(changed),
        "workflow_changed_count": len(relevant),
        "covered": covered,
        "uncovered": uncovered,
        "excluded": sorted(excluded),
        "change_log_problems": [problem._asdict() for problem in problems],
        "strict_pass": not uncovered and not problems,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Worktree Audit",
        "",
        f"- changed: {report.get('changed_count', 0)}",
        f"- workflow changed: {report.get('workflow_changed_count', 0)}",
        f"- covered: {len(report.get('covered', []))}",
        f"- uncovered: {len(report.get('uncovered', []))}",
        "",
        "## Uncovered",
        "",
    ]
    uncovered = report.get("uncovered", [])
    if uncovered:
        lines.extend(f"- `{path}`" for path in uncovered)
    else:
        lines.append("- none")
    lines.extend(["", "## Covered", ""])
    covered = report.get("covered", [])
    if covered:
        lines.extend(f"- `{path}`" for path in covered)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="worktree change-log coverage audit")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out")
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        report = audit(Path(args.repo_root), base=args.base)
        text = (
            render_markdown(report)
            if args.format == "markdown"
            else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        if args.strict and not report["strict_pass"]:
            return 1
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
