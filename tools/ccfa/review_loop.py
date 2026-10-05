"""Deterministic state machine for multi-round review loops."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from ccfa.cli import Problem, emit, save_text_atomically, tool_error


STATE_NAME = "review-loop-state.json"
MEMORY_NAME = "reviewer-memory.md"
ACQUITTAL_NAME = "ACQUITTAL_LOG.jsonl"
VALID_RELATIONS = {"cross-family", "same-family", "unknown"}


def _state_path(paper_root: Path) -> Path:
    return Path(paper_root) / "reviews" / STATE_NAME


def _memory_path(paper_root: Path) -> Path:
    return Path(paper_root) / "reviews" / MEMORY_NAME


def _acquittal_path(paper_root: Path) -> Path:
    return Path(paper_root) / "reviews" / ACQUITTAL_NAME


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是对象")
    return payload


def _save_state(paper_root: Path, state: dict) -> None:
    save_text_atomically(
        _state_path(paper_root),
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="review loop state",
    )


def init_loop(
    paper_root: Path,
    *,
    run_id: str,
    executor_model: str,
    reviewer_backend: str,
    reviewer_model: str,
    family_relation: str,
    max_rounds: int = 4,
) -> dict:
    paper_root = Path(paper_root).resolve()
    if not run_id.strip():
        raise ValueError("run_id 不能为空")
    if family_relation not in VALID_RELATIONS:
        raise ValueError("family_relation 必须是 cross-family/same-family/unknown")
    if type(max_rounds) is not int or max_rounds < 1:
        raise ValueError("max_rounds 必须是正整数")
    path = _state_path(paper_root)
    if path.exists():
        raise ValueError(f"review loop state 已存在: {path}")
    state = {
        "version": 1,
        "run_id": run_id.strip(),
        "round": 0,
        "max_rounds": max_rounds,
        "status": "in_progress",
        "executor_model": executor_model,
        "reviewer_backend": reviewer_backend,
        "reviewer_model": reviewer_model,
        "family_relation": family_relation,
        "requires_external_acquittal": family_relation != "cross-family",
        "last_verdict": None,
        "last_cross_review": None,
        "last_cross_review_sha256": None,
    }
    _save_state(paper_root, state)
    save_text_atomically(
        _memory_path(paper_root),
        "# Reviewer Memory\n\n",
        description="reviewer memory",
    )
    return state


def _relative_review(paper_root: Path, path: Path) -> str:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = paper_root / resolved
    resolved = resolved.resolve()
    try:
        return resolved.relative_to(paper_root.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"cross-review 必须位于 paper root 内: {resolved}") from exc


def record_round(paper_root: Path, *, cross_review: Path) -> dict:
    paper_root = Path(paper_root).resolve()
    state_path = _state_path(paper_root)
    state = _load_json(state_path)
    if state.get("status") == "completed":
        raise ValueError("review loop 已完成")
    relative = _relative_review(paper_root, cross_review)
    review_path = paper_root / relative
    review = _load_json(review_path)
    if review.get("status") != "complete":
        raise ValueError("cross-review 记录不是 complete")
    model_verdict = review.get("verdict")
    if model_verdict not in {"pass", "blocking"}:
        raise ValueError("cross-review verdict 非法")
    family = review.get("family_judgement") or state.get("family_relation")
    requires_external = family != "cross-family"
    effective_verdict = "blocking" if requires_external and model_verdict == "pass" else model_verdict
    round_number = int(state.get("round", 0)) + 1
    if effective_verdict == "pass" and not requires_external:
        status = "completed"
    elif requires_external:
        status = "blocked"
    elif round_number >= int(state.get("max_rounds", 4)):
        status = "blocked"
    else:
        status = "in_progress"
    state.update(
        {
            "round": round_number,
            "status": status,
            "family_relation": family,
            "requires_external_acquittal": requires_external,
            "last_verdict": effective_verdict,
            "last_cross_review": relative,
            "last_cross_review_sha256": _sha256_file(review_path),
        }
    )
    _save_state(paper_root, state)
    with _memory_path(paper_root).open("a", encoding="utf-8", newline="\n") as handle:
        blocking = review.get("blocking", [])
        titles = ", ".join(
            str(item.get("title", ""))
            for item in blocking
            if isinstance(item, dict)
        )
        handle.write(
            f"- round {round_number}: verdict={effective_verdict}"
            f"; family={family}; blocking=[{titles}]\n"
        )
    if status == "completed":
        line = {
            "run_id": state["run_id"],
            "round": round_number,
            "reviewer_backend": state["reviewer_backend"],
            "reviewer_model": state["reviewer_model"],
            "executor_model": state["executor_model"],
            "family_relation": family,
            "verdict": effective_verdict,
            "cross_review_sha256": state["last_cross_review_sha256"],
        }
        with _acquittal_path(paper_root).open(
            "a",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    return state


def drive_loop(
    paper_root: Path,
    *,
    fix_runner,
    review_runner,
) -> dict:
    """Run fix/review rounds until pass, external blocker, or max rounds."""
    paper_root = Path(paper_root).resolve()
    state = _load_json(_state_path(paper_root))
    if state.get("status") == "completed":
        return state
    while True:
        if state.get("requires_external_acquittal"):
            state["status"] = "blocked"
            _save_state(paper_root, state)
            return state
        if int(state.get("round", 0)) >= int(state.get("max_rounds", 4)):
            state["status"] = "blocked"
            _save_state(paper_root, state)
            return state
        fix_runner(paper_root)
        review_path = review_runner(paper_root, state)
        state = record_round(paper_root, cross_review=Path(review_path))
        if state.get("status") == "completed":
            return state


def check_loop(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    state_path = _state_path(paper_root)
    if not state_path.is_file():
        return [
            Problem("review-loop-missing", str(state_path), None, "缺少 review loop state")
        ], []
    problems: list[Problem] = []
    try:
        state = _load_json(state_path)
    except ValueError as exc:
        return [
            Problem("review-loop-malformed", str(state_path), None, str(exc))
        ], []
    if state.get("version") != 1:
        problems.append(
            Problem("review-loop-invalid", str(state_path), None, "version 必须是 1")
        )
    round_number = state.get("round")
    max_rounds = state.get("max_rounds")
    if type(round_number) is not int or type(max_rounds) is not int or round_number > max_rounds:
        problems.append(
            Problem(
                "review-loop-invalid",
                str(state_path),
                None,
                "round/max_rounds 非法",
            )
        )
    if state.get("status") not in {"in_progress", "completed", "blocked"}:
        problems.append(
            Problem("review-loop-invalid", str(state_path), None, "status 非法")
        )
    review_relative = state.get("last_cross_review")
    review_sha = state.get("last_cross_review_sha256")
    if review_relative:
        review_path = paper_root / str(review_relative)
        if not review_path.is_file():
            problems.append(
                Problem(
                    "review-loop-review-missing",
                    str(review_path),
                    None,
                    "记录里的 cross-review 不存在",
                )
            )
        elif review_sha != _sha256_file(review_path):
            problems.append(
                Problem(
                    "review-loop-review-stale",
                    str(review_path),
                    None,
                    "cross-review 在写入 state 后发生变化",
                )
            )
    if state.get("status") == "completed":
        if state.get("requires_external_acquittal"):
            problems.append(
                Problem(
                    "review-loop-self-acquittal",
                    str(state_path),
                    None,
                    "同族或未知族评审不能 completed",
                )
            )
        if not _acquittal_path(paper_root).is_file():
            problems.append(
                Problem(
                    "review-loop-acquittal-missing",
                    str(_acquittal_path(paper_root)),
                    None,
                    "completed 缺少 append-only acquittal log",
                )
            )
    if not _memory_path(paper_root).is_file():
        problems.append(
            Problem(
                "review-loop-memory-missing",
                str(_memory_path(paper_root)),
                None,
                "缺少 reviewer memory",
            )
        )
    acquittal = _acquittal_path(paper_root)
    if acquittal.is_file():
        for line_number, raw in enumerate(
            acquittal.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                problems.append(
                    Problem(
                        "review-loop-acquittal-malformed",
                        str(acquittal),
                        line_number,
                        f"JSON 非法: {exc}",
                    )
                )
                continue
            if not isinstance(payload, dict):
                problems.append(
                    Problem(
                        "review-loop-acquittal-malformed",
                        str(acquittal),
                        line_number,
                        "acquittal entry 必须是对象",
                    )
                )
    return problems, []


def next_action(paper_root: Path) -> dict:
    paper_root = Path(paper_root).resolve()
    state = _load_json(_state_path(paper_root))
    if state.get("status") == "completed":
        return {"action": "stop", "reason": "review loop completed"}
    if state.get("requires_external_acquittal"):
        return {
            "action": "configure-cross-family-review",
            "reason": "同族或未知族不能开释",
        }
    if int(state.get("round", 0)) >= int(state.get("max_rounds", 4)):
        return {"action": "blocked-max-rounds", "reason": "达到最大轮数"}
    if state.get("last_verdict") == "blocking":
        return {"action": "fix-blockers", "reason": "上一轮仍有 blocking"}
    return {"action": "run-review", "reason": "尚未完成一轮评审"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARIS 风格多轮 review loop state")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--paper-root", required=True)
    init.add_argument("--run-id", required=True)
    init.add_argument("--executor-model", required=True)
    init.add_argument("--reviewer-backend", required=True)
    init.add_argument("--reviewer-model", required=True)
    init.add_argument("--family-relation", choices=sorted(VALID_RELATIONS), required=True)
    init.add_argument("--max-rounds", type=int, default=4)
    record = sub.add_parser("record-round")
    record.add_argument("--paper-root", required=True)
    record.add_argument("--cross-review", required=True)
    for name in ("check", "next"):
        item = sub.add_parser(name)
        item.add_argument("--paper-root", required=True)
    drive = sub.add_parser("drive")
    drive.add_argument("--paper-root", required=True)
    drive.add_argument("--fix-command")
    drive.add_argument("--review-command")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "init":
            result = init_loop(
                Path(args.paper_root),
                run_id=args.run_id,
                executor_model=args.executor_model,
                reviewer_backend=args.reviewer_backend,
                reviewer_model=args.reviewer_model,
                family_relation=args.family_relation,
                max_rounds=args.max_rounds,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "record-round":
            result = record_round(
                Path(args.paper_root),
                cross_review=Path(args.cross_review),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "next":
            print(json.dumps(next_action(Path(args.paper_root)), ensure_ascii=False))
            return 0
        if args.command == "drive":
            if not args.fix_command or not args.review_command:
                raise ValueError("drive 需要 --fix-command 与 --review-command")
            fix_argv = json.loads(args.fix_command)
            review_argv = json.loads(args.review_command)
            if (
                not isinstance(fix_argv, list)
                or not fix_argv
                or not all(isinstance(item, str) for item in fix_argv)
            ):
                raise ValueError("--fix-command 必须是 JSON 字符串数组")
            if (
                not isinstance(review_argv, list)
                or not review_argv
                or not all(isinstance(item, str) for item in review_argv)
            ):
                raise ValueError("--review-command 必须是 JSON 字符串数组")
            paper_root = Path(args.paper_root).resolve()
            review_path = paper_root / "reviews" / "cross-review.json"

            def fix_runner(root: Path) -> None:
                completed = subprocess.run(
                    fix_argv,
                    cwd=str(root),
                    shell=False,
                    check=False,
                )
                if completed.returncode != 0:
                    raise ValueError(f"fix command 失败: {completed.returncode}")

            def review_runner(root: Path, state: dict) -> Path:
                env = os.environ.copy()
                env["CCFA_PAPER_ROOT"] = str(root)
                env["CCFA_CROSS_REVIEW_PATH"] = str(review_path)
                env["CCFA_REVIEW_ROUND"] = str(state.get("round", 0) + 1)
                completed = subprocess.run(
                    review_argv,
                    cwd=str(root),
                    env=env,
                    shell=False,
                    check=False,
                )
                if completed.returncode != 0:
                    raise ValueError(f"review command 失败: {completed.returncode}")
                if not review_path.is_file():
                    raise ValueError(f"review command 未生成 {review_path}")
                return review_path

            result = drive_loop(
                paper_root,
                fix_runner=fix_runner,
                review_runner=review_runner,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        problems, advisories = check_loop(Path(args.paper_root))
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
