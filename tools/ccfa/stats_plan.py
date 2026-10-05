"""Validate the pre-specified statistical analysis plan (`stats_plan`).

This is a completeness gate. It cannot decide whether the chosen test is
appropriate; it requires the author to state the endpoint, test, alpha,
effect size, target power, sample size, seeds, stopping rule, missing-data
handling, and multiple-comparison correction before the design is frozen.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from ccfa.cli import emit, tool_error
from ccfa.ledger import (
    is_nonempty_str,
    load_ledger,
    missing_fields,
    problem,
)

LEDGER_RELATIVE_PATH = Path("data") / "statistics-plan.yaml"
TOP_FIELDS = ("alpha", "multiple_comparison", "claims")
CLAIM_FIELDS = (
    "id",
    "endpoint",
    "test",
    "effect_size",
    "target_power",
    "sample_size",
    "seeds",
    "stopping_rule",
    "missing_data",
)
NO_CORRECTION = {"", "none", "no", "无", "未校正"}
NOT_APPLICABLE = {"n/a", "na", "not-applicable", "not_applicable", "不适用"}
DESCRIPTIVE = {"descriptive", "descriptive-sok", "description"}
INFERENTIAL = {"inferential", "inference"}
ANALYSIS_TYPES = DESCRIPTIVE | INFERENTIAL


def _not_applicable(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.strip().casefold() in NOT_APPLICABLE
    )


def _analysis_type(value: object, default: str = "inferential") -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        return "invalid"
    return value.strip().casefold()


def _check_claim(
    path: Path,
    index: int,
    claim: object,
    default_analysis_type: str = "inferential",
) -> list:
    problems = []
    if not isinstance(claim, dict):
        return [
            problem(
                "statistics-invalid",
                path,
                None,
                f"claims[{index}] 必须是映射",
            )
        ]
    missing = missing_fields(claim, CLAIM_FIELDS)
    if missing:
        return [
            problem(
                "statistics-invalid",
                path,
                None,
                f"claims[{index}] 缺少字段: {', '.join(missing)}",
            )
        ]
    claim_id = claim.get("id")
    if not is_nonempty_str(claim_id):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                f"claims[{index}].id 必须是非空字符串",
            )
        )
        claim_id = f"claims[{index}]"
    for field in ("endpoint", "test", "stopping_rule", "missing_data"):
        if not is_nonempty_str(claim.get(field)):
            problems.append(
                problem(
                    "statistics-invalid",
                    path,
                    None,
                    f"{claim_id}: {field} 必须是非空字符串",
                )
            )
    analysis_type = _analysis_type(
        claim.get("analysis_type"),
        default_analysis_type,
    )
    if analysis_type not in ANALYSIS_TYPES:
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                f"{claim_id}: analysis_type 必须是 descriptive 或 inferential",
            )
        )
    descriptive = analysis_type in DESCRIPTIVE
    effect_size = claim.get("effect_size")
    try:
        effect_size_ok = (
            not isinstance(effect_size, bool)
            and isinstance(effect_size, (int, float))
            and math.isfinite(effect_size)
            and effect_size > 0
        )
    except OverflowError:
        effect_size_ok = False
    if not effect_size_ok and not (descriptive and _not_applicable(effect_size)):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                f"{claim_id}: effect_size 必须是正数，"
                "或分析类型为 descriptive 时写 not-applicable",
            )
        )
    target_power = claim.get("target_power")
    target_power_ok = (
        not isinstance(target_power, bool)
        and isinstance(target_power, (int, float))
        and 0 < target_power < 1
    )
    if not target_power_ok and not (
        descriptive and _not_applicable(target_power)
    ):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                f"{claim_id}: target_power 必须在 (0, 1) 内，"
                "或分析类型为 descriptive 时写 not-applicable",
            )
        )
    sample_size = claim.get("sample_size")
    sample_size_ok = type(sample_size) is int and sample_size > 0
    if not sample_size_ok and not (
        descriptive and _not_applicable(sample_size)
    ):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                f"{claim_id}: sample_size 必须是正整数，"
                "或分析类型为 descriptive 时写 not-applicable",
            )
        )
    seeds = claim.get("seeds")
    seeds_ok = (
        isinstance(seeds, list)
        and bool(seeds)
        and all(
            type(seed) is int or is_nonempty_str(seed) for seed in seeds
        )
    )
    if not seeds_ok and not (descriptive and _not_applicable(seeds)):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                f"{claim_id}: seeds 必须是非空数组（整数或字符串），"
                "或分析类型为 descriptive 时写 not-applicable",
            )
        )
    return problems


def check(paper_root: Path, ledger: Path | None = None) -> tuple[list, list]:
    paper_root = Path(paper_root)
    path = Path(ledger) if ledger else paper_root / LEDGER_RELATIVE_PATH
    payload, problems = load_ledger(
        path,
        code="statistics-ledger-missing",
    )
    if payload is None:
        return problems, []
    missing = missing_fields(payload, TOP_FIELDS)
    if missing:
        return [
            problem(
                "statistics-invalid",
                path,
                None,
                f"统计计划缺少字段: {', '.join(missing)}",
            )
        ], []
    analysis_type = _analysis_type(payload.get("analysis_type"))
    if analysis_type not in ANALYSIS_TYPES:
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                "analysis_type 必须是 descriptive 或 inferential",
            )
        )
    descriptive = analysis_type in DESCRIPTIVE
    alpha = payload.get("alpha")
    if (
        isinstance(alpha, bool)
        or not isinstance(alpha, (int, float))
        or not 0 < alpha < 1
    ) and not (descriptive and _not_applicable(alpha)):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                "alpha 必须在 (0, 1) 内，"
                "或 analysis_type: descriptive 时写 not-applicable",
            )
        )
    correction = payload.get("multiple_comparison")
    if not is_nonempty_str(correction):
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                "multiple_comparison 必须是非空字符串",
            )
        )
    claims = payload.get("claims")
    if not isinstance(claims, list) or not claims:
        problems.append(
            problem(
                "statistics-invalid",
                path,
                None,
                "claims 必须是非空数组",
            )
        )
        return problems, []
    if (
        len(claims) > 1
        and is_nonempty_str(correction)
        and correction.strip().casefold() in NO_CORRECTION
    ):
        problems.append(
            problem(
                "statistics-missing-correction",
                path,
                None,
                "存在多个 claim 时，multiple_comparison 不能是 none/无",
            )
        )
    ids: set[str] = set()
    for index, claim in enumerate(claims):
        problems.extend(
            _check_claim(
                path,
                index,
                claim,
                default_analysis_type=analysis_type,
            )
        )
        if isinstance(claim, dict) and is_nonempty_str(claim.get("id")):
            claim_id = claim["id"].strip()
            if claim_id in ids:
                problems.append(
                    problem(
                        "statistics-duplicate-claim",
                        path,
                        None,
                        f"claim id 重复: {claim_id}",
                    )
                )
            ids.add(claim_id)
    return problems, []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="检查预注册统计设计：功效、样本量、多重比较与停止规则"
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--ledger")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.paper_root),
            Path(args.ledger) if args.ledger else None,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
