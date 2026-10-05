"""Build a cross-paper research control dashboard from readiness reports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from ccfa import readiness
from ccfa.cli import tool_error
from ccfa.friction_log import write_text_output


def _paper_title(paper_root: Path, fallback: str) -> str:
    path = paper_root / "ccfa.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return fallback
    project = payload.get("project") if isinstance(payload, dict) else None
    title = project.get("title") if isinstance(project, dict) else None
    return title if isinstance(title, str) and title.strip() else fallback


def collect_reports(
    papers_root: Path,
    *,
    profile: str | None = None,
    today: date | None = None,
    builder=readiness.build_report,
) -> list[dict]:
    """Collect readiness reports for every child directory with ccfa.yaml."""
    papers_root = Path(papers_root)
    if not papers_root.is_dir():
        raise ValueError(f"papers 根目录不存在: {papers_root}")
    reports = []
    for child in sorted(papers_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or not (child / "ccfa.yaml").is_file():
            continue
        resolved = child.resolve()
        try:
            report = builder(resolved, profile=profile, today=today)
        except (OSError, ValueError) as exc:
            report = {
                "paper_root": str(resolved),
                "profile": profile or "unknown",
                "stage": {"current": "unknown", "gate": "unknown"},
                "dimensions": {
                    "schema-valid": "problem",
                    "evidence-present": "problem",
                    "gate-verified": "problem",
                    "independently-reviewed": "unknown",
                    "scientifically-accepted": "unknown",
                    "collaboration-ready": "problem",
                },
                "git": {
                    "present": False,
                    "dirty": None,
                    "commit": None,
                    "remotes": [],
                    "workflows_present": False,
                },
                "human_review": {"status": "unknown", "pending": []},
                "blocking": [f"readiness error: {exc}"],
                "ready": False,
            }
        report = dict(report)
        report["project_title"] = _paper_title(
            resolved,
            resolved.name,
        )
        reports.append(report)
    return reports


def summarize(reports: list[dict]) -> dict:
    """Reduce full readiness reports to dashboard rows and counts."""
    papers = []
    for report in reports:
        root = Path(report.get("paper_root", "."))
        blocking = [
            str(item)
            for item in report.get("blocking", [])
            if isinstance(item, str) and item.strip()
        ]
        human = report.get("human_review", {})
        pending = human.get("pending", []) if isinstance(human, dict) else []
        git = report.get("git", {}) if isinstance(report.get("git"), dict) else {}
        papers.append(
            {
                "paper": root.name,
                "title": report.get("project_title") or root.name,
                "profile": report.get("profile", "unknown"),
                "stage": report.get("stage", {}).get("current", "unknown"),
                "gate": report.get("stage", {}).get("gate", "unknown"),
                "ready": bool(report.get("ready")),
                "blocking_count": len(blocking),
                "blocking": blocking,
                "next_action": blocking[0] if blocking else "ready",
                "human_review": human.get("status", "unknown")
                if isinstance(human, dict)
                else "unknown",
                "human_pending": list(pending) if isinstance(pending, list) else [],
                "git_commit": git.get("commit"),
                "git_dirty": git.get("dirty"),
                "git_remotes": list(git.get("remotes", [])),
                "workflows_present": bool(git.get("workflows_present")),
                "dimensions": report.get("dimensions", {}),
            }
        )
    return {
        "paper_count": len(papers),
        "ready_count": sum(1 for paper in papers if paper["ready"]),
        "blocked_count": sum(1 for paper in papers if not paper["ready"]),
        "human_pending_count": sum(
            1 for paper in papers if paper["human_pending"]
        ),
        "dirty_count": sum(1 for paper in papers if paper["git_dirty"] is True),
        "missing_remote_count": sum(
            1 for paper in papers if not paper["git_remotes"]
        ),
        "papers": papers,
    }


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(summary: dict) -> str:
    lines = [
        "# Research Dashboard",
        "",
        f"- papers: {summary.get('paper_count', 0)}",
        f"- ready: {summary.get('ready_count', 0)}",
        f"- blocked: {summary.get('blocked_count', 0)}",
        f"- human pending: {summary.get('human_pending_count', 0)}",
        f"- dirty worktrees: {summary.get('dirty_count', 0)}",
        "",
        "| paper | stage | profile | ready | human review | next action |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for paper in summary.get("papers", []):
        lines.append(
            "| "
            + " | ".join(
                _cell(value)
                for value in (
                    paper.get("paper", ""),
                    paper.get("stage", ""),
                    paper.get("profile", ""),
                    str(paper.get("ready", False)).lower(),
                    paper.get("human_review", ""),
                    paper.get("next_action", ""),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="汇总 papers/ 下每篇论文的 readiness 与下一动作"
    )
    parser.add_argument("--papers-root", default="papers")
    parser.add_argument("--profile", choices=readiness.PROFILES)
    parser.add_argument("--today", help="注入今天日期 YYYY-MM-DD")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        today = date.fromisoformat(args.today) if args.today else None
        reports = collect_reports(
            Path(args.papers_root),
            profile=args.profile,
            today=today,
        )
        summary = summarize(reports)
        text = (
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.format == "json"
            else render_markdown(summary)
        )
        if args.out:
            write_text_output(Path(args.out), text, force=args.force)
        else:
            print(text, end="")
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
