"""Budgeted inner-loop optimization over a declared parameter search space.

This is deliberately an optimizer, not an acquittal mechanism. It may run
trials, read metrics and propose keep/revert decisions, but it never writes
``data/claim-registry.yaml`` and never changes a claim to ``supported``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ccfa import compute, run_log
from ccfa.cli import Problem, emit, save_text_atomically, tool_error
from ccfa.ledger import is_nonempty_str, load_ledger, missing_fields, problem

SPEC_PATH = Path("data") / "experiment-optimization.yaml"
PROPOSALS_PATH = Path("data") / "experiment-optimization-proposals.yaml"
OPTIMIZATION_DIR = Path("experiments") / "optimization"
CLAIM_REGISTRY = Path("data") / "claim-registry.yaml"
DIRECTIONS = {"maximize", "minimize"}
STRATEGIES = {"grid", "random"}
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_spec(paper_root: Path, spec_path: Path | None = None) -> tuple[dict | None, list[Problem]]:
    path = spec_path or (paper_root / SPEC_PATH)
    if not path.is_absolute():
        path = paper_root / path
    payload, problems = load_ledger(path, code="experiment-optimization-invalid")
    return payload if isinstance(payload, dict) else None, problems


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


def check_spec(paper_root: Path, spec_path: Path | None = None) -> list[Problem]:
    paper_root = Path(paper_root).resolve()
    payload, problems = _load_spec(paper_root, spec_path)
    if payload is None:
        return problems
    path = spec_path or (paper_root / SPEC_PATH)

    required = ("version", "objective", "budget", "command", "search_space")
    missing = missing_fields(payload, required)
    if missing:
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                f"缺少字段: {', '.join(missing)}",
            )
        )
        return problems
    if payload.get("version") != 1:
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "version 必须是 1",
            )
        )
    claim_id = payload.get("claim_id")
    if claim_id is not None:
        known = _claim_ids(paper_root)
        if not is_nonempty_str(claim_id) or claim_id not in known:
            problems.append(
                problem(
                    "experiment-optimization-unknown-claim",
                    path,
                    None,
                    f"claim_id 不存在: {claim_id!r}",
                )
            )

    objective = payload.get("objective")
    if not isinstance(objective, dict):
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "objective 必须是映射",
            )
        )
    else:
        if not is_nonempty_str(objective.get("name")):
            problems.append(
                problem(
                    "experiment-optimization-invalid",
                    path,
                    None,
                    "objective.name 必须是非空字符串",
                )
            )
        if objective.get("direction") not in DIRECTIONS:
            problems.append(
                problem(
                    "experiment-optimization-invalid",
                    path,
                    None,
                    "objective.direction 必须是 maximize 或 minimize",
                )
            )
        for field in ("baseline", "min_delta"):
            value = objective.get(field, 0 if field == "min_delta" else None)
            if field == "baseline" and value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                problems.append(
                    problem(
                        "experiment-optimization-invalid",
                        path,
                        None,
                        f"objective.{field} 必须是数字",
                    )
                )

    budget = payload.get("budget")
    if not isinstance(budget, dict):
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "budget 必须是映射",
            )
        )
    else:
        for field in ("max_trials", "minutes_per_trial"):
            value = budget.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                problems.append(
                    problem(
                        "experiment-optimization-invalid",
                        path,
                        None,
                        f"budget.{field} 必须是正数",
                    )
                )
        gpus = budget.get("gpus_per_trial", 0)
        if isinstance(gpus, bool) or not isinstance(gpus, int) or gpus < 0:
            problems.append(
                problem(
                    "experiment-optimization-invalid",
                    path,
                    None,
                    "budget.gpus_per_trial 必须是非负整数",
                )
            )
        for field in ("max_total_minutes", "max_total_gpu_minutes"):
            if field not in budget:
                continue
            value = budget[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                problems.append(
                    problem(
                        "experiment-optimization-invalid",
                        path,
                        None,
                        f"budget.{field} 必须是正数",
                    )
                )

    command = payload.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "command 必须是非空字符串数组",
            )
        )
    elif not any("{metrics_path}" in part for part in command):
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "command 必须包含 {metrics_path}",
            )
        )

    search = payload.get("search_space")
    if not isinstance(search, dict) or not search:
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "search_space 必须是非空映射",
            )
        )
    else:
        for name, values in search.items():
            if not isinstance(name, str) or not name:
                problems.append(
                    problem(
                        "experiment-optimization-invalid",
                        path,
                        None,
                        "search_space 的键必须是非空字符串",
                    )
                )
                continue
            choices = values if isinstance(values, list) else [values]
            if not choices:
                problems.append(
                    problem(
                        "experiment-optimization-invalid",
                        path,
                        None,
                        f"search_space.{name} 不能为空",
                    )
                )

    strategy = payload.get("strategy", "grid")
    if strategy not in STRATEGIES:
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "strategy 必须是 grid 或 random",
            )
        )
    patience = payload.get("patience", 0)
    if isinstance(patience, bool) or not isinstance(patience, int) or patience < 0:
        problems.append(
            problem(
                "experiment-optimization-invalid",
                path,
                None,
                "patience 必须是非负整数",
            )
        )
    return problems


def _trial_sets(spec: dict) -> list[dict[str, object]]:
    search = spec["search_space"]
    names = sorted(search)
    choices = [
        search[name] if isinstance(search[name], list) else [search[name]]
        for name in names
    ]
    combinations = [
        dict(zip(names, values))
        for values in itertools.product(*choices)
    ]
    strategy = spec.get("strategy", "grid")
    if strategy == "random":
        rng = random.Random(spec.get("seed", 0))
        rng.shuffle(combinations)
    max_trials = int(spec["budget"]["max_trials"])
    return combinations[:max_trials]


def _render_command(spec: dict, params: dict, metrics_path: Path) -> list[str]:
    replacements = {
        **{name: str(value) for name, value in params.items()},
        "python": sys.executable,
        "metrics_path": str(metrics_path),
    }
    rendered = []
    for part in spec["command"]:
        text = part
        for name, value in replacements.items():
            text = text.replace("{" + name + "}", value)
        unknown = PLACEHOLDER.search(text)
        if unknown:
            raise ValueError(f"command 中存在未知占位符: {unknown.group(0)}")
        rendered.append(text)
    return rendered


def _metric_value(metrics: dict, name: str) -> float | None:
    current = metrics
    for part in name.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return None
    return float(current)


def _improved(value: float, baseline: float | None, direction: str, min_delta: float) -> bool:
    if baseline is None:
        return True
    if direction == "maximize":
        return value > baseline + min_delta
    return value < baseline - min_delta


def _proposal(
    spec: dict,
    best: dict | None,
    *,
    stop_reason: str,
) -> dict:
    if best is None:
        decision = "revert"
        result = "inconclusive"
        rationale = f"没有 trial 产生可用 objective；stop_reason={stop_reason}"
    else:
        decision = "keep" if best["improved"] else "revert"
        result = "improved" if best["improved"] else "no-change"
        rationale = (
            f"best trial {best['trial_id']} objective={best['value']} "
            f"{spec['objective']['direction']} baseline={spec['objective'].get('baseline')}; "
            f"stop_reason={stop_reason}"
        )
    return {
        "version": 1,
        "status": "proposed",
        "claim_id": spec.get("claim_id"),
        "optimization_id": spec["_optimization_id"],
        "best_trial": best,
        "stop_reason": stop_reason,
        "proposed_inner_loop": {
            "id": f"OPT-{spec['_optimization_id']}",
            "claim_id": spec.get("claim_id"),
            "run_id": best["run_id"] if best else None,
            "change": "parameter optimization",
            "hypothesis": spec.get("hypothesis", "The declared search space contains a better configuration."),
            "metric": spec["objective"]["name"],
            "result": result,
            "decision": decision,
            "next_action": "人工复核 proposal，然后把接受项写入 experiment-loop.yaml",
        },
        "rationale": rationale,
        "human_review": "pending",
        "generated_at": _now_iso(),
    }


def run_optimization(
    paper_root: Path,
    *,
    spec_path: Path | None = None,
    execute: bool = False,
    runner=None,
) -> dict:
    paper_root = Path(paper_root).resolve()
    spec_file = Path(spec_path) if spec_path is not None else (paper_root / SPEC_PATH)
    if not spec_file.is_absolute():
        spec_file = paper_root / spec_file
    # Normalize before any relative_to(): Windows can name the same directory
    # twice (8.3 short path, or different case), and paper_root is already
    # resolved, so an unnormalized spec_file would look like it is outside the
    # paper even though it is the file we just read.
    spec_file = spec_file.resolve()
    spec, problems = _load_spec(paper_root, spec_file)
    if spec is None:
        raise ValueError(problems[0].message if problems else "optimization spec 不存在")
    checked = check_spec(paper_root, spec_file)
    if checked:
        raise ValueError(f"optimization spec 有问题: {checked[0].code}: {checked[0].message}")

    optimization_id = str(spec.get("id") or f"OPT-{_now_iso().replace(':', '').replace('-', '')}")
    spec["_optimization_id"] = optimization_id
    out_dir = paper_root / OPTIMIZATION_DIR / optimization_id
    if out_dir.exists() and execute:
        raise ValueError(f"optimization 目录已存在，拒绝覆盖: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    trials_path = out_dir / "trials.jsonl"
    trials_path.write_text("", encoding="utf-8")

    plan = _trial_sets(spec)
    if not execute:
        preview = [
            {
                "trial_id": f"T{index:03d}",
                "params": params,
                "command": _render_command(
                    spec,
                    params,
                    out_dir / f"T{index:03d}" / "metrics.json",
                ),
            }
            for index, params in enumerate(plan, start=1)
        ]
        return {
            "status": "dry-run",
            "optimization_id": optimization_id,
            "trials": preview,
            "count": len(preview),
        }

    objective = spec["objective"]
    budget = spec["budget"]
    baseline = objective.get("baseline")
    min_delta = float(objective.get("min_delta", 0.0))
    patience = int(spec.get("patience", 0))
    best: dict | None = None
    no_improvement = 0
    total_minutes = 0.0
    total_gpu_minutes = 0.0
    stop_reason = "max-trials"

    for index, params in enumerate(plan, start=1):
        trial_id = f"T{index:03d}"
        trial_dir = out_dir / trial_id
        trial_dir.mkdir(parents=True, exist_ok=True)
        metrics_path = trial_dir / "metrics.json"
        command = _render_command(spec, params, metrics_path)

        def budget_runner(argv: list[str], _cwd: Path) -> tuple[int, str]:
            attempt = compute.run_local(
                argv,
                budget_minutes=float(budget["minutes_per_trial"]),
                gpus_used=int(budget.get("gpus_per_trial", 0)),
                cwd=paper_root,
            )
            compute.append_attempt(paper_root, attempt)
            return attempt.returncode, ""

        run_id, record = run_log.run_command(
            command,
            paper_root / "experiments" / "log",
            paper_root,
            config=spec_file.relative_to(paper_root),
            notes=f"optimization {optimization_id} {trial_id}",
            purpose="experiment",
            policy={
                "optimization_id": optimization_id,
                "trial_id": trial_id,
                "executor": "ccfa.compute.run_local",
            },
            runner=runner or budget_runner,
        )
        exit_code = int(record.get("exit_code", 1))
        value = None
        metrics = None
        if exit_code == 0 and metrics_path.is_file():
            try:
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                metrics = None
            if isinstance(metrics, dict):
                value = _metric_value(metrics, objective["name"])
                run_log.log_metrics(
                    paper_root / "experiments" / "log",
                    run_id,
                    metrics,
                )
        trial = {
            "trial_id": trial_id,
            "params": params,
            "command": command,
            "run_id": run_id,
            "exit_code": exit_code,
            "objective": value,
            "metrics": metrics,
            "status": (
                "completed"
                if exit_code == 0 and value is not None
                else "failed"
                if exit_code != 0
                else "missing-objective"
            ),
            "recorded_at": _now_iso(),
        }
        with trials_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trial, ensure_ascii=False) + "\n")

        if value is not None:
            improved = _improved(value, baseline, objective["direction"], min_delta)
            if best is None or (
                improved
                and (
                    (objective["direction"] == "maximize" and value > best["value"])
                    or (objective["direction"] == "minimize" and value < best["value"])
                )
            ):
                best = {
                    "trial_id": trial_id,
                    "run_id": run_id,
                    "params": params,
                    "value": value,
                    "improved": improved,
                }
                no_improvement = 0
            else:
                no_improvement += 1
        else:
            no_improvement += 1

        total_minutes += float(budget["minutes_per_trial"])
        total_gpu_minutes += float(budget["minutes_per_trial"]) * int(
            budget.get("gpus_per_trial", 0)
        )
        if patience and no_improvement >= patience:
            stop_reason = "patience"
            break
        if "max_total_minutes" in budget and total_minutes >= float(budget["max_total_minutes"]):
            stop_reason = "max-total-minutes"
            break
        if "max_total_gpu_minutes" in budget and total_gpu_minutes >= float(
            budget["max_total_gpu_minutes"]
        ):
            stop_reason = "max-total-gpu-minutes"
            break

    proposal = _proposal(spec, best, stop_reason=stop_reason)
    save_text_atomically(
        out_dir / "summary.json",
        json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        description="optimization summary",
    )
    proposals_path = paper_root / PROPOSALS_PATH
    existing = {}
    if proposals_path.is_file():
        loaded = yaml.safe_load(proposals_path.read_text(encoding="utf-8"))
        existing = loaded if isinstance(loaded, dict) else {}
    proposals = existing.get("proposals")
    if not isinstance(proposals, list):
        proposals = []
    proposals.append(proposal)
    save_text_atomically(
        proposals_path,
        yaml.safe_dump(
            {"version": 1, "proposals": proposals},
            sort_keys=False,
            allow_unicode=True,
        ),
        description="optimization proposals",
    )
    return {
        "status": "executed",
        "optimization_id": optimization_id,
        "best": best,
        "stop_reason": stop_reason,
        "summary": str(out_dir / "summary.json"),
        "proposals": str(proposals_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="内层实验参数优化：预算内多 trial、objective 回流、patience 早停，只写 proposal"
    )
    parser.add_argument("action", choices=("check", "run"), nargs="?", default="check")
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--spec", default=str(SPEC_PATH))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="run 默认只预演；加此参数才真正消耗预算执行 trial",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    paper_root = Path(args.paper_root)
    if args.action == "check":
        try:
            return emit(check_spec(paper_root, Path(args.spec)), [])
        except (OSError, ValueError) as exc:
            return tool_error(str(exc))
    try:
        result = run_optimization(
            paper_root,
            spec_path=Path(args.spec),
            execute=args.execute,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "dry-run" or result.get("best") else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
