"""Validate rebuttal, resubmission and talk artifact contracts.

The tail of the workflow has different risks from the submission package:
rebuttal promises can outrun evidence, resubmission plans can drift from the
new venue, and talk slides can cite claims or figures that do not exist. This
checker keeps those artifacts explicit without judging their scientific merit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import is_nonempty_str, load_ledger, missing_fields, problem


POST_SUBMISSION = Path("data/post-submission.yaml")
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
RUN_LOG_DIR = Path("experiments/log")
FIGURE_MANIFEST = Path("figures/manifest.yaml")

SECTION_NAMES = ("rebuttal", "resubmit", "talk")
SECTION_STATUSES = {"not-started", "in-progress", "complete", "not-applicable"}
VENUE_DIFF_FIELDS = (
    "id",
    "requirement",
    "current",
    "action",
    "sections",
    "evidence",
    "status",
)
VENUE_DIFF_STATUSES = {"pending", "complete", "not-applicable"}
SLIDE_FIELDS = ("id", "title", "claim_ids", "figure_ids", "talking_points")
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


def _figure_ids(paper_root: Path) -> set[str]:
    path = paper_root / FIGURE_MANIFEST
    if not path.is_file():
        return set()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    figures = payload.get("figures") if isinstance(payload, dict) else None
    if not isinstance(figures, list):
        return set()
    ids: set[str] = set()
    for item in figures:
        if not isinstance(item, dict):
            continue
        value = item.get("id") or item.get("name")
        if is_nonempty_str(value):
            ids.add(value)
    return ids


def _load_payload(paper_root: Path) -> tuple[dict | None, list[Problem], list[Problem]]:
    path = paper_root / POST_SUBMISSION
    if not path.is_file():
        return None, [], [
            problem(
                "post-submission-not-configured",
                path,
                None,
                "尚未配置 post-submission 台账",
            )
        ]
    payload, problems = load_ledger(
        path,
        code="post-submission-invalid",
    )
    return payload if isinstance(payload, dict) else None, problems, []


def _validate_status(
    section_name: str,
    section: object,
    *,
    path: Path,
) -> tuple[list[Problem], str | None]:
    if not isinstance(section, dict):
        return [
            problem(
                "post-submission-invalid",
                path,
                None,
                f"{section_name} 必须是映射",
            )
        ], None
    status = section.get("status")
    if status not in SECTION_STATUSES:
        return [
            problem(
                "post-submission-invalid",
                path,
                None,
                f"{section_name}.status 非法",
            )
        ], None
    if status == "not-applicable":
        reason = section.get("reason")
        if not is_nonempty_str(reason):
            return [
                problem(
                    "post-submission-na-reason-missing",
                    path,
                    None,
                    f"{section_name}=not-applicable 需要非空 reason",
                )
            ], status
    return [], status


def _validate_rebuttal(
    paper_root: Path,
    section: dict,
    *,
    path: Path,
    run_ids: set[str],
) -> list[Problem]:
    if section.get("status") != "complete":
        return []
    problems: list[Problem] = []
    ledger = section.get("response_ledger")
    if not is_nonempty_str(ledger):
        problems.append(
            problem(
                "post-submission-rebuttal-incomplete",
                path,
                None,
                "rebuttal=complete 需要 response_ledger",
            )
        )
    else:
        resolved = (paper_root / ledger).resolve()
        try:
            resolved.relative_to(paper_root.resolve())
        except ValueError:
            resolved = None
        if resolved is None or not resolved.is_file():
            problems.append(
                problem(
                    "post-submission-missing-ledger",
                    path,
                    None,
                    f"response_ledger 不存在或越界: {ledger!r}",
                )
            )
    run_values = section.get("new_evidence_run_ids", [])
    if not _string_list(run_values, allow_empty=True):
        problems.append(
            problem(
                "post-submission-invalid",
                path,
                None,
                "rebuttal.new_evidence_run_ids 必须是字符串数组",
            )
        )
    else:
        for run_id in run_values:
            if run_id not in run_ids:
                problems.append(
                    problem(
                        "post-submission-unknown-run",
                        path,
                        None,
                        f"rebuttal.new_evidence_run_ids 引用了不存在的 run: {run_id!r}",
                    )
                )
    commitments = section.get("commitments", [])
    if not _string_list(commitments, allow_empty=True):
        problems.append(
            problem(
                "post-submission-invalid",
                path,
                None,
                "rebuttal.commitments 必须是字符串数组",
            )
        )
    elif any(_placeholder(value) for value in commitments):
        problems.append(
            problem(
                "post-submission-placeholder",
                path,
                None,
                "rebuttal.commitments 仍是 placeholder",
            )
        )
    return problems


def _validate_evidence(
    paper_root: Path,
    evidence: object,
    run_ids: set[str],
    *,
    path: Path,
    item_id: str,
) -> list[Problem]:
    if not _string_list(evidence):
        return [
            problem(
                "post-submission-invalid",
                path,
                None,
                f"{item_id}: evidence 必须是非空字符串数组",
            )
        ]
    problems: list[Problem] = []
    for value in evidence:
        if value in run_ids:
            continue
        candidate = (paper_root / value).resolve()
        try:
            candidate.relative_to(paper_root.resolve())
        except ValueError:
            candidate = None
        if candidate is None or not candidate.is_file():
            problems.append(
                problem(
                    "post-submission-evidence-unknown",
                    path,
                    None,
                    f"{item_id}: evidence 不是已有 run id 或仓库内文件: {value!r}",
                )
            )
    return problems


def _validate_resubmit(
    paper_root: Path,
    section: dict,
    *,
    path: Path,
    run_ids: set[str],
) -> list[Problem]:
    if section.get("status") != "complete":
        return []
    problems: list[Problem] = []
    for field in ("from_venue", "to_venue"):
        value = section.get(field)
        if not is_nonempty_str(value):
            problems.append(
                problem(
                    "post-submission-resubmit-incomplete",
                    path,
                    None,
                    f"resubmit=complete 需要 {field}",
                )
            )
    diff = section.get("venue_diff")
    if not isinstance(diff, list) or not diff:
        problems.append(
            problem(
                "post-submission-resubmit-incomplete",
                path,
                None,
                "resubmit=complete 需要非空 venue_diff",
            )
        )
    else:
        seen: set[str] = set()
        for index, item in enumerate(diff):
            if not isinstance(item, dict):
                problems.append(
                    problem(
                        "post-submission-invalid",
                        path,
                        None,
                        f"venue_diff[{index}] 必须是映射",
                    )
                )
                continue
            missing = missing_fields(item, VENUE_DIFF_FIELDS)
            if missing:
                problems.append(
                    problem(
                        "post-submission-invalid",
                        path,
                        None,
                        f"venue_diff[{index}] 缺少字段: {', '.join(missing)}",
                    )
                )
                continue
            item_id = item.get("id")
            if not is_nonempty_str(item_id):
                problems.append(
                    problem(
                        "post-submission-invalid",
                        path,
                        None,
                        f"venue_diff[{index}].id 必须是非空字符串",
                    )
                )
                continue
            if item_id in seen:
                problems.append(
                    problem(
                        "post-submission-duplicate",
                        path,
                        None,
                        f"venue_diff id 重复: {item_id}",
                    )
                )
            seen.add(item_id)
            for field in ("requirement", "current", "action"):
                value = item.get(field)
                if not is_nonempty_str(value):
                    problems.append(
                        problem(
                            "post-submission-invalid",
                            path,
                            None,
                            f"{item_id}: {field} 必须是非空字符串",
                        )
                    )
                elif _placeholder(value):
                    problems.append(
                        problem(
                            "post-submission-placeholder",
                            path,
                            None,
                            f"{item_id}: {field} 仍是 placeholder",
                        )
                    )
            if not _string_list(item.get("sections")):
                problems.append(
                    problem(
                        "post-submission-invalid",
                        path,
                        None,
                        f"{item_id}: sections 必须是非空字符串数组",
                    )
                )
            status = item.get("status")
            if status not in VENUE_DIFF_STATUSES:
                problems.append(
                    problem(
                        "post-submission-invalid",
                        path,
                        None,
                        f"{item_id}: status 非法",
                    )
                )
            if status == "complete":
                problems.extend(
                    _validate_evidence(
                        paper_root,
                        item.get("evidence"),
                        run_ids,
                        path=path,
                        item_id=item_id,
                    )
                )
    sections = section.get("sections_to_rewrite")
    if not _string_list(sections):
        problems.append(
            problem(
                "post-submission-resubmit-incomplete",
                path,
                None,
                "resubmit=complete 需要非空 sections_to_rewrite",
            )
        )
    return problems


def _validate_talk(
    section: dict,
    *,
    path: Path,
    claim_ids: set[str],
    figure_ids: set[str],
) -> list[Problem]:
    if section.get("status") != "complete":
        return []
    problems: list[Problem] = []
    slides = section.get("slide_outline")
    if not isinstance(slides, list) or not slides:
        return [
            problem(
                "post-submission-talk-incomplete",
                path,
                None,
                "talk=complete 需要非空 slide_outline",
            )
        ]
    seen: set[str] = set()
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"slide_outline[{index}] 必须是映射",
                )
            )
            continue
        missing = missing_fields(slide, SLIDE_FIELDS)
        if missing:
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"slide_outline[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        slide_id = slide.get("id")
        if not is_nonempty_str(slide_id):
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"slide_outline[{index}].id 必须是非空字符串",
                )
            )
            continue
        if slide_id in seen:
            problems.append(
                problem(
                    "post-submission-duplicate",
                    path,
                    None,
                    f"slide id 重复: {slide_id}",
                )
            )
        seen.add(slide_id)
        title = slide.get("title")
        if not is_nonempty_str(title):
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"{slide_id}: title 必须是非空字符串",
                )
            )
        elif _placeholder(title):
            problems.append(
                problem(
                    "post-submission-placeholder",
                    path,
                    None,
                    f"{slide_id}: title 仍是 placeholder",
                )
            )
        claim_values = slide.get("claim_ids")
        if not _string_list(claim_values):
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"{slide_id}: claim_ids 必须是非空字符串数组",
                )
            )
        else:
            for claim_id in claim_values:
                if claim_id not in claim_ids:
                    problems.append(
                        problem(
                            "post-submission-unknown-claim",
                            path,
                            None,
                            f"{slide_id}: claim {claim_id!r} 不存在",
                        )
                    )
        figure_values = slide.get("figure_ids", [])
        if not _string_list(figure_values, allow_empty=True):
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"{slide_id}: figure_ids 必须是字符串数组",
                )
            )
        else:
            for figure_id in figure_values:
                if figure_id not in figure_ids:
                    problems.append(
                        problem(
                            "post-submission-unknown-figure",
                            path,
                            None,
                            f"{slide_id}: figure {figure_id!r} 不存在",
                        )
                    )
        points = slide.get("talking_points")
        if not _string_list(points):
            problems.append(
                problem(
                    "post-submission-invalid",
                    path,
                    None,
                    f"{slide_id}: talking_points 必须是非空字符串数组",
                )
            )
        elif any(_placeholder(value) for value in points):
            problems.append(
                problem(
                    "post-submission-placeholder",
                    path,
                    None,
                    f"{slide_id}: talking_points 仍是 placeholder",
                )
            )
    return problems


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_payload(paper_root)
    if payload is None:
        return problems, advisories
    path = paper_root / POST_SUBMISSION
    sections: dict[str, dict] = {}
    statuses: dict[str, str | None] = {}
    for name in SECTION_NAMES:
        section_problems, status = _validate_status(
            name,
            payload.get(name),
            path=path,
        )
        problems.extend(section_problems)
        statuses[name] = status
        if isinstance(payload.get(name), dict):
            sections[name] = payload[name]

    run_ids = _run_ids(paper_root)
    claim_ids = _claim_ids(paper_root)
    figure_ids = _figure_ids(paper_root)
    problems.extend(
        _validate_rebuttal(
            paper_root,
            sections.get("rebuttal", {}),
            path=path,
            run_ids=run_ids,
        )
    )
    problems.extend(
        _validate_resubmit(
            paper_root,
            sections.get("resubmit", {}),
            path=path,
            run_ids=run_ids,
        )
    )
    problems.extend(
        _validate_talk(
            sections.get("talk", {}),
            path=path,
            claim_ids=claim_ids,
            figure_ids=figure_ids,
        )
    )
    if all(status == "not-started" for status in statuses.values()):
        advisories.append(
            problem(
                "post-submission-empty",
                path,
                None,
                "post-submission 台账已创建但尚未填写",
            )
        )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验 rebuttal、resubmit 与 talk 产出物契约"
    )
    parser.add_argument(
        "action",
        choices=("check",),
        nargs="?",
        default="check",
    )
    parser.add_argument("--paper-root", default=".")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        problems, advisories = check(Path(args.paper_root))
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    return emit(problems, advisories)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
