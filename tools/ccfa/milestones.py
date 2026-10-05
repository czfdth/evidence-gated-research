"""Check deadline-relative milestone checkpoints and gate gaps."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from ccfa.cli import Problem, tool_error
from ccfa.stages import gate_for, stages_for

_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CHECKPOINT_STAGES = {
    "T-90": "experiment-design",
    "T-60": "experiments-running",
    "T-30": "results-ready",
    "T-21": "writing",
    "T-14": "internal-review",
    "T-7": "internal-review",
    "T-3": "submission-check",
    "T-1": "submission-check",
}
_SEQUENTIAL_ADVISORY = "无投稿目标日，按顺序推进"
_RUN_STARTED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_MIN_EXEMPTION_REASON = 20


def parse_deadline(value: object) -> date | None:
    """Parse an optional YYYY-MM-DD deadline."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"deadline 必须是 YYYY-MM-DD 日期字符串: {value!r}"
        )
    text = value.strip()
    if not text:
        return None
    if _DATE_PATTERN.fullmatch(text) is None:
        raise ValueError(f"deadline 非法: {value!r}，应为 YYYY-MM-DD")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"deadline 不是合法日期: {value!r}") from exc


def checkpoints(deadline: date) -> dict[str, date]:
    """Return all eight checkpoint dates relative to the deadline."""
    return {
        "T-90": deadline - timedelta(days=90),
        "T-60": deadline - timedelta(days=60),
        "T-30": deadline - timedelta(days=30),
        "T-21": deadline - timedelta(days=21),
        "T-14": deadline - timedelta(days=14),
        "T-7": deadline - timedelta(days=7),
        "T-3": deadline - timedelta(days=3),
        "T-1": deadline - timedelta(days=1),
    }


def _load_state(paper_root: Path) -> dict:
    path = Path(paper_root) / "ccfa.yaml"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    try:
        state = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML 解析失败于 {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return state


def _problem(
    code: str,
    path: Path,
    message: str,
) -> dict:
    return dict(Problem(code, str(path), None, message)._asdict())


def _parse_run_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _RUN_STARTED_FORMAT).date()
    except ValueError:
        return None


def _exemption_reason(value: object) -> str:
    """Return the whitespace-normalised reason, or '' when unusable."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


def _scan_t30_runs(
    paper_root: Path,
    t30: date,
) -> tuple[list[dict], list[dict]]:
    """Find experiment runs started after T-30.

    Records that *declare* ``build`` (new ``declared_purpose`` or legacy
    ``purpose``) describe figure rendering or compilation, so they do not
    trigger the T-30 freeze -- but only when they also record a reason. A bare
    one-word declaration buys an exemption with nothing to review, so it is a
    problem instead; a justified exemption is still only an advisory, because
    the declaration itself is not evidence.
    """
    log_dir = paper_root / "experiments" / "log"
    problems: list[dict] = []
    advisories: list[dict] = []
    if not log_dir.is_dir():
        return problems, advisories

    for path in sorted(log_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            advisories.append(
                _problem(
                    "t30-scan-skipped",
                    path,
                    f"运行记录不可读，已跳过: {exc}",
                )
            )
            continue
        if not isinstance(record, dict):
            advisories.append(
                _problem(
                    "t30-scan-skipped",
                    path,
                    "运行记录不是对象，已跳过",
                )
            )
            continue

        started = _parse_run_date(record.get("started_at"))
        if started is None:
            advisories.append(
                _problem(
                    "t30-scan-skipped",
                    path,
                    "运行记录缺少可解析的 started_at，已跳过: "
                    f"{record.get('started_at')!r}",
                )
            )
            continue

        run_id = record.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            advisories.append(
                _problem(
                    "t30-scan-skipped",
                    path,
                    "运行记录缺少 run_id，已跳过",
                )
            )
            continue

        if started > t30:
            declared = record.get("declared_purpose")
            if declared is None:
                declared = record.get("purpose")
            if declared == "build":
                reason = _exemption_reason(record.get("purpose_reason"))
                if len(reason) < _MIN_EXEMPTION_REASON:
                    problems.append(
                        _problem(
                            "t30-unjustified-build-run",
                            path,
                            f"T-30 ({t30.isoformat()}) 后声明的 build 运行 "
                            f"{run_id}（开始于 {started.isoformat()}）没有写 "
                            f"purpose_reason（至少 {_MIN_EXEMPTION_REASON} 字符）；"
                            "缺理由的豁免等同于新实验",
                        )
                    )
                else:
                    advisories.append(
                        _problem(
                            "t30-declared-build-run",
                            path,
                            f"T-30 ({t30.isoformat()}) 后出现声明为 build 的运行 "
                            f"{run_id}，开始于 {started.isoformat()}，"
                            f"理由：{reason}；已按调用者声明豁免，该声明不构成证据",
                        )
                    )
            else:
                problems.append(
                    _problem(
                        "t30-new-experiment",
                        path,
                        f"T-30 ({t30.isoformat()}) 后出现新实验记录 "
                        f"{run_id}，开始于 {started.isoformat()}",
                    )
                )
    return problems, advisories


def _gate_problems(
    mode: str,
    current: str,
    target: str,
    path: Path,
) -> list[dict]:
    stages = stages_for(mode)
    current_index = stages.index(current)
    target_index = stages.index(target)
    if current_index > target_index:
        return []
    problems: list[dict] = []
    for stage in stages[current_index : target_index + 1]:
        gate = gate_for(mode, stage)
        problems.append(
            _problem(
                "milestone-gate-missing",
                path,
                f"stage {stage} gate {gate.id} 未完成: {gate.criterion}",
            )
        )
    return problems


def _due_item(checkpoint: str, checkpoint_date: date | None, mode: str, stage: str) -> dict:
    gate = gate_for(mode, stage)
    return {
        "checkpoint": checkpoint,
        "date": checkpoint_date.isoformat() if checkpoint_date else None,
        "stage": stage,
        "gate": gate.id,
        "criterion": gate.criterion,
    }


def due_report(paper_root: Path, today: date) -> dict:
    """Return a read-only milestone report for one injected date."""
    paper_root = Path(paper_root)
    state_path = paper_root / "ccfa.yaml"
    state = _load_state(paper_root)
    venue = state.get("target_venue")
    if not isinstance(venue, dict):
        raise ValueError(f"{state_path} 的 target_venue 必须是映射")

    mode = venue.get("mode", "conference")
    stages_for(mode)
    stage_data = state.get("stage")
    current = stage_data.get("current") if isinstance(stage_data, dict) else None
    stage_known = isinstance(current, str) and current in stages_for(mode)

    problems: list[dict] = []
    if not stage_known:
        problems.append(
            _problem(
                "stage-unknown",
                state_path,
                f"stage.current 不在 stages.py 中: {current!r}",
            )
        )
        current = None

    raw_deadline = venue.get("deadline")
    try:
        deadline = parse_deadline(raw_deadline)
    except ValueError as exc:
        if raw_deadline is not None and not isinstance(raw_deadline, str):
            raise
        problems.append(
            _problem("deadline-invalid", state_path, str(exc))
        )
        return {
            "mode": "countdown",
            "deadline": raw_deadline if isinstance(raw_deadline, str) else None,
            "due": [],
            "missing_gates": [],
            "problems": problems,
            "advisory": None,
            "advisories": [],
        }

    if deadline is None:
        advisory = _SEQUENTIAL_ADVISORY
        if stage_known:
            gate = gate_for(mode, current)
            advisory = (
                f"{_SEQUENTIAL_ADVISORY}；下一动作: stage {current} "
                f"gate {gate.id}: {gate.criterion}"
            )
        return {
            "mode": "sequential",
            "deadline": None,
            "due": [],
            "missing_gates": [],
            "problems": problems,
            "advisory": advisory,
        }

    due = []
    missing_gates: list[dict] = []
    checkpoint_dates = checkpoints(deadline)
    advisories: list[dict] = []

    if today > deadline:
        due.append(_due_item("overdue", deadline, mode, "submission-check"))
        problems.append(
            _problem(
                "deadline-passed",
                state_path,
                f"已超过投稿目标日 {deadline.isoformat()}",
            )
        )
        if stage_known:
            missing_gates = _gate_problems(
                mode,
                current,
                "submission-check",
                state_path,
            )
            problems.extend(missing_gates)
    else:
        checkpoint = next(
            (
                name
                for name, checkpoint_date in checkpoint_dates.items()
                if today == checkpoint_date
            ),
            None,
        )
        if checkpoint is not None:
            target_stage = _CHECKPOINT_STAGES[checkpoint]
            stages = stages_for(mode)
            target_passed = (
                stage_known
                and stages.index(current) > stages.index(target_stage)
            )
            if not target_passed:
                due.append(
                    _due_item(
                        checkpoint,
                        checkpoint_dates[checkpoint],
                        mode,
                        target_stage,
                    )
                )
            if stage_known:
                missing_gates = _gate_problems(
                    mode,
                    current,
                    target_stage,
                    state_path,
                )
                problems.extend(missing_gates)

    if today > checkpoint_dates["T-30"]:
        t30_problems, advisories = _scan_t30_runs(
            paper_root,
            checkpoint_dates["T-30"],
        )
        problems.extend(t30_problems)

    return {
        "mode": "countdown",
        "deadline": deadline.isoformat(),
        "due": due,
        "missing_gates": missing_gates,
        "problems": problems,
        "advisory": None,
        "advisories": advisories,
    }


def stage_report(paper_root: Path) -> dict:
    """Return the public stage/gate/updated_at report for one paper root."""
    paper_root = Path(paper_root)
    state_path = paper_root / "ccfa.yaml"
    state = _load_state(paper_root)
    stage = state.get("stage")
    if not isinstance(stage, dict):
        raise ValueError(f"{state_path} 的 stage 必须是映射")
    result: dict[str, str] = {}
    for field in ("current", "gate", "updated_at"):
        value = stage.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"stage.{field} 必须是非空字符串")
        result[field] = value
    try:
        date.fromisoformat(result["updated_at"])
    except ValueError as exc:
        raise ValueError(
            f"stage.updated_at 不是合法日期: {result['updated_at']!r}"
        ) from exc

    venue = state.get("target_venue")
    mode = venue.get("mode", "conference") if isinstance(venue, dict) else "conference"
    if mode not in ("conference", "journal"):
        raise ValueError(f"未知 mode: {mode!r}")
    if result["current"] not in stages_for(mode):
        raise ValueError(
            f"stage.current 不在 stages.py 中: {result['current']!r}"
        )
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="检查投稿倒排里程碑")
    subparsers = parser.add_subparsers(dest="command", required=True)
    due = subparsers.add_parser("due", help="检查到期 checkpoint 与 gate 缺口")
    due.add_argument("--paper-root", default=".")
    due.add_argument("--today", help="注入今天日期 YYYY-MM-DD（默认系统日期）")
    stage = subparsers.add_parser("stage", help="读取当前 stage/gate/updated_at")
    stage.add_argument("--paper-root", default=".")
    args = parser.parse_args(argv[1:])

    try:
        if args.command == "stage":
            print(
                json.dumps(
                    stage_report(Path(args.paper_root)),
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        today = parse_deadline(args.today) if args.today else date.today()
        if today is None:
            raise ValueError("--today 不能为空")
        report = due_report(Path(args.paper_root), today)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    for problem in report["problems"]:
        print(
            f"{problem['path']}: {problem['code']}: {problem['message']}",
            file=sys.stderr,
        )
    for advisory in report.get("advisories", []):
        print(
            f"{advisory['path']}: {advisory['code']}: {advisory['message']}",
            file=sys.stderr,
        )
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
