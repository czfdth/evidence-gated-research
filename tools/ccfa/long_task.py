"""Resume long-running tasks across sessions from an append-only event log.

The task state is derived, never trusted: ``resume`` replays the hash-chained
events and recomputes the current step and next action. A new process only
needs the paper root and task id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa import compute, run_log
from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.ledger import is_nonempty_str, load_ledger, missing_fields, problem

TASK_ROOT = Path("ccfa-workfiles") / "tasks"
SPEC_NAME = "spec.yaml"
EVENTS_NAME = "events.jsonl"
VALID_STEP_STATUSES = {"pending", "in-progress", "complete", "failed", "blocked", "skipped"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_payload(payload: dict) -> str:
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _task_dir(paper_root: Path, task_id: str) -> Path:
    return paper_root / TASK_ROOT / task_id


def _load_spec(path: Path) -> tuple[dict | None, list[Problem]]:
    payload, problems = load_ledger(path, code="long-task-spec-invalid")
    if payload is None:
        return None, problems
    missing = missing_fields(payload, ("version", "id", "title", "steps"))
    if missing:
        return None, [
            problem(
                "long-task-spec-invalid",
                path,
                None,
                f"缺少字段: {', '.join(missing)}",
            )
        ]
    if payload.get("version") != 1:
        return None, [
            problem("long-task-spec-invalid", path, None, "version 必须是 1")
        ]
    if not is_nonempty_str(payload.get("id")) or not is_nonempty_str(payload.get("title")):
        return None, [
            problem("long-task-spec-invalid", path, None, "id/title 必须是非空字符串")
        ]
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        return None, [
            problem("long-task-spec-invalid", path, None, "steps 必须是非空数组")
        ]
    ids: set[str] = set()
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            return None, [
                problem("long-task-spec-invalid", path, None, f"steps[{index}] 必须是映射")
            ]
        step_id = step.get("id")
        if not is_nonempty_str(step_id):
            return None, [
                problem("long-task-spec-invalid", path, None, f"steps[{index}].id 非法")
            ]
        if step_id in ids:
            return None, [
                problem("long-task-spec-duplicate", path, None, f"step id 重复: {step_id}")
            ]
        ids.add(step_id)
        if not is_nonempty_str(step.get("description")):
            return None, [
                problem(
                    "long-task-spec-invalid",
                    path,
                    None,
                    f"{step_id}: description 必须是非空字符串",
                )
            ]
        command = step.get("command")
        if command is not None and (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            return None, [
                problem(
                    "long-task-spec-invalid",
                    path,
                    None,
                    f"{step_id}: command 必须是非空字符串数组",
                )
            ]
        budget = step.get("budget_minutes", 10)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget <= 0:
            return None, [
                problem(
                    "long-task-spec-invalid",
                    path,
                    None,
                    f"{step_id}: budget_minutes 必须是正数",
                )
            ]
    return payload, []


def _read_events(task_dir: Path) -> tuple[list[dict], list[Problem]]:
    path = task_dir / EVENTS_NAME
    if not path.is_file():
        return [], [problem("long-task-events-missing", path, None, "事件流不存在")]
    events = []
    problems = []
    previous = ""
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(
                problem("long-task-event-invalid", path, line_number, f"JSON 非法: {exc}")
            )
            continue
        if not isinstance(event, dict):
            problems.append(
                problem("long-task-event-invalid", path, line_number, "event 必须是对象")
            )
            continue
        if event.get("prev_sha256", "") != previous:
            problems.append(
                problem(
                    "long-task-chain-broken",
                    path,
                    line_number,
                    "prev_sha256 与前一条事件不符",
                )
            )
        expected = _sha256_payload({**event, "event_sha256": ""})
        if event.get("event_sha256") != expected:
            problems.append(
                problem(
                    "long-task-event-tampered",
                    path,
                    line_number,
                    "event_sha256 与事件内容不符",
                )
            )
        previous = event.get("event_sha256", "")
        events.append(event)
    return events, problems


def _append_event(task_dir: Path, payload: dict) -> dict:
    events_path = task_dir / EVENTS_NAME
    if events_path.is_file():
        events, problems = _read_events(task_dir)
        if problems:
            first = problems[0]
            raise ValueError(f"事件流不可写: {first.code}: {first.message}")
    else:
        events = []
    previous = events[-1]["event_sha256"] if events else ""
    event = {
        **payload,
        "timestamp": _now_iso(),
        "prev_sha256": previous,
        "event_sha256": "",
    }
    event["event_sha256"] = _sha256_payload(event)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def start_task(paper_root: Path, spec_path: Path, *, force: bool = False) -> dict:
    paper_root = Path(paper_root).resolve()
    spec_path = Path(spec_path)
    if not spec_path.is_absolute():
        spec_path = paper_root / spec_path
    spec, problems = _load_spec(spec_path)
    if spec is None:
        raise ValueError(problems[0].message if problems else "task spec 不存在")
    task_dir = _task_dir(paper_root, spec["id"])
    if task_dir.exists() and not force:
        raise ValueError(f"task 已存在，拒绝覆盖: {task_dir}")
    if force and task_dir.exists():
        for path in sorted(task_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
    task_dir.mkdir(parents=True, exist_ok=True)
    save_text_atomically(
        task_dir / SPEC_NAME,
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
        description="long task spec",
    )
    _append_event(
        task_dir,
        {
            "event": "start",
            "task_id": spec["id"],
            "title": spec["title"],
            "spec_sha256": _sha256_payload(spec),
        },
    )
    return resume_task(paper_root, spec["id"])


def checkpoint_task(
    paper_root: Path,
    task_id: str,
    *,
    step_id: str,
    status: str,
    evidence: list[str],
    next_action: str = "",
    note: str = "",
) -> dict:
    paper_root = Path(paper_root).resolve()
    task_dir = _task_dir(paper_root, task_id)
    spec, problems = _load_spec(task_dir / SPEC_NAME)
    if spec is None:
        raise ValueError(problems[0].message if problems else "task spec 不存在")
    if status not in VALID_STEP_STATUSES:
        raise ValueError(f"status 非法: {status!r}")
    if step_id not in {step["id"] for step in spec["steps"]}:
        raise ValueError(f"step_id 不存在: {step_id!r}")
    if status in {"complete", "failed", "blocked"} and not evidence:
        raise ValueError(f"{status} checkpoint 必须提供至少一个 evidence")
    _append_event(
        task_dir,
        {
            "event": "checkpoint",
            "task_id": task_id,
            "step_id": step_id,
            "status": status,
            "evidence": evidence,
            "next_action": next_action,
            "note": note,
        },
    )
    return resume_task(paper_root, task_id)


def replay_task(paper_root: Path, task_id: str) -> dict:
    paper_root = Path(paper_root).resolve()
    task_dir = _task_dir(paper_root, task_id)
    spec, problems = _load_spec(task_dir / SPEC_NAME)
    if spec is None:
        raise ValueError(problems[0].message if problems else "task spec 不存在")
    events, event_problems = _read_events(task_dir)
    if event_problems:
        first = event_problems[0]
        raise ValueError(f"事件流损坏: {first.code}: {first.message}")
    statuses = {step["id"]: "pending" for step in spec["steps"]}
    history: dict[str, list[dict]] = {step["id"]: [] for step in spec["steps"]}
    latest_next_action = ""
    for event in events:
        if event.get("event") != "checkpoint":
            continue
        step_id = event.get("step_id")
        if step_id not in statuses:
            continue
        statuses[step_id] = event.get("status", "pending")
        history[step_id].append(
            {
                "status": event.get("status"),
                "timestamp": event.get("timestamp"),
                "evidence": event.get("evidence", []),
                "note": event.get("note", ""),
            }
        )
        if is_nonempty_str(event.get("next_action")):
            latest_next_action = event["next_action"]
    steps = [
        {
            "id": step["id"],
            "description": step["description"],
            "status": statuses[step["id"]],
            "history": history[step["id"]],
            "command": step.get("command"),
            "budget_minutes": step.get("budget_minutes", 10),
            "gpus": step.get("gpus", 0),
        }
        for step in spec["steps"]
    ]
    current = next(
        (
            step
            for step in steps
            if step["status"] not in {"complete", "skipped"}
        ),
        None,
    )
    if current is None:
        next_action = "任务已完成；可运行归档/评审流程"
    else:
        next_action = (
            latest_next_action
            if latest_next_action and current["id"] in latest_next_action
            else f"{current['id']}: {current['description']}"
        )
    return {
        "task_id": task_id,
        "title": spec["title"],
        "status": "complete" if current is None else "active",
        "current_step": current,
        "next_action": next_action,
        "steps": steps,
        "event_count": len(events),
        "task_dir": str(task_dir),
    }


def resume_task(paper_root: Path, task_id: str) -> dict:
    return replay_task(paper_root, task_id)


def check_task(paper_root: Path, task_id: str) -> list[Problem]:
    paper_root = Path(paper_root).resolve()
    task_dir = _task_dir(paper_root, task_id)
    spec, problems = _load_spec(task_dir / SPEC_NAME)
    if spec is None:
        return problems
    events, problems = _read_events(task_dir)
    if problems:
        return problems
    if not events or events[0].get("event") != "start":
        problems.append(
            problem("long-task-no-start", task_dir / EVENTS_NAME, None, "事件流缺少 start")
        )
    if events and events[0].get("spec_sha256") != _sha256_payload(spec):
        problems.append(
            problem("long-task-spec-drift", task_dir / SPEC_NAME, None, "spec 已变化")
        )
    known = {step["id"] for step in spec["steps"]}
    for index, event in enumerate(events, start=1):
        if event.get("event") == "checkpoint" and event.get("step_id") not in known:
            problems.append(
                problem(
                    "long-task-unknown-step",
                    task_dir / EVENTS_NAME,
                    index,
                    f"checkpoint 引用了未知 step: {event.get('step_id')!r}",
                )
            )
    return problems


def run_next_task(
    paper_root: Path,
    task_id: str,
    *,
    execute: bool = False,
) -> dict:
    paper_root = Path(paper_root).resolve()
    state = resume_task(paper_root, task_id)
    current = state.get("current_step")
    if current is None:
        return {"status": "complete", "next_action": state["next_action"]}
    command = current.get("command")
    if not command:
        return {
            "status": "manual",
            "step_id": current["id"],
            "next_action": state["next_action"],
        }
    if not execute:
        return {
            "status": "dry-run",
            "step_id": current["id"],
            "command": command,
            "next_action": state["next_action"],
        }

    def budget_runner(argv: list[str], _cwd: Path) -> tuple[int, str]:
        attempt = compute.run_local(
            argv,
            budget_minutes=float(current.get("budget_minutes", 10)),
            gpus_used=int(current.get("gpus", 0)),
            cwd=paper_root,
        )
        compute.append_attempt(paper_root, attempt)
        return attempt.returncode, ""

    run_id, record = run_log.run_command(
        command,
        paper_root / "experiments" / "log",
        paper_root,
        notes=f"long-task {task_id} {current['id']}",
        purpose="experiment",
        runner=budget_runner,
    )
    status = "complete" if record.get("status") == "completed" else "failed"
    checkpoint_task(
        paper_root,
        task_id,
        step_id=current["id"],
        status=status,
        evidence=[run_id],
        next_action="运行 long-task resume 获取下一步",
        note=f"run-log status={record.get('status')} exit={record.get('exit_code')}",
    )
    return {
        "status": status,
        "step_id": current["id"],
        "run_id": run_id,
        "exit_code": record.get("exit_code"),
        "next_action": resume_task(paper_root, task_id)["next_action"],
    }


def list_tasks(paper_root: Path) -> list[dict]:
    root = Path(paper_root).resolve() / TASK_ROOT
    if not root.is_dir():
        return []
    return [
        replay_task(Path(paper_root), path.name)
        for path in sorted(root.iterdir())
        if path.is_dir() and (path / SPEC_NAME).is_file()
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="跨会话长任务续跑")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--paper-root", default=".")
    start.add_argument("--spec", required=True)
    start.add_argument("--force", action="store_true")
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("--paper-root", default=".")
    checkpoint.add_argument("--task", required=True)
    checkpoint.add_argument("--step", required=True)
    checkpoint.add_argument("--status", required=True, choices=sorted(VALID_STEP_STATUSES))
    checkpoint.add_argument("--evidence", action="append", default=[])
    checkpoint.add_argument("--next-action", default="")
    checkpoint.add_argument("--note", default="")
    resume = sub.add_parser("resume")
    resume.add_argument("--paper-root", default=".")
    resume.add_argument("--task", required=True)
    check = sub.add_parser("check")
    check.add_argument("--paper-root", default=".")
    check.add_argument("--task", required=True)
    run_next = sub.add_parser("run-next")
    run_next.add_argument("--paper-root", default=".")
    run_next.add_argument("--task", required=True)
    run_next.add_argument("--execute", action="store_true")
    sub.add_parser("list").add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "start":
            print(json.dumps(start_task(Path(args.paper_root), Path(args.spec), force=args.force), ensure_ascii=False, indent=2))
            return 0
        if args.command == "checkpoint":
            print(json.dumps(checkpoint_task(Path(args.paper_root), args.task, step_id=args.step, status=args.status, evidence=args.evidence, next_action=args.next_action, note=args.note), ensure_ascii=False, indent=2))
            return 0
        if args.command == "resume":
            print(json.dumps(resume_task(Path(args.paper_root), args.task), ensure_ascii=False, indent=2))
            return 0
        if args.command == "run-next":
            print(json.dumps(run_next_task(Path(args.paper_root), args.task, execute=args.execute), ensure_ascii=False, indent=2))
            return 0
        if args.command == "list":
            print(json.dumps(list_tasks(Path(args.paper_root)), ensure_ascii=False, indent=2))
            return 0
        return emit(check_task(Path(args.paper_root), args.task), [])
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
