"""Validate the project-level research state aligned with AI-Research-SKILLs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import is_iso_date, is_nonempty_str, load_ledger, missing_fields, problem


RESEARCH_STATE = Path("data/research-state.yaml")
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
RUN_LOG_DIR = Path("experiments/log")

PROJECT_FIELDS = ("title", "question", "status", "started", "domain")
PROJECT_STATUSES = {"active", "paused", "concluded"}
HYPOTHESIS_FIELDS = (
    "id",
    "statement",
    "status",
    "motivation",
    "parent",
    "priority",
)
HYPOTHESIS_STATUSES = {
    "pending",
    "active",
    "supported",
    "refuted",
    "inconclusive",
}
PRIORITIES = {"high", "medium", "low"}
EXPERIMENT_FIELDS = (
    "proxy_metric",
    "baseline_value",
    "best_value",
    "total_runs",
    "trajectory",
)
TRAJECTORY_FIELDS = (
    "run_id",
    "hypothesis",
    "metric_value",
    "delta",
    "wall_time_min",
    "change_summary",
    "timestamp",
)
OUTER_FIELDS = ("cycle", "last_direction", "last_reflection")
OUTER_DIRECTIONS = {"deepen", "broaden", "pivot", "conclude", None}
WORKSPACE_FIELDS = (
    "findings",
    "log",
    "literature_dir",
    "experiments_dir",
    "to_human_dir",
    "paper_dir",
)


def _claim_ids(paper_root: Path) -> set[str]:
    path = paper_root / CLAIM_REGISTRY
    if not path.is_file():
        return set()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    claims = payload.get("claims") if isinstance(payload, dict) else None
    if not isinstance(claims, list):
        return set()
    return {
        item["id"]
        for item in claims
        if isinstance(item, dict) and is_nonempty_str(item.get("id"))
    }


def _run_ids(paper_root: Path) -> set[str]:
    log_dir = paper_root / RUN_LOG_DIR
    if not log_dir.is_dir():
        return set()
    ids: set[str] = set()
    for path in log_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and is_nonempty_str(payload.get("run_id")):
            ids.add(payload["run_id"])
    return ids


def _path_inside(paper_root: Path, value: object) -> bool:
    if not is_nonempty_str(value):
        return False
    candidate = (paper_root / str(value)).resolve()
    try:
        candidate.relative_to(paper_root.resolve())
    except ValueError:
        return False
    return candidate.exists()


def _partial_state(payload: object) -> bool:
    if not isinstance(payload, dict):
        return True
    required = {
        "project",
        "literature",
        "hypotheses",
        "experiments",
        "outer_loop",
        "workspace",
    }
    return not required.issubset(payload)


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    path = paper_root / RESEARCH_STATE
    if not path.is_file():
        return [], [
            problem(
                "research-state-not-configured",
                path,
                None,
                "尚未配置 research-state",
            )
        ]
    payload, problems = load_ledger(path, code="research-state-invalid")
    if not isinstance(payload, dict):
        return problems, []
    if _partial_state(payload):
        return problems, [
            problem(
                "research-state-empty",
                path,
                None,
                "research-state 尚未填写完整",
            )
        ]

    project = payload.get("project")
    literature = payload.get("literature")
    hypotheses = payload.get("hypotheses")
    experiments = payload.get("experiments")
    outer = payload.get("outer_loop")
    workspace = payload.get("workspace")
    if not isinstance(project, dict):
        problems.append(problem("research-state-invalid", path, None, "project 必须是映射"))
        project = {}
    else:
        missing = missing_fields(project, PROJECT_FIELDS)
        if missing:
            problems.append(problem("research-state-invalid", path, None, f"project 缺少字段: {', '.join(missing)}"))
        if project.get("status") not in PROJECT_STATUSES:
            problems.append(problem("research-state-invalid", path, None, "project.status 非法"))
        if not is_iso_date(project.get("started")):
            problems.append(problem("research-state-invalid", path, None, "project.started 必须是 YYYY-MM-DD"))
        for field in ("title", "question", "domain"):
            if not is_nonempty_str(project.get(field)):
                problems.append(problem("research-state-invalid", path, None, f"project.{field} 必须是非空字符串"))
    if not isinstance(literature, dict):
        problems.append(problem("research-state-invalid", path, None, "literature 必须是映射"))
    else:
        for field in ("key_papers", "open_problems", "evidence_gaps"):
            if not isinstance(literature.get(field), list):
                problems.append(problem("research-state-invalid", path, None, f"literature.{field} 必须是数组"))
    if not isinstance(hypotheses, list):
        problems.append(problem("research-state-invalid", path, None, "hypotheses 必须是数组"))
        hypotheses = []
    hypothesis_ids: set[str] = set()
    for index, item in enumerate(hypotheses):
        if not isinstance(item, dict):
            problems.append(problem("research-state-invalid", path, None, f"hypotheses[{index}] 必须是映射"))
            continue
        missing = missing_fields(item, HYPOTHESIS_FIELDS)
        if missing:
            problems.append(problem("research-state-invalid", path, None, f"hypotheses[{index}] 缺少字段: {', '.join(missing)}"))
            continue
        item_id = item.get("id")
        if not is_nonempty_str(item_id):
            problems.append(problem("research-state-invalid", path, None, f"hypotheses[{index}].id 必须是非空字符串"))
            continue
        if item_id in hypothesis_ids:
            problems.append(problem("research-state-duplicate", path, None, f"hypothesis id 重复: {item_id}"))
        hypothesis_ids.add(item_id)
        if item.get("status") not in HYPOTHESIS_STATUSES:
            problems.append(problem("research-state-invalid", path, None, f"{item_id}: status 非法"))
        if item.get("priority") not in PRIORITIES:
            problems.append(problem("research-state-invalid", path, None, f"{item_id}: priority 非法"))
        if not is_nonempty_str(item.get("statement")):
            problems.append(problem("research-state-invalid", path, None, f"{item_id}: statement 必须是非空字符串"))
        if not is_nonempty_str(item.get("motivation")):
            problems.append(problem("research-state-invalid", path, None, f"{item_id}: motivation 必须是非空字符串"))
        parent = item.get("parent")
        if parent is not None and parent not in hypothesis_ids and parent not in {
            other.get("id")
            for other in hypotheses
            if isinstance(other, dict)
        }:
            problems.append(problem("research-state-unknown-hypothesis", path, None, f"{item_id}: parent {parent!r} 不存在"))
    if not isinstance(experiments, dict):
        problems.append(problem("research-state-invalid", path, None, "experiments 必须是映射"))
        experiments = {}
    else:
        missing = missing_fields(experiments, EXPERIMENT_FIELDS)
        if missing:
            problems.append(problem("research-state-invalid", path, None, f"experiments 缺少字段: {', '.join(missing)}"))
        if not is_nonempty_str(experiments.get("proxy_metric")):
            problems.append(problem("research-state-invalid", path, None, "experiments.proxy_metric 必须是非空字符串"))
        total_runs = experiments.get("total_runs")
        trajectory = experiments.get("trajectory")
        if type(total_runs) is not int or total_runs < 0:
            problems.append(problem("research-state-invalid", path, None, "experiments.total_runs 必须是非负整数"))
        if not isinstance(trajectory, list):
            problems.append(problem("research-state-invalid", path, None, "experiments.trajectory 必须是数组"))
            trajectory = []
        elif type(total_runs) is int and total_runs != len(trajectory):
            problems.append(problem("research-state-run-count-mismatch", path, None, "experiments.total_runs 必须等于 trajectory 长度"))
        run_ids = _run_ids(paper_root)
        for index, item in enumerate(trajectory):
            if not isinstance(item, dict):
                problems.append(problem("research-state-invalid", path, None, f"trajectory[{index}] 必须是映射"))
                continue
            missing = missing_fields(item, TRAJECTORY_FIELDS)
            if missing:
                problems.append(problem("research-state-invalid", path, None, f"trajectory[{index}] 缺少字段: {', '.join(missing)}"))
                continue
            run_id = item.get("run_id")
            if run_id not in run_ids:
                problems.append(problem("research-state-unknown-run", path, None, f"trajectory[{index}].run_id {run_id!r} 不存在"))
            hypothesis = item.get("hypothesis")
            if hypothesis not in hypothesis_ids:
                problems.append(problem("research-state-unknown-hypothesis", path, None, f"trajectory[{index}].hypothesis {hypothesis!r} 不存在"))
            if not is_nonempty_str(item.get("change_summary")):
                problems.append(problem("research-state-invalid", path, None, f"trajectory[{index}].change_summary 必须是非空字符串"))
    if not isinstance(outer, dict):
        problems.append(problem("research-state-invalid", path, None, "outer_loop 必须是映射"))
    else:
        missing = missing_fields(outer, OUTER_FIELDS)
        if missing:
            problems.append(problem("research-state-invalid", path, None, f"outer_loop 缺少字段: {', '.join(missing)}"))
        if type(outer.get("cycle")) is not int or outer.get("cycle", -1) < 0:
            problems.append(problem("research-state-invalid", path, None, "outer_loop.cycle 必须是非负整数"))
        if outer.get("last_direction") not in OUTER_DIRECTIONS:
            problems.append(problem("research-state-invalid", path, None, "outer_loop.last_direction 非法"))
        if not is_nonempty_str(outer.get("last_reflection")):
            problems.append(problem("research-state-invalid", path, None, "outer_loop.last_reflection 必须是非空字符串"))
    if not isinstance(workspace, dict):
        problems.append(problem("research-state-invalid", path, None, "workspace 必须是映射"))
    else:
        missing = missing_fields(workspace, WORKSPACE_FIELDS)
        if missing:
            problems.append(problem("research-state-invalid", path, None, f"workspace 缺少字段: {', '.join(missing)}"))
        for field in WORKSPACE_FIELDS:
            if not _path_inside(paper_root, workspace.get(field)):
                problems.append(problem("research-state-missing-path", path, None, f"workspace.{field} 不存在: {workspace.get(field)!r}"))
    return problems, []


def next_actions(paper_root: Path) -> dict:
    paper_root = Path(paper_root).resolve()
    path = paper_root / RESEARCH_STATE
    if not path.is_file():
        raise ValueError("缺少 research-state.yaml")
    payload, problems = load_ledger(path, code="research-state-invalid")
    if not isinstance(payload, dict) or problems:
        raise ValueError("research-state 不可用")
    hypotheses = [
        item
        for item in payload.get("hypotheses", [])
        if isinstance(item, dict) and item.get("status") in {"pending", "active"}
    ]
    if hypotheses:
        selected = sorted(
            hypotheses,
            key=lambda item: (item.get("priority") != "high", str(item.get("id"))),
        )[0]
        return {
            "hypothesis": selected.get("id"),
            "action": f"运行 hypothesis {selected.get('id')} 的下一步实验并记录 trajectory",
        }
    return {"hypothesis": None, "action": "所有 hypothesis 已闭环，执行 outer-loop 综合或撰写"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验 AI-Research-SKILLs 风格的 research-state")
    parser.add_argument("action", choices=("check", "next"), nargs="?", default="check")
    parser.add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    paper_root = Path(args.paper_root)
    if args.action == "next":
        try:
            print(json.dumps(next_actions(paper_root), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            return tool_error(str(exc))
        return 0
    try:
        problems, advisories = check(paper_root)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
