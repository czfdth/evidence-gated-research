"""Validate pilot screening and the inner/outer experiment loop.

The ledger is intentionally explicit about decisions: a pilot cannot be
promoted without a budget, metric, kill criterion and run id; an inner-loop
decision cannot be recorded as keep/revert/stop while the result is pending;
and an outer-loop decision must link back to real claims and run records.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from ccfa import compute, run_log
from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import is_nonempty_str, load_ledger, missing_fields, problem


EXPERIMENT_LOOP = Path("data/experiment-loop.yaml")
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
RUN_LOG_DIR = Path("experiments/log")

IDEA_FIELDS = ("id", "statement", "status")
PILOT_FIELDS = (
    "pilot_budget_minutes",
    "pilot_metric",
    "kill_criterion",
    "run_ids",
)
IDEA_STATUSES = {
    "proposed",
    "pilot-planned",
    "pilot-running",
    "promoted",
    "rejected",
    "parked",
}
IDEA_DECISIONS = {
    "promoted": "promote",
    "rejected": "reject",
    "parked": "park",
}
INNER_FIELDS = (
    "id",
    "claim_id",
    "run_id",
    "change",
    "hypothesis",
    "metric",
    "result",
    "decision",
    "next_action",
)
INNER_RESULTS = {"pending", "improved", "no-change", "worse", "inconclusive"}
INNER_DECISIONS = {"pending", "keep", "revert", "continue", "stop"}
OUTER_FIELDS = (
    "id",
    "claim_ids",
    "evidence_run_ids",
    "decision",
    "rationale",
    "next_action",
)
OUTER_DECISIONS = {"pending", "continue", "pivot", "write", "stop"}
PILOT_COMMAND_FIELD = "pilot_command"
PLACEHOLDER = re.compile(
    r"(?<![a-z0-9])(pending|tbd|todo|placeholder|"
    r"to[ -]be[ -]determined)(?![a-z0-9])",
    re.IGNORECASE,
)


def _placeholder(value: object) -> bool:
    return (
        isinstance(value, str)
        and PLACEHOLDER.search(" ".join(value.casefold().split())) is not None
    )


def _string_list(value: object, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    return all(is_nonempty_str(item) for item in value)


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
        item["id"] for item in claims if isinstance(item, dict) and is_nonempty_str(item.get("id"))
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


def _check_ids(
    values: object,
    known: set[str],
    *,
    path: Path,
    code: str,
    label: str,
) -> list[Problem]:
    if not _string_list(values, allow_empty=True):
        return [
            problem(
                code,
                path,
                None,
                f"{label} 必须是字符串数组",
            )
        ]
    return [
        problem(code, path, None, f"{label} 引用了不存在的 id: {value!r}")
        for value in values
        if value not in known
    ]


def _validate_ideas(
    payload: dict,
    *,
    path: Path,
    run_ids: set[str],
) -> list[Problem]:
    problems: list[Problem] = []
    ideas = payload.get("ideas", [])
    if not isinstance(ideas, list):
        return [problem("experiment-loop-invalid", path, None, "ideas 必须是数组")]
    seen: set[str] = set()
    for index, idea in enumerate(ideas):
        if not isinstance(idea, dict):
            problems.append(
                problem("experiment-loop-invalid", path, None, f"ideas[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(idea, IDEA_FIELDS)
        if missing:
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"ideas[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        idea_id = idea.get("id")
        if not is_nonempty_str(idea_id):
            problems.append(
                problem(
                    "experiment-loop-invalid", path, None, f"ideas[{index}].id 必须是非空字符串"
                )
            )
            continue
        if idea_id in seen:
            problems.append(
                problem("experiment-loop-duplicate", path, None, f"重复 idea id: {idea_id}")
            )
        seen.add(idea_id)
        if not is_nonempty_str(idea.get("statement")):
            problems.append(
                problem(
                    "experiment-loop-invalid", path, None, f"{idea_id}: statement 必须是非空字符串"
                )
            )
        elif _placeholder(idea.get("statement")):
            problems.append(
                problem(
                    "experiment-loop-placeholder",
                    path,
                    None,
                    f"{idea_id}: statement 仍是 placeholder",
                )
            )
        status = idea.get("status")
        if status not in IDEA_STATUSES:
            problems.append(
                problem("experiment-loop-invalid", path, None, f"{idea_id}: status 非法")
            )
            continue
        if status == "pilot-planned":
            command = idea.get(PILOT_COMMAND_FIELD)
            if not _string_list(command):
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{idea_id}: pilot-planned 需要非空 pilot_command 字符串数组",
                    )
                )
        if status in {"pilot-planned", "pilot-running", "promoted", "rejected", "parked"}:
            missing_pilot = missing_fields(idea, PILOT_FIELDS)
            if missing_pilot:
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{idea_id}: pilot 状态缺少字段: {', '.join(missing_pilot)}",
                    )
                )
            budget = idea.get("pilot_budget_minutes")
            if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{idea_id}: pilot_budget_minutes 必须是正数",
                    )
                )
            for field in ("pilot_metric", "kill_criterion"):
                value = idea.get(field)
                if not is_nonempty_str(value):
                    problems.append(
                        problem(
                            "experiment-loop-invalid",
                            path,
                            None,
                            f"{idea_id}: {field} 必须是非空字符串",
                        )
                    )
                elif _placeholder(value):
                    problems.append(
                        problem(
                            "experiment-loop-placeholder",
                            path,
                            None,
                            f"{idea_id}: {field} 仍是 placeholder",
                        )
                    )
            problems.extend(
                _check_ids(
                    idea.get("run_ids"),
                    run_ids,
                    path=path,
                    code="experiment-loop-unknown-run",
                    label=f"{idea_id}.run_ids",
                )
            )
        if status in IDEA_DECISIONS:
            expected = IDEA_DECISIONS[status]
            if idea.get("decision") != expected:
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{idea_id}: status={status} 需要 decision={expected}",
                    )
                )
            if not is_nonempty_str(idea.get("decision_rationale")):
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{idea_id}: 终态 idea 需要 decision_rationale",
                    )
                )
            elif _placeholder(idea.get("decision_rationale")):
                problems.append(
                    problem(
                        "experiment-loop-placeholder",
                        path,
                        None,
                        f"{idea_id}: decision_rationale 仍是 placeholder",
                    )
                )
    return problems


def _validate_inner(
    payload: dict,
    *,
    path: Path,
    claim_ids: set[str],
    run_ids: set[str],
) -> list[Problem]:
    problems: list[Problem] = []
    entries = payload.get("inner_loop", [])
    if not isinstance(entries, list):
        return [problem("experiment-loop-invalid", path, None, "inner_loop 必须是数组")]
    seen: set[str] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(
                problem("experiment-loop-invalid", path, None, f"inner_loop[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(item, INNER_FIELDS)
        if missing:
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"inner_loop[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        item_id = item.get("id")
        if not is_nonempty_str(item_id):
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"inner_loop[{index}].id 必须是非空字符串",
                )
            )
            continue
        if item_id in seen:
            problems.append(
                problem("experiment-loop-duplicate", path, None, f"重复 inner_loop id: {item_id}")
            )
        seen.add(item_id)
        for field in ("change", "hypothesis", "metric", "next_action"):
            value = item.get(field)
            if not is_nonempty_str(value):
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{item_id}: {field} 必须是非空字符串",
                    )
                )
            elif _placeholder(value):
                problems.append(
                    problem(
                        "experiment-loop-placeholder",
                        path,
                        None,
                        f"{item_id}: {field} 仍是 placeholder",
                    )
                )
        claim_id = item.get("claim_id")
        if claim_id not in claim_ids:
            problems.append(
                problem(
                    "experiment-loop-unknown-claim",
                    path,
                    None,
                    f"{item_id}: claim_id {claim_id!r} 不存在",
                )
            )
        run_id = item.get("run_id")
        if run_id not in run_ids:
            problems.append(
                problem(
                    "experiment-loop-unknown-run",
                    path,
                    None,
                    f"{item_id}: run_id {run_id!r} 不存在",
                )
            )
        result = item.get("result")
        decision = item.get("decision")
        if result not in INNER_RESULTS:
            problems.append(
                problem("experiment-loop-invalid", path, None, f"{item_id}: result 非法")
            )
        if decision not in INNER_DECISIONS:
            problems.append(
                problem("experiment-loop-invalid", path, None, f"{item_id}: decision 非法")
            )
        if result == "pending" and decision != "pending":
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"{item_id}: result=pending 时 decision 必须是 pending",
                )
            )
        if result != "pending" and decision == "pending":
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"{item_id}: 已有 result 时必须记录 decision",
                )
            )
    return problems


def _validate_outer(
    payload: dict,
    *,
    path: Path,
    claim_ids: set[str],
    run_ids: set[str],
) -> list[Problem]:
    problems: list[Problem] = []
    entries = payload.get("outer_loop", [])
    if not isinstance(entries, list):
        return [problem("experiment-loop-invalid", path, None, "outer_loop 必须是数组")]
    seen: set[str] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(
                problem("experiment-loop-invalid", path, None, f"outer_loop[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(item, OUTER_FIELDS)
        if missing:
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"outer_loop[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        item_id = item.get("id")
        if not is_nonempty_str(item_id):
            problems.append(
                problem(
                    "experiment-loop-invalid",
                    path,
                    None,
                    f"outer_loop[{index}].id 必须是非空字符串",
                )
            )
            continue
        if item_id in seen:
            problems.append(
                problem("experiment-loop-duplicate", path, None, f"重复 outer_loop id: {item_id}")
            )
        seen.add(item_id)
        problems.extend(
            _check_ids(
                item.get("claim_ids"),
                claim_ids,
                path=path,
                code="experiment-loop-unknown-claim",
                label=f"{item_id}.claim_ids",
            )
        )
        problems.extend(
            _check_ids(
                item.get("evidence_run_ids"),
                run_ids,
                path=path,
                code="experiment-loop-unknown-run",
                label=f"{item_id}.evidence_run_ids",
            )
        )
        decision = item.get("decision")
        if decision not in OUTER_DECISIONS:
            problems.append(
                problem("experiment-loop-invalid", path, None, f"{item_id}: decision 非法")
            )
        for field in ("rationale", "next_action"):
            value = item.get(field)
            if not is_nonempty_str(value):
                problems.append(
                    problem(
                        "experiment-loop-invalid",
                        path,
                        None,
                        f"{item_id}: {field} 必须是非空字符串",
                    )
                )
            elif _placeholder(value):
                problems.append(
                    problem(
                        "experiment-loop-placeholder",
                        path,
                        None,
                        f"{item_id}: {field} 仍是 placeholder",
                    )
                )
    return problems


def _load_payload(paper_root: Path) -> tuple[dict | None, list[Problem], list[Problem]]:
    path = paper_root / EXPERIMENT_LOOP
    if not path.is_file():
        return (
            None,
            [],
            [
                problem(
                    "experiment-loop-not-configured",
                    path,
                    None,
                    "尚未配置 experiment-loop 台账",
                )
            ],
        )
    payload, problems = load_ledger(
        path,
        code="experiment-loop-invalid",
    )
    return payload if isinstance(payload, dict) else None, problems, []


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_payload(paper_root)
    if payload is None:
        return problems, advisories

    not_applicable = payload.get("not_applicable", False)
    if not isinstance(not_applicable, bool):
        return [
            problem(
                "experiment-loop-invalid",
                paper_root / EXPERIMENT_LOOP,
                None,
                "not_applicable 必须是布尔值",
            )
        ], advisories
    if not_applicable:
        reason = payload.get("not_applicable_reason")
        if not is_nonempty_str(reason):
            problems.append(
                problem(
                    "experiment-loop-na-reason-missing",
                    paper_root / EXPERIMENT_LOOP,
                    None,
                    "not_applicable=true 需要非空 not_applicable_reason",
                )
            )
        return problems, advisories

    claim_ids = _claim_ids(paper_root)
    run_ids = _run_ids(paper_root)
    path = paper_root / EXPERIMENT_LOOP
    problems.extend(_validate_ideas(payload, path=path, run_ids=run_ids))
    problems.extend(
        _validate_inner(
            payload,
            path=path,
            claim_ids=claim_ids,
            run_ids=run_ids,
        )
    )
    problems.extend(
        _validate_outer(
            payload,
            path=path,
            claim_ids=claim_ids,
            run_ids=run_ids,
        )
    )
    ideas = payload.get("ideas")
    inner = payload.get("inner_loop")
    outer = payload.get("outer_loop")
    if not any(isinstance(value, list) and value for value in (ideas, inner, outer)):
        advisories.append(
            problem(
                "experiment-loop-empty",
                path,
                None,
                "台账已创建但尚未填写",
            )
        )
    return problems, advisories


def _budgeted_command(idea: dict) -> str | None:
    """Return the executor invocation that enforces a pilot's declared budget.

    The ledger already declares ``pilot_budget_minutes``. Without a command that
    references it the budget is documentation rather than a constraint;
    ``compute.py`` is the executor that enforces the wall clock and records
    ``gpu_minutes`` into the compute ledger.
    """
    budget = idea.get("pilot_budget_minutes")
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
        return None
    gpus = idea.get("pilot_gpus")
    gpu_flag = ""
    if isinstance(gpus, int) and not isinstance(gpus, bool) and gpus > 0:
        gpu_flag = f" --gpus {gpus}"
    pilot_command = _pilot_command(idea)
    rendered = " ".join(pilot_command) if pilot_command else "<命令>"
    return (
        "scripts/compute.ps1 run --paper-root <paper-root> "
        f"--minutes {budget:g}{gpu_flag} -- {rendered}"
    )


def _pilot_command(idea: dict) -> list[str] | None:
    command = idea.get(PILOT_COMMAND_FIELD)
    return list(command) if _string_list(command) else None


def next_actions(paper_root: Path) -> dict:
    """Return deterministic next actions for active pilots and loops."""
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_payload(paper_root)
    if payload is None:
        detail = problems[0].message if problems else advisories[0].message
        raise ValueError(detail)
    checked, _checked_advisories = check(paper_root)
    if checked:
        first = checked[0]
        raise ValueError(f"experiment-loop 台账存在问题: {first.code}: {first.message}")
    if payload.get("not_applicable") is True:
        return {
            "pilot": [],
            "inner": [],
            "outer": [],
            "reason": payload.get("not_applicable_reason", ""),
        }

    pilot = []
    for idea in payload.get("ideas", []):
        if not isinstance(idea, dict):
            continue
        if idea.get("status") == "pilot-planned":
            pilot.append(
                {
                    "id": idea.get("id"),
                    "action": "运行 pilot；完成后记录 run_ids 与 decision",
                    "suggested_command": _budgeted_command(idea),
                    "command": _pilot_command(idea),
                }
            )
        elif idea.get("status") == "pilot-running":
            pilot.append(
                {
                    "id": idea.get("id"),
                    "action": "记录 pilot 结果、run_ids 与 promote/reject/park 决策",
                    "suggested_command": None,
                }
            )

    inner = []
    for item in payload.get("inner_loop", []):
        if not isinstance(item, dict):
            continue
        if item.get("result") == "pending" or item.get("decision") == "pending":
            inner.append(
                {
                    "id": item.get("id"),
                    "action": item.get("next_action") or "记录内层循环决策",
                }
            )

    outer = []
    for item in payload.get("outer_loop", []):
        if not isinstance(item, dict):
            continue
        if item.get("decision") in {"pending", "continue", "pivot"}:
            outer.append(
                {
                    "id": item.get("id"),
                    "action": item.get("next_action") or "记录外层综合决策",
                }
            )
    return {"pilot": pilot, "inner": inner, "outer": outer}


def run_next(paper_root: Path, *, execute: bool = False) -> dict:
    """Run the first planned pilot through the budgeted local executor.

    The executor records both a run-log entry and a compute-ledger entry. It
    deliberately does not update ``run_ids`` or promote an idea: those are
    scientific decisions that still require the recorded result and a human
    decision.
    """
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_payload(paper_root)
    if payload is None:
        detail = problems[0].message if problems else advisories[0].message
        raise ValueError(detail)
    checked, _checked_advisories = check(paper_root)
    if checked:
        first = checked[0]
        raise ValueError(
            f"experiment-loop 台账存在问题: {first.code}: {first.message}"
        )
    if payload.get("not_applicable") is True:
        raise ValueError(
            "experiment-loop 标记为 not_applicable，没有可运行的 pilot"
        )

    idea = next(
        (
            item
            for item in payload.get("ideas", [])
            if isinstance(item, dict) and item.get("status") == "pilot-planned"
        ),
        None,
    )
    if idea is None:
        raise ValueError("没有 status=pilot-planned 的 idea")
    command = _pilot_command(idea)
    if command is None:
        raise ValueError(f"{idea.get('id')}: pilot_command 缺失或非法")
    budget = idea.get("pilot_budget_minutes")
    if (
        isinstance(budget, bool)
        or not isinstance(budget, (int, float))
        or budget <= 0
    ):
        raise ValueError(f"{idea.get('id')}: pilot_budget_minutes 必须是正数")
    gpus = idea.get("pilot_gpus", 0)
    if isinstance(gpus, bool) or not isinstance(gpus, int) or gpus < 0:
        raise ValueError(f"{idea.get('id')}: pilot_gpus 必须是非负整数")

    result = {
        "status": "dry-run" if not execute else "executed",
        "idea_id": idea.get("id"),
        "command": command,
        "budget_minutes": budget,
        "gpus": gpus,
    }
    if not execute:
        result["note"] = (
            "加 --execute 才会真正运行；结果仍需写回 run_ids 与 decision"
        )
        return result

    last_attempt = {"value": None}

    def budget_runner(argv: list[str], cwd: Path) -> tuple[int, str]:
        attempt = compute.run_local(
            argv,
            budget_minutes=float(budget),
            gpus_used=gpus,
            cwd=cwd,
        )
        compute.append_attempt(cwd, attempt)
        last_attempt["value"] = attempt
        return attempt.returncode, ""

    run_id, record = run_log.run_command(
        command,
        paper_root / "experiments" / "log",
        paper_root,
        config=Path("data/experiment-loop.yaml"),
        notes=f"experiment-loop pilot {idea.get('id')}",
        purpose="experiment",
        policy={
            "pilot_id": idea.get("id"),
            "pilot_budget_minutes": budget,
            "pilot_gpus": gpus,
            "executor": "ccfa.compute.run_local",
        },
        runner=budget_runner,
    )
    attempt = last_attempt["value"]
    result.update(
        {
            "run_id": run_id,
            "run_status": record.get("status"),
            "exit_code": record.get("exit_code"),
            "timed_out": bool(getattr(attempt, "timed_out", False)),
            "compute_ledger": str(paper_root / compute.COMPUTE_LEDGER),
            "note": "运行已留档；请根据结果填写 run_ids、result 与 decision",
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验 pilot 筛选与内层/外层实验循环台账")
    parser.add_argument(
        "action",
        choices=("check", "next", "run-next"),
        nargs="?",
        default="check",
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run-next 默认只预演；加此参数才在预算内执行 pilot",
    )
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
    if args.action == "run-next":
        try:
            result = run_next(paper_root, execute=args.execute)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (OSError, ValueError) as exc:
            return tool_error(str(exc))
        return 1 if result.get("exit_code") not in (None, 0) else 0
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
