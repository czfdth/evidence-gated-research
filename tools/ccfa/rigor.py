"""Validate the six-dimension rigor rubric.

The rubric does not decide whether a paper is good. It forces a reviewer to
make six independent judgements explicit and bind each one to inspectable
evidence. A model review may be recorded as advisory, but only a human or
mixed review may be marked ``complete``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import (
    is_iso_date,
    is_nonempty_str,
    load_ledger,
    missing_fields,
    problem,
)


RIGOR_RUBRIC = Path("data/rigor-rubric.yaml")
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
RUN_LOG_DIR = Path("experiments/log")

DIMENSIONS = (
    "evidence_relevance",
    "falsifiability",
    "scope",
    "coherence",
    "exploration_integrity",
    "methodology",
)
DIMENSION_FIELDS = ("score", "rationale", "evidence")
REVIEWER_FIELDS = ("kind", "identity", "reviewed_at")
REVIEWER_KINDS = {"human", "model", "mixed"}
STATUSES = {"not-started", "in-progress", "model-advisory", "complete"}
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


def _string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(is_nonempty_str(item) for item in value)
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


def _evidence_known(
    paper_root: Path,
    value: object,
    *,
    claim_ids: set[str],
    run_ids: set[str],
) -> bool:
    if not is_nonempty_str(value):
        return False
    text = value.strip()
    if text in claim_ids or text in run_ids:
        return True
    candidate = (paper_root / text).resolve()
    try:
        candidate.relative_to(paper_root.resolve())
    except ValueError:
        return False
    return candidate.is_file()


def _validate_reviewer(
    payload: dict,
    *,
    path: Path,
    status: str,
    require_complete: bool,
) -> list[Problem]:
    reviewer = payload.get("reviewed_by")
    if not isinstance(reviewer, dict):
        return [
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                "reviewed_by 必须是映射",
            )
        ]
    problems: list[Problem] = []
    missing = missing_fields(reviewer, REVIEWER_FIELDS)
    if missing:
        return [
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                f"reviewed_by 缺少字段: {', '.join(missing)}",
            )
        ]
    kind = reviewer.get("kind")
    if kind not in REVIEWER_KINDS:
        problems.append(
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                "reviewed_by.kind 非法",
            )
        )
    if kind == "model" and (status == "complete" or require_complete):
        problems.append(
            problem(
                "rigor-model-cannot-acquit",
                path,
                None,
                "模型评审只能 advisory，不能把 rigor rubric 标记为 complete",
            )
        )
    for field in ("identity", "reviewed_at"):
        value = reviewer.get(field)
        if not is_nonempty_str(value):
            problems.append(
                problem(
                    "rigor-rubric-invalid",
                    path,
                    None,
                    f"reviewed_by.{field} 必须是非空字符串",
                )
            )
        elif _placeholder(value):
            problems.append(
                problem(
                    "rigor-rubric-placeholder",
                    path,
                    None,
                    f"reviewed_by.{field} 仍是 placeholder",
                )
            )
    if not is_iso_date(reviewer.get("reviewed_at")):
        problems.append(
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                "reviewed_by.reviewed_at 必须是 YYYY-MM-DD",
            )
        )
    return problems


def _validate_dimensions(
    payload: dict,
    *,
    paper_root: Path,
    path: Path,
    claim_ids: set[str],
    run_ids: set[str],
) -> list[Problem]:
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict):
        return [
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                "dimensions 必须是映射",
            )
        ]
    problems: list[Problem] = []
    missing = [name for name in DIMENSIONS if name not in dimensions]
    if missing:
        problems.append(
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                f"缺少维度: {', '.join(missing)}",
            )
        )
    for name in DIMENSIONS:
        item = dimensions.get(name)
        if not isinstance(item, dict):
            problems.append(
                problem(
                    "rigor-rubric-invalid",
                    path,
                    None,
                    f"dimensions.{name} 必须是映射",
                )
            )
            continue
        missing_fields_ = missing_fields(item, DIMENSION_FIELDS)
        if missing_fields_:
            problems.append(
                problem(
                    "rigor-rubric-invalid",
                    path,
                    None,
                    f"dimensions.{name} 缺少字段: {', '.join(missing_fields_)}",
                )
            )
            continue
        score = item.get("score")
        if type(score) is not int or not 0 <= score <= 4:
            problems.append(
                problem(
                    "rigor-rubric-invalid",
                    path,
                    None,
                    f"dimensions.{name}.score 必须是 0..4 整数",
                )
            )
        rationale = item.get("rationale")
        if not is_nonempty_str(rationale):
            problems.append(
                problem(
                    "rigor-rubric-invalid",
                    path,
                    None,
                    f"dimensions.{name}.rationale 必须是非空字符串",
                )
            )
        elif _placeholder(rationale):
            problems.append(
                problem(
                    "rigor-rubric-placeholder",
                    path,
                    None,
                    f"dimensions.{name}.rationale 仍是 placeholder",
                )
            )
        evidence = item.get("evidence")
        if not _string_list(evidence):
            problems.append(
                problem(
                    "rigor-rubric-invalid",
                    path,
                    None,
                    f"dimensions.{name}.evidence 必须是非空字符串数组",
                )
            )
        else:
            for value in evidence:
                if not _evidence_known(
                    paper_root,
                    value,
                    claim_ids=claim_ids,
                    run_ids=run_ids,
                ):
                    problems.append(
                        problem(
                            "rigor-rubric-unknown-evidence",
                            path,
                            None,
                            f"dimensions.{name}.evidence 引用了不存在的证据: {value!r}",
                        )
                    )
    return problems


def check(
    paper_root: Path,
    *,
    require_complete: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    path = paper_root / RIGOR_RUBRIC
    if not path.is_file():
        if require_complete:
            return [
                problem(
                    "rigor-rubric-missing",
                    path,
                    None,
                    "缺少 rigor rubric 台账",
                )
            ], []
        return [], [
            problem(
                "rigor-rubric-not-configured",
                path,
                None,
                "尚未配置 rigor rubric",
            )
        ]

    payload, problems = load_ledger(path, code="rigor-rubric-invalid")
    advisories: list[Problem] = []
    if not isinstance(payload, dict):
        return problems, advisories

    status = payload.get("status")
    if status not in STATUSES:
        problems.append(
            problem(
                "rigor-rubric-invalid",
                path,
                None,
                "status 非法",
            )
        )
        return problems, advisories

    if status in {"not-started", "in-progress"}:
        if require_complete:
            problems.append(
                problem(
                    "rigor-rubric-not-complete",
                    path,
                    None,
                    f"rigor rubric 仍为 {status}",
                )
            )
        else:
            advisories.append(
                problem(
                    "rigor-rubric-not-started",
                    path,
                    None,
                    f"rigor rubric 仍为 {status}",
                )
            )
        return problems, advisories

    if status == "model-advisory":
        if not require_complete:
            advisories.append(
                problem(
                    "rigor-model-advisory",
                    path,
                    None,
                    "模型 review 只能作为 rigor advisory",
                )
            )

    problems.extend(
        _validate_reviewer(
            payload,
            path=path,
            status=status,
            require_complete=require_complete,
        )
    )
    problems.extend(
        _validate_dimensions(
            payload,
            paper_root=paper_root,
            path=path,
            claim_ids=_claim_ids(paper_root),
            run_ids=_run_ids(paper_root),
        )
    )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验六维 rigor rubric 的证据绑定与人工复核边界"
    )
    parser.add_argument(
        "action",
        choices=("check",),
        nargs="?",
        default="check",
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="高风险论文要求 rigor rubric 已完成且由真人复核",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.paper_root),
            require_complete=args.require_complete,
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
