"""Compute inter-rater agreement for two human coding sheets.

This tool does not judge whether a coding manual is scientifically correct.
It makes one required human step auditable: two independent coding sheets are
joined by item id, agreement and Cohen's kappa are computed, and a bootstrap
confidence interval is reported. A missing, duplicate, or unmatched item is a
problem, not a silent exclusion.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

from ccfa.cli import tool_error

DEFAULT_MIN_KAPPA = 0.6
DEFAULT_BOOTSTRAP_ITERATIONS = 5000


def _read_sheet(
    path: Path,
    *,
    delimiter: str,
    id_column: str,
    code_column: str,
) -> tuple[dict[str, str], list[dict]]:
    path = Path(path)
    problems: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"无法读取编码表 {path}: {exc}") from exc
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    if reader.fieldnames is None:
        raise ValueError(f"编码表缺少表头: {path}")
    missing = [
        name
        for name in (id_column, code_column)
        if name not in reader.fieldnames
    ]
    if missing:
        raise ValueError(
            f"编码表 {path} 缺少列 {', '.join(missing)}；"
            f"现有列: {', '.join(reader.fieldnames)}"
        )
    rows: dict[str, str] = {}
    for index, row in enumerate(reader, start=2):
        item_id = (row.get(id_column) or "").strip()
        code = (row.get(code_column) or "").strip()
        if not item_id:
            problems.append(
                {
                    "code": "human-coding-empty-id",
                    "message": f"{path}:{index} 的 {id_column} 为空",
                }
            )
            continue
        if not code:
            problems.append(
                {
                    "code": "human-coding-empty-code",
                    "message": f"{path}:{index} 的 {code_column} 为空",
                }
            )
            continue
        if item_id in rows:
            problems.append(
                {
                    "code": "human-coding-duplicate-id",
                    "message": f"{path}:{index} 的 item id 重复: {item_id}",
                }
            )
            continue
        rows[item_id] = code
    return rows, problems


def _kappa_from_pairs(pairs: list[tuple[str, str]]) -> dict:
    n = len(pairs)
    if n == 0:
        raise ValueError("没有可比较的编码项")
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    row = Counter(a for a, _ in pairs)
    column = Counter(b for _, b in pairs)
    observed = sum(1 for a, b in pairs if a == b) / n
    expected = sum((row[label] / n) * (column[label] / n) for label in labels)
    if expected >= 1.0:
        kappa = 1.0 if observed >= 1.0 else 0.0
    else:
        kappa = (observed - expected) / (1.0 - expected)
    return {
        "n": n,
        "labels": labels,
        "observed_agreement": observed,
        "expected_agreement": expected,
        "kappa": kappa,
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("空样本没有百分位")
    index = (len(values) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[int(index)]
    return (
        values[lower] * (upper - index)
        + values[upper] * (index - lower)
    )


def _bootstrap_ci(
    pairs: list[tuple[str, str]],
    *,
    seed: int,
    iterations: int,
) -> tuple[float, float]:
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(iterations):
        sample = [pairs[rng.randrange(len(pairs))] for _ in range(len(pairs))]
        values.append(_kappa_from_pairs(sample)["kappa"])
    values.sort()
    return _percentile(values, 0.025), _percentile(values, 0.975)


def _label_report(pairs: list[tuple[str, str]], labels: list[str]) -> dict:
    report: dict[str, dict] = {}
    for label in labels:
        both = sum(1 for a, b in pairs if a == label and b == label)
        a_only = sum(1 for a, b in pairs if a == label and b != label)
        b_only = sum(1 for a, b in pairs if b == label and a != label)
        union = both + a_only + b_only
        report[label] = {
            "both": both,
            "a_only": a_only,
            "b_only": b_only,
            "a_total": both + a_only,
            "b_total": both + b_only,
            "jaccard": round(both / union, 6) if union else 1.0,
        }
    return report


def check(
    a_path: Path,
    b_path: Path,
    *,
    delimiter: str = ",",
    id_column: str = "item_id",
    code_column: str = "code",
    min_kappa: float = DEFAULT_MIN_KAPPA,
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = 0,
) -> tuple[dict, list[dict]]:
    a_rows, problems = _read_sheet(
        a_path,
        delimiter=delimiter,
        id_column=id_column,
        code_column=code_column,
    )
    b_rows, b_problems = _read_sheet(
        b_path,
        delimiter=delimiter,
        id_column=id_column,
        code_column=code_column,
    )
    problems.extend(b_problems)
    a_ids = set(a_rows)
    b_ids = set(b_rows)
    missing_in_b = sorted(a_ids - b_ids)
    missing_in_a = sorted(b_ids - a_ids)
    for item_id in missing_in_b:
        problems.append(
            {
                "code": "human-coding-missing-item",
                "message": f"B 表缺少 A 表中的 item: {item_id}",
            }
        )
    for item_id in missing_in_a:
        problems.append(
            {
                "code": "human-coding-missing-item",
                "message": f"A 表缺少 B 表中的 item: {item_id}",
            }
        )
    common = sorted(a_ids & b_ids)
    if not common:
        problems.append(
            {
                "code": "human-coding-no-common-items",
                "message": "两张编码表没有共同 item，无法计算一致性",
            }
        )
        return {
            "n": 0,
            "items": [],
            "kappa": None,
            "passed": False,
        }, problems
    pairs = [(a_rows[item_id], b_rows[item_id]) for item_id in common]
    base = _kappa_from_pairs(pairs)
    n = base["n"]
    observed = base["observed_agreement"]
    expected = base["expected_agreement"]
    ci_low, ci_high = _bootstrap_ci(
        pairs,
        seed=seed,
        iterations=bootstrap_iterations,
    )
    kappa = base["kappa"]
    report = {
        "n": n,
        "items": common,
        "kappa": round(kappa, 6),
        "observed_agreement": round(observed, 6),
        "expected_agreement": round(expected, 6),
        "ci95_bootstrap": {
            "low": round(ci_low, 6),
            "high": round(ci_high, 6),
            "iterations": bootstrap_iterations,
            "seed": seed,
        },
        "labels": _label_report(pairs, base["labels"]),
        "matrix": [
            {"a": a, "b": b, "count": count}
            for (a, b), count in sorted(Counter(pairs).items())
        ],
        "min_kappa": min_kappa,
        "passed": not problems and kappa >= min_kappa,
    }
    if kappa < min_kappa:
        problems.append(
            {
                "code": "human-coding-low-kappa",
                "message": (
                    f"Cohen's kappa={kappa:.4f} 低于阈值 {min_kappa:.4f}；"
                    "先修编码手册，不要直接进入论文写作"
                ),
            }
        )
        report["passed"] = False
    return report, problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="计算两名人类编码者的一致率、Cohen's kappa 与置信区间"
    )
    parser.add_argument("--a", required=True, help="A 编码表 CSV")
    parser.add_argument("--b", required=True, help="B 编码表 CSV")
    parser.add_argument("--delimiter", default=",")
    parser.add_argument("--id-column", default="item_id")
    parser.add_argument("--code-column", default="code")
    parser.add_argument("--min-kappa", type=float, default=DEFAULT_MIN_KAPPA)
    parser.add_argument(
        "--bootstrap-iterations",
        type=int,
        default=DEFAULT_BOOTSTRAP_ITERATIONS,
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv[1:])
    try:
        if args.bootstrap_iterations < 100:
            raise ValueError("--bootstrap-iterations 必须 >= 100")
        if not 0.0 <= args.min_kappa <= 1.0:
            raise ValueError("--min-kappa 必须在 [0, 1] 内")
        report, problems = check(
            Path(args.a),
            Path(args.b),
            delimiter=args.delimiter,
            id_column=args.id_column,
            code_column=args.code_column,
            min_kappa=args.min_kappa,
            bootstrap_iterations=args.bootstrap_iterations,
            seed=args.seed,
        )
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    report["problems"] = problems
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report.get("kappa") is not None:
        print(
            f"human-coding: n={report['n']} kappa={report['kappa']} "
            f"95%CI=[{report['ci95_bootstrap']['low']}, "
            f"{report['ci95_bootstrap']['high']}]",
            file=sys.stderr,
        )
    for problem in problems:
        print(
            f"human-coding-problem {problem['code']}: {problem['message']}",
            file=sys.stderr,
        )
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
