"""State a paper's whole current situation in one snapshot.

Each tool answers one question and the answers live in different reports, so
seeing "what is actually blocking this paper right now" meant running five
commands and reading five outputs. This composes the same probes - the full
readiness gate set, the platform preflight, git/CI and the submission
countdown - into one Markdown page.

It is read-only: without ``--out`` it prints and writes nothing, and it never
touches the paper's tracked files.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from ccfa import doctor as doctor_module
from ccfa import readiness as readiness_module
from ccfa.cli import save_text_atomically, tool_error
from ccfa.verifiers import FORMAL_ENGINES


def discover_paper(repo_root: Path) -> Path:
    """Return the only paper under ``papers/``, refusing to guess between many."""

    papers = Path(repo_root) / "papers"
    if not papers.is_dir():
        raise ValueError(f"没有 papers 目录: {papers}")
    candidates = sorted(
        path for path in papers.iterdir() if (path / "ccfa.yaml").is_file()
    )
    if not candidates:
        raise ValueError(f"papers/ 下没有项目（缺 ccfa.yaml）: {papers}")
    if len(candidates) > 1:
        names = "、".join(path.name for path in candidates)
        raise ValueError(
            f"papers/ 下有多个项目（{names}），请用 --paper-root 指定"
        )
    return candidates[0]


def collect_environment(
    repo_root: Path,
    *,
    skip_services: bool = False,
    skip_verifiers: bool = False,
    codex_config: Path | None = None,
):
    """Run the same platform preflight ``ccfa.doctor`` runs."""

    config_path = (
        Path(codex_config)
        if codex_config is not None
        else Path.home() / ".codex" / "config.toml"
    )
    services = () if skip_services else doctor_module.discover_services(config_path)
    return doctor_module.check_environment(
        Path(repo_root),
        services=services,
        formal_engines=() if skip_verifiers else FORMAL_ENGINES,
    )


def _bullet_list(problems, empty: str) -> list[str]:
    if not problems:
        return [f"- {empty}"]
    return [f"- `{item.code}`: {item.message}" for item in problems]


def _countdown(deadline: dict) -> str:
    days_left = deadline.get("days_left")
    raw = deadline.get("deadline")
    if not raw:
        return "无截止日期（sequential 模式）"
    if isinstance(days_left, int) and days_left < 0:
        return f"已逾期 {abs(days_left)} 天（{raw}）"
    return f"还有 {days_left} 天（{raw}）"


def render_snapshot(
    report: dict,
    env_problems,
    env_advisories,
    env_statuses,
    *,
    today: date,
) -> str:
    """Render one Markdown page from the readiness report plus the preflight."""

    paper_root = Path(report["paper_root"])
    git = report["git"]
    gates = report["gate_results"]
    failed = [item for item in gates if item["status"] != "pass"]
    passed = len(gates) - len(failed)
    blocking = report["blocking"]
    deadline = report.get("deadline", {})
    checkpoints = report.get("human_review", {}).get("checkpoints", [])

    lines = [
        "# 端到端现状快照",
        "",
        f"- 日期: `{today.isoformat()}`",
        f"- 论文: `{paper_root.name}`（HEAD `{git.get('commit') or '未知'}`）",
        f"- profile: `{report['profile']}` / assurance `{report['assurance']}`",
        f"- stage: `{report['stage']['current']}` / gate `{report['stage']['gate']}`",
        "",
        "## 一句话结论",
        "",
        f"`ready={str(bool(report['ready'])).lower()}`，阻塞 {len(blocking)} 条；"
        f"{len(gates)} 个 gate 里 {passed} 个通过"
        + (
            "，未通过：" + "、".join(f"`{item['name']}`" for item in failed)
            if failed
            else "，全部通过"
        )
        + "。",
        "",
        "## Summary",
        "",
        f"- 投稿倒计时: {_countdown(deadline)}",
        f"- 待人工复核: {len(checkpoints)} 项",
        "",
        "## 阻塞",
        "",
    ]
    lines.extend(f"- {item}" for item in blocking)
    if not blocking:
        lines.append("- 无")

    lines.extend(["", "## 门禁结论", ""])
    if gates:
        lines.append("| gate | verdict | status | problems | codes |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in gates:
            codes = "、".join(
                f"{code} ×{count}" if count > 1 else code
                for code, count in Counter(
                    problem.get("code", "?")
                    for problem in item.get("problems", [])
                ).most_common(6)
            )
            distinct = len(
                {
                    problem.get("code", "?")
                    for problem in item.get("problems", [])
                }
            )
            if distinct > 6:
                codes += f" …（{distinct} 类，共 {item.get('problem_count', 0)} 条）"
            lines.append(
                f"| `{item['name']}` | `{report.get('verdicts', {}).get(item['name'], '?')}` "
                f"| `{item['status']}` | {item.get('problem_count', 0)} | {codes or '—'} |"
            )
    else:
        lines.append("- 没有跑任何 gate")

    lines.extend(["", "## 待人工复核", ""])
    if checkpoints:
        lines.append("| id | 类型 | stage | 要判断什么 | 写进哪里 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for item in checkpoints:
            ledger = item.get("ledger")
            ledger_cell = f"`{ledger}`" if ledger else "—"
            lines.append(
                f"| `{item.get('id')}` | {item.get('type')} | `{item.get('stage')}` "
                f"| {item.get('question')} | {ledger_cell} |"
            )
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 环境健康",
            "",
            f"- problems: {len(env_problems)}，advisories: {len(env_advisories)}",
        ]
    )
    lines.extend(_bullet_list(env_problems, "没有阻断性环境问题"))
    lines.extend(f"- advisory `{item.code}`: {item.message}" for item in env_advisories)
    if env_statuses:
        lines.extend(["", "已安装/可达：", ""])
        lines.extend(f"- `{line}`" for line in env_statuses)

    lines.extend(
        [
            "",
            "## Git 与 CI",
            "",
            f"- present: `{git.get('present')}`",
            f"- dirty: `{git.get('dirty')}`",
            f"- commit: `{git.get('commit')}`",
            f"- remotes: `{', '.join(git.get('remotes') or []) or 'none'}`",
            f"- GitHub Actions workflows: `{git.get('workflows_present')}`",
            "",
            "## Scientific Boundary",
            "",
            "- 这份快照汇总确定性 gate 与环境状态，不证明结论正确。",
            f"- scientific acceptance: `{report.get('scientific_acceptance', {}).get('status')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="一条命令给出论文当前状态：gate 结论、人工待办、环境健康、git/CI 与倒计时"
    )
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--paper-root", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--today", default=None, help="注入今天日期 YYYY-MM-DD")
    parser.add_argument(
        "--out",
        default=None,
        help="写入该 Markdown 路径；缺省只打印到 stdout，不写任何文件",
    )
    parser.add_argument("--skip-services", action="store_true")
    parser.add_argument("--skip-verifiers", action="store_true")
    parser.add_argument(
        "--codex-config",
        default=None,
        help="Codex config.toml 路径，用于发现 provider 服务",
    )
    args = parser.parse_args(argv[1:])
    try:
        repo_root = (
            Path(args.repo_root)
            if args.repo_root
            else Path(__file__).resolve().parents[2]
        )
        paper_root = (
            Path(args.paper_root)
            if args.paper_root
            else discover_paper(repo_root)
        )
        today = date.fromisoformat(args.today) if args.today else date.today()
        report = readiness_module.build_report(
            paper_root,
            profile=args.profile,
            today=today,
        )
        env_problems, env_advisories, env_statuses = collect_environment(
            repo_root,
            skip_services=args.skip_services,
            skip_verifiers=args.skip_verifiers,
            codex_config=args.codex_config,
        )
        text = render_snapshot(
            report,
            env_problems,
            env_advisories,
            env_statuses,
            today=today,
        )
        if args.out:
            out = Path(args.out)
            save_text_atomically(out, text, description="端到端快照")
            print(f"snapshot written: {out}", file=sys.stderr)
        else:
            print(text, end="")
        print(
            f"e2e-check summary: ready={str(bool(report['ready'])).lower()}, "
            f"{len(report['blocking'])} blocking, "
            f"{len(env_problems)} environment problems",
            file=sys.stderr,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    # A snapshot is a report, not a gate: the exit code says "the report was
    # produced", and the content says whether the paper is ready.
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
