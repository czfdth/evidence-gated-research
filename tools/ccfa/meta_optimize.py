"""Aggregate workflow friction and gate failures into improvement proposals.

This tool is deliberately read-only. It groups repeated friction records and
readiness gate problems, then emits candidate changes for a human to approve.
It never edits skills, gates, or workflow code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ccfa.cli import tool_error
from ccfa.friction_log import check_store, load_store, write_text_output


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


def _parse_input(raw: str) -> tuple[Path, str]:
    path_text, separator, label = raw.partition("=")
    if not separator or not path_text or not label:
        raise ValueError(f"输入必须写成 PATH=LABEL: {raw!r}")
    return Path(path_text), label


def _proposal_for_friction(category: str, component: str) -> str:
    if category == "tool-bug":
        return f"为 {component} 添加判别性回归测试，修复重复工具缺陷后重跑该测试"
    if category == "skill-gap":
        return f"更新 {component} 的 skill/README/CLI 说明，并增加触发条件示例"
    if category == "environment":
        return f"把 {component} 加入 doctor 或启动文档，明确缺失时的降级与恢复步骤"
    return f"人工审查 {component} 的重复摩擦，决定是否新增 gate 或调整责任边界"


def _load_readiness(
    path: Path,
    label: str,
) -> list[tuple[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 readiness 报告 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"readiness 报告顶层必须是对象: {path}")
    results = payload.get("gate_results")
    if not isinstance(results, list):
        raise ValueError(f"readiness 报告缺少 gate_results: {path}")
    problems: list[tuple[str, str]] = []
    for gate in results:
        if not isinstance(gate, dict):
            continue
        gate_name = gate.get("name")
        if not isinstance(gate_name, str) or not gate_name.strip():
            continue
        for problem in gate.get("problems", []):
            if not isinstance(problem, dict):
                continue
            code = problem.get("code")
            if isinstance(code, str) and code.strip():
                problems.append((gate_name.strip(), code.strip()))
    return problems


def analyze(
    friction_inputs: list[tuple[Path, str]],
    *,
    readiness_inputs: list[tuple[Path, str]] | None = None,
    min_count: int = 2,
) -> dict:
    if min_count < 1:
        raise ValueError("min_count 必须是正整数")
    readiness_inputs = readiness_inputs or []

    groups: dict[tuple[str, str], dict] = {}
    occurrence_count = 0
    for path, label in friction_inputs:
        path = Path(path)
        if not path.is_file():
            raise ValueError(f"摩擦 store 不存在: {path}")
        problems = check_store(path)
        if problems:
            first = problems[0]
            raise ValueError(
                f"摩擦 store 不合法 {path}: {first.code}: {first.message}"
            )
        store = load_store(path)
        for entry in store.get("entries", []):
            if not isinstance(entry, dict):
                continue
            category = entry.get("category")
            component = entry.get("component")
            severity = entry.get("severity")
            if not isinstance(category, str) or not isinstance(component, str):
                continue
            if severity not in _SEVERITY_RANK:
                continue
            occurrence_count += 1
            key = (category, component)
            group = groups.setdefault(
                key,
                {
                    "kind": "friction",
                    "key": f"{category}:{component}",
                    "category": category,
                    "component": component,
                    "count": 0,
                    "severity": "low",
                    "sources": set(),
                    "stages": set(),
                    "descriptions": [],
                },
            )
            group["count"] += 1
            if _SEVERITY_RANK[severity] > _SEVERITY_RANK[group["severity"]]:
                group["severity"] = severity
            group["sources"].add(label)
            stage = entry.get("stage")
            if isinstance(stage, str) and stage.strip():
                group["stages"].add(stage.strip())
            description = entry.get("description")
            if isinstance(description, str) and description.strip():
                group["descriptions"].append(description.strip())

    candidates: list[dict] = []
    for group in groups.values():
        if group["count"] < min_count:
            continue
        candidates.append(
            {
                **{
                    key: value
                    for key, value in group.items()
                    if key not in {"sources", "stages", "descriptions"}
                },
                "sources": sorted(group["sources"]),
                "stages": sorted(group["stages"]),
                "sample_descriptions": group["descriptions"][:5],
                "proposal": _proposal_for_friction(
                    group["category"],
                    group["component"],
                ),
                "status": "proposed",
            }
        )

    gate_groups: dict[tuple[str, str], dict] = {}
    readiness_count = 0
    for path, label in readiness_inputs:
        for gate_name, code in _load_readiness(Path(path), label):
            readiness_count += 1
            key = (gate_name, code)
            group = gate_groups.setdefault(
                key,
                {
                    "kind": "gate",
                    "key": f"{gate_name}:{code}",
                    "gate": gate_name,
                    "code": code,
                    "count": 0,
                    "severity": "high",
                    "sources": set(),
                },
            )
            group["count"] += 1
            group["sources"].add(label)
    for group in gate_groups.values():
        if group["count"] < min_count:
            continue
        candidates.append(
            {
                "kind": "gate",
                "key": group["key"],
                "gate": group["gate"],
                "code": group["code"],
                "count": group["count"],
                "severity": group["severity"],
                "sources": sorted(group["sources"]),
                "proposal": (
                    f"检查 {group['gate']} 的 gate 规则或证据输入，"
                    f"为 {group['code']} 增加回归或修复输入引导"
                ),
                "status": "proposed",
            }
        )

    candidates.sort(key=lambda item: (-item["count"], item["key"]))
    return {
        "occurrence_count": occurrence_count,
        "readiness_problem_count": readiness_count,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict) -> str:
    lines = [
        "# 工作流自优化候选",
        "",
        f"- 摩擦条目: {report.get('occurrence_count', 0)}",
        f"- readiness problem: {report.get('readiness_problem_count', 0)}",
        f"- 候选改进: {report.get('candidate_count', 0)}",
        "",
    ]
    candidates = report.get("candidates", [])
    if not candidates:
        lines.append("没有达到最小重复次数的候选改进。")
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "| kind | key | count | severity | sources | proposal |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for candidate in candidates:
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    candidate.get("kind", ""),
                    candidate.get("key", ""),
                    candidate.get("count", ""),
                    candidate.get("severity", ""),
                    ", ".join(candidate.get("sources", [])),
                    candidate.get("proposal", ""),
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把摩擦记录和 readiness gate 失败聚合成候选改进"
    )
    parser.add_argument(
        "--friction",
        action="append",
        default=[],
        metavar="PATH=LABEL",
        help="摩擦 store；可重复传入",
    )
    parser.add_argument(
        "--readiness",
        action="append",
        default=[],
        metavar="PATH=LABEL",
        help="readiness JSON 报告；可重复传入",
    )
    parser.add_argument("--min-count", type=int, default=2)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--out")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        friction_inputs = [_parse_input(raw) for raw in args.friction]
        readiness_inputs = [_parse_input(raw) for raw in args.readiness]
        if not friction_inputs and not readiness_inputs:
            raise ValueError("至少需要一个 --friction 或 --readiness 输入")
        report = analyze(
            friction_inputs,
            readiness_inputs=readiness_inputs,
            min_count=args.min_count,
        )
        text = (
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            if args.format == "json"
            else render_markdown(report)
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
