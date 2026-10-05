"""Deterministic guardrails for a text-only resubmission to a new venue."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error


PLAN = Path("data/resubmit-plan.yaml")
TEXT_SUFFIXES = {
    ".tex",
    ".bib",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".json",
}


def _load_plan(paper_root: Path) -> dict:
    path = paper_root / PLAN
    if not path.is_file():
        raise ValueError(f"缺少 resubmit plan: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 resubmit plan: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("resubmit plan version 必须是 1")
    return payload


def _resolve_dir(paper_root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError("resubmit dir 必须是非空字符串")
    path = (paper_root / relative).resolve()
    try:
        path.relative_to(paper_root.resolve())
    except ValueError as exc:
        raise ValueError(f"resubmit dir 逃出 paper root: {relative}") from exc
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_files(root: Path):
    if not root.is_dir():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES
    ]


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    path = paper_root / PLAN
    if not path.is_file():
        return [], [
            Problem(
                "resubmit-plan-not-configured",
                str(path),
                None,
                "尚未配置 resubmit plan",
            )
        ]
    try:
        plan = _load_plan(paper_root)
        source = plan.get("source")
        target = plan.get("target")
        if not isinstance(source, dict) or not isinstance(target, dict):
            raise ValueError("source/target 必须是映射")
        source_dir = _resolve_dir(paper_root, source.get("dir"))
        target_dir = _resolve_dir(paper_root, target.get("dir"))
    except ValueError as exc:
        return [
            Problem("resubmit-invalid", str(path), None, str(exc))
        ], []
    problems: list[Problem] = []
    if source_dir == target_dir:
        problems.append(
            Problem(
                "resubmit-source-target-conflict",
                str(path),
                None,
                "source 与 target 必须物理隔离",
            )
        )
    if not target_dir.is_dir():
        problems.append(
            Problem(
                "resubmit-target-missing",
                str(target_dir),
                None,
                "target 目录不存在",
            )
        )
    frozen = plan.get("frozen")
    frozen = frozen if isinstance(frozen, dict) else {}
    bib = source.get("bib")
    if not isinstance(bib, str) or not bib.strip():
        problems.append(
            Problem("resubmit-invalid", str(path), None, "source.bib 必须是非空路径")
        )
    else:
        target_bib = target_dir / bib
        if not target_bib.is_file():
            problems.append(
                Problem(
                    "resubmit-frozen-bib-missing",
                    str(target_bib),
                    None,
                    "target 缺少 frozen bib",
                )
            )
        elif frozen.get("bib_sha256") != _sha256(target_bib):
            problems.append(
                Problem(
                    "resubmit-frozen-bib-changed",
                    str(target_bib),
                    None,
                    "target bib 与冻结 hash 不一致",
                )
            )
    allowed = target.get("allowed_paths")
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) and item.strip() for item in allowed
    ):
        problems.append(
            Problem(
                "resubmit-invalid",
                str(path),
                None,
                "target.allowed_paths 必须是非空字符串数组",
            )
        )
    forbidden = target.get("forbidden_paths")
    if not isinstance(forbidden, list) or not all(
        isinstance(item, str) and item.strip() for item in forbidden
    ):
        problems.append(
            Problem(
                "resubmit-invalid",
                str(path),
                None,
                "target.forbidden_paths 必须是非空字符串数组",
            )
        )
    else:
        for file_path in target_dir.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(target_dir).as_posix()
            for prefix in forbidden:
                if relative.startswith(prefix):
                    source_file = source_dir / relative
                    if (
                        not source_file.is_file()
                        or _sha256(source_file) != _sha256(file_path)
                    ):
                        problems.append(
                            Problem(
                                "resubmit-forbidden-path",
                                str(file_path),
                                None,
                                f"target 修改了 forbidden path: {relative}",
                            )
                        )
    frozen_runs = frozen.get("run_ids")
    if not isinstance(frozen_runs, list) or not all(
        isinstance(item, str) for item in frozen_runs
    ):
        problems.append(
            Problem(
                "resubmit-invalid",
                str(path),
                None,
                "frozen.run_ids 必须是字符串数组",
            )
        )
    else:
        for run_file in (target_dir / "experiments" / "log").glob("*.json"):
            run_id = run_file.stem
            if run_id not in frozen_runs:
                problems.append(
                    Problem(
                        "resubmit-new-experiment",
                        str(run_file),
                        None,
                        f"target 出现新 experiment: {run_id}",
                    )
                )
    patterns = plan.get("anonymity_patterns")
    if not isinstance(patterns, list) or not all(
        isinstance(item, str) and item for item in patterns
    ):
        problems.append(
            Problem(
                "resubmit-invalid",
                str(path),
                None,
                "anonymity_patterns 必须是字符串数组",
            )
        )
    else:
        for file_path in _text_files(target_dir):
            text = file_path.read_text(encoding="utf-8", errors="replace")
            for pattern in patterns:
                if pattern.casefold() in text.casefold():
                    problems.append(
                        Problem(
                            "resubmit-anonymity-leak",
                            str(file_path),
                            None,
                            f"target 文本包含匿名禁用片段: {pattern!r}",
                        )
                    )
    return problems, []


def render_report(report: dict) -> str:
    lines = [
        "# Resubmit Report",
        "",
        "## Findings",
        "",
    ]
    problems = report.get("problems", [])
    if not problems:
        lines.append("- none")
    for item in problems:
        lines.append(
            f"- `{item.get('code')}` {item.get('path')}: {item.get('message')}"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="resubmit pipeline guardrails")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--paper-root", required=True)
    report = sub.add_parser("report")
    report.add_argument("--paper-root", required=True)
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        problems, advisories = check(Path(args.paper_root))
        if args.command == "report":
            print(
                render_report(
                    {"problems": [p._asdict() for p in problems]},
                ),
                end="",
            )
            return 0
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
