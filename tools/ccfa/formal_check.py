"""Run and verify machine-checkable formal checks declared by a paper."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, save_text_atomically, tool_error


LEDGER_RELATIVE_PATH = Path("data") / "formal-checks.yaml"
DEFAULT_TIMEOUT_S = 120.0
SUCCESS_STATUSES = frozenset({"proved", "unsat", "valid"})


def _problem(code: str, path: Path | str, message: str) -> Problem:
    return Problem(code, str(path), None, message)


def _render(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def _load_ledger(path: Path) -> tuple[dict | None, list[Problem]]:
    if not path.is_file():
        return None, [
            _problem(
                "formal-check-ledger-missing",
                path,
                f"缺少形式化检查台账: {path}",
            )
        ]
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                path,
                f"无法读取形式化检查台账: {exc}",
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                path,
                "formal-checks.yaml 顶层必须是映射",
            )
        ]
    if payload.get("version") != 1:
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                path,
                "formal-checks.yaml version 必须是 1",
            )
        ]
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                path,
                "formal-checks.yaml 必须包含非空 checks 列表",
            )
        ]
    return payload, []


def _string_list(value: object) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    if not all(isinstance(item, str) and item.strip() for item in value):
        return None
    return [item.strip() for item in value]


def _run_check(
    check: dict,
    paper_root: Path,
    ledger_path: Path,
    index: int,
) -> tuple[dict | None, list[Problem]]:
    label = f"checks[{index}]"
    check_id = check.get("id")
    if not isinstance(check_id, str) or not check_id.strip():
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                ledger_path,
                f"{label}: id 必须是非空字符串",
            )
        ]
    expected_status = check.get("expected_status", "proved")
    if not isinstance(expected_status, str) or not expected_status.strip():
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                ledger_path,
                f"{label}: expected_status 必须是非空字符串",
            )
        ]
    engine = check.get("engine")
    theorem_id = check.get("theorem_id")
    command = _string_list(check.get("command"))
    if not isinstance(engine, str) or not engine.strip():
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                ledger_path,
                f"{label}: engine 必须是非空字符串",
            )
        ]
    if not isinstance(theorem_id, str) or not theorem_id.strip():
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                ledger_path,
                f"{label}: theorem_id 必须是非空字符串",
            )
        ]
    if command is None:
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                ledger_path,
                f"{label}: command 必须是非空字符串数组",
            )
        ]
    timeout = check.get("timeout", DEFAULT_TIMEOUT_S)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        return None, [
            _problem(
                "formal-check-ledger-invalid",
                ledger_path,
                f"{label}: timeout 必须是正数",
            )
        ]

    argv = [sys.executable if item == "{python}" else item for item in command]
    try:
        completed = subprocess.run(
            argv,
            cwd=str(paper_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout),
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, [
            _problem(
                "formal-check-execution-failed",
                ledger_path,
                f"{check_id}: 无法执行检查: {exc}",
            )
        ]

    if completed.returncode != 0:
        return None, [
            _problem(
                "formal-check-execution-failed",
                ledger_path,
                f"{check_id}: 退出码 {completed.returncode}: {completed.stderr.strip()[:500]}",
            )
        ]
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return None, [
            _problem(
                "formal-check-output-invalid",
                ledger_path,
                f"{check_id}: stdout 不是 JSON: {exc}",
            )
        ]
    if not isinstance(payload, dict):
        return None, [
            _problem(
                "formal-check-output-invalid",
                ledger_path,
                f"{check_id}: 检查输出必须是 JSON 对象",
            )
        ]
    if payload.get("id") != check_id:
        return None, [
            _problem(
                "formal-check-output-mismatch",
                ledger_path,
                f"{check_id}: 输出 id={payload.get('id')!r} 与台账不一致",
            )
        ]
    if payload.get("engine") != engine:
        return None, [
            _problem(
                "formal-check-output-mismatch",
                ledger_path,
                f"{check_id}: 输出 engine={payload.get('engine')!r} 与台账不一致",
            )
        ]
    if payload.get("theorem_id") != theorem_id:
        return None, [
            _problem(
                "formal-check-output-mismatch",
                ledger_path,
                f"{check_id}: 输出 theorem_id={payload.get('theorem_id')!r} 与台账不一致",
            )
        ]
    status = str(payload.get("status", ""))
    if status != expected_status or status not in SUCCESS_STATUSES:
        return payload, [
            _problem(
                "formal-check-not-proved",
                ledger_path,
                f"{check_id}: status={status!r}，期望 {expected_status!r}",
            )
        ]
    return payload, []


def run_checks(paper_root: Path) -> tuple[list[Problem], list[Problem], list[dict]]:
    paper_root = Path(paper_root).resolve()
    ledger_path = paper_root / LEDGER_RELATIVE_PATH
    ledger, problems = _load_ledger(ledger_path)
    if ledger is None:
        return problems, [], []
    results: list[dict] = []
    seen: set[str] = set()
    for index, check in enumerate(ledger["checks"]):
        if not isinstance(check, dict):
            problems.append(
                _problem(
                    "formal-check-ledger-invalid",
                    ledger_path,
                    f"checks[{index}] 必须是映射",
                )
            )
            continue
        check_id = check.get("id")
        if isinstance(check_id, str):
            if check_id in seen:
                problems.append(
                    _problem(
                        "formal-check-ledger-invalid",
                        ledger_path,
                        f"重复的 check id: {check_id}",
                    )
                )
                continue
            seen.add(check_id)
        result, result_problems = _run_check(
            check,
            paper_root,
            ledger_path,
            index,
        )
        problems.extend(result_problems)
        if result is not None:
            results.append(result)
    return problems, [], results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="运行论文声明的形式化检查（Z3/其他助手）并写机器可读证据"
    )
    parser.add_argument("--paper-root", required=True)
    parser.add_argument("--out")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        problems, advisories, results = run_checks(Path(args.paper_root))
    except ValueError as exc:
        return tool_error(str(exc))
    report = {
        "problems": [dict(problem._asdict()) for problem in problems],
        "advisories": [dict(advisory._asdict()) for advisory in advisories],
        "problem_count": len(problems),
        "results": results,
    }
    if args.out:
        try:
            save_text_atomically(
                Path(args.out),
                _render(report),
                description="形式化检查报告",
            )
        except ValueError as exc:
            return tool_error(str(exc))
    print(json.dumps(report, ensure_ascii=False))
    for problem in problems:
        print(
            f"{problem.path}:{problem.code}: {problem.message}",
            file=sys.stderr,
        )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
