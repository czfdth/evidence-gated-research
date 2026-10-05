"""Validate ACM-style artifact badge and long-term archive evidence.

The checker cannot decide whether an artifact is reusable. It enforces that
available / evaluated / reusable claims point to inspectable evidence, and
that evaluated/reusable claims are not certified by a model name.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import (
    is_iso_date,
    is_nonempty_str,
    load_ledger,
    missing_fields,
    problem,
)


ARTIFACT_BADGE = Path("data/artifact-badge.yaml")
BADGE_NAMES = ("available", "evaluated", "reusable")
BADGE_FIELDS = ("status", "evidence", "rationale")
STATUSES = {"not-started", "in-progress", "verified", "not-applicable"}
BADGE_STATUSES = {"not-started", "claimed", "verified", "not-applicable"}
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
PLACEHOLDER = re.compile(
    r"(?<![a-z0-9])(pending|tbd|todo|placeholder|"
    r"to[ -]be[ -]determined)(?![a-z0-9])",
    re.IGNORECASE,
)
MODEL_REVIEWER = re.compile(
    r"(?i)\b(gpt|chatgpt|claude|gemini|deepseek|qwen|llama|mistral|"
    r"grok|sonnet|haiku|opus|nova|command|phi|o[134])\b"
)


def _placeholder(value: object) -> bool:
    return (
        isinstance(value, str)
        and PLACEHOLDER.search(" ".join(value.casefold().split())) is not None
    )


def _human_reviewer(value: object) -> bool:
    return (
        is_nonempty_str(value)
        and MODEL_REVIEWER.search(value) is None
    )


def _string_list(value: object, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    return all(is_nonempty_str(item) for item in value)


def _valid_url(value: object) -> bool:
    if not is_nonempty_str(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _evidence_known(paper_root: Path, value: object) -> bool:
    if not is_nonempty_str(value):
        return False
    if _valid_url(value):
        return True
    candidate = (paper_root / value).resolve()
    try:
        candidate.relative_to(paper_root.resolve())
    except ValueError:
        return False
    return candidate.is_file()


def _load_payload(
    paper_root: Path,
) -> tuple[dict | None, list[Problem], list[Problem]]:
    path = paper_root / ARTIFACT_BADGE
    if not path.is_file():
        return None, [], [
            problem(
                "artifact-badge-not-configured",
                path,
                None,
                "尚未配置 artifact badge 台账",
            )
        ]
    payload, problems = load_ledger(path, code="artifact-badge-invalid")
    return payload if isinstance(payload, dict) else None, problems, []


def _validate_badge(
    paper_root: Path,
    name: str,
    badge: object,
    *,
    path: Path,
    require_verified: bool,
) -> list[Problem]:
    if not isinstance(badge, dict):
        return [
            problem(
                "artifact-badge-invalid",
                path,
                None,
                f"badges.{name} 必须是映射",
            )
        ]
    missing = missing_fields(badge, BADGE_FIELDS)
    if missing:
        return [
            problem(
                "artifact-badge-invalid",
                path,
                None,
                f"badges.{name} 缺少字段: {', '.join(missing)}",
            )
        ]
    problems: list[Problem] = []
    status = badge.get("status")
    if status not in BADGE_STATUSES:
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                f"badges.{name}.status 非法",
            )
        )
        return problems
    if status == "not-applicable":
        reason = badge.get("reason")
        if not is_nonempty_str(reason):
            problems.append(
                problem(
                    "artifact-badge-invalid",
                    path,
                    None,
                    f"badges.{name}=not-applicable 需要 reason",
                )
            )
        return problems
    if status != "verified":
        if require_verified:
            problems.append(
                problem(
                    "artifact-badge-not-verified",
                    path,
                    None,
                    f"badges.{name} 仍为 {status}",
                )
            )
        return problems

    evidence = badge.get("evidence")
    if not _string_list(evidence):
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                f"badges.{name}.evidence 必须是非空字符串数组",
            )
        )
    else:
        for value in evidence:
            if not _evidence_known(paper_root, value):
                problems.append(
                    problem(
                        "artifact-badge-unknown-evidence",
                        path,
                        None,
                        f"badges.{name}.evidence 不是 URL 或仓库内文件: {value!r}",
                    )
                )
    rationale = badge.get("rationale")
    if not is_nonempty_str(rationale):
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                f"badges.{name}.rationale 必须是非空字符串",
            )
        )
    elif _placeholder(rationale):
        problems.append(
            problem(
                "artifact-badge-placeholder",
                path,
                None,
                f"badges.{name}.rationale 仍是 placeholder",
            )
        )
    if name == "evaluated":
        reviewer = badge.get("independent_reviewer")
        if not _human_reviewer(reviewer):
            problems.append(
                problem(
                    "artifact-badge-reviewer-not-human",
                    path,
                    None,
                    "evaluated 需要非模型 independent_reviewer",
                )
            )
        if not is_iso_date(badge.get("reviewed_at")):
            problems.append(
                problem(
                    "artifact-badge-invalid",
                    path,
                    None,
                    "evaluated 需要 YYYY-MM-DD reviewed_at",
                )
            )
    if name == "reusable" and not is_nonempty_str(badge.get("reuse_context")):
        problems.append(
            problem(
                "artifact-badge-reusable-incomplete",
                path,
                None,
                "reusable 需要 reuse_context",
            )
        )
    return problems


def check(
    paper_root: Path,
    *,
    require_verified: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_payload(paper_root)
    if payload is None:
        if require_verified:
            return [
                problem(
                    "artifact-badge-missing",
                    paper_root / ARTIFACT_BADGE,
                    None,
                    "缺少 artifact badge 台账",
                )
            ], []
        return problems, advisories
    path = paper_root / ARTIFACT_BADGE
    status = payload.get("status")
    if status not in STATUSES:
        return [
            problem(
                "artifact-badge-invalid",
                path,
                None,
                "status 非法",
            )
        ], advisories
    if status == "not-applicable":
        if not is_nonempty_str(payload.get("reason")):
            problems.append(
                problem(
                    "artifact-badge-invalid",
                    path,
                    None,
                    "status=not-applicable 需要 reason",
                )
            )
        return problems, advisories
    if status in {"not-started", "in-progress"}:
        if require_verified:
            problems.append(
                problem(
                    "artifact-badge-not-verified",
                    path,
                    None,
                    f"artifact badge 仍为 {status}",
                )
            )
        else:
            advisories.append(
                problem(
                    "artifact-badge-not-started",
                    path,
                    None,
                    f"artifact badge 仍为 {status}",
                )
            )
        return problems, advisories

    doi = payload.get("doi")
    archive_url = payload.get("archive_url")
    if doi is not None and (not is_nonempty_str(doi) or not DOI.fullmatch(doi)):
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                "doi 必须是 DOI 字符串",
            )
        )
    if archive_url is not None and not _valid_url(archive_url):
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                "archive_url 必须是 http(s) URL",
            )
        )
    if not is_nonempty_str(doi) and not _valid_url(archive_url):
        problems.append(
            problem(
                "artifact-badge-archive-missing",
                path,
                None,
                "verified 至少需要 DOI 或 archive_url",
            )
        )
    license_payload = payload.get("license")
    if not isinstance(license_payload, dict):
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                "license 必须是映射",
            )
        )
    else:
        for field in ("code", "data"):
            if not is_nonempty_str(license_payload.get(field)):
                problems.append(
                    problem(
                        "artifact-badge-invalid",
                        path,
                        None,
                        f"license.{field} 必须是非空字符串",
                    )
                )
    badges = payload.get("badges")
    if not isinstance(badges, dict):
        problems.append(
            problem(
                "artifact-badge-invalid",
                path,
                None,
                "badges 必须是映射",
            )
        )
        return problems, advisories
    for name in BADGE_NAMES:
        problems.extend(
            _validate_badge(
                paper_root,
                name,
                badges.get(name),
                path=path,
                require_verified=require_verified or status == "verified",
            )
        )
    return problems, advisories


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验 ACM artifact badge、独立复核与长期归档证据"
    )
    parser.add_argument(
        "action",
        choices=("check",),
        nargs="?",
        default="check",
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument(
        "--require-verified",
        action="store_true",
        help="高风险/发布检查要求三个 badge 与归档证据完整",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.paper_root),
            require_verified=args.require_verified,
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
