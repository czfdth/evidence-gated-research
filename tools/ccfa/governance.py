"""Validate the governance and ethics ledger.

This is a completeness gate, not a truth checker. It cannot verify that a
declared conflict is complete or that an IRB approval number is genuine. It
makes those declarations explicit, attributed, and machine-checkable before
the submission gate can pass.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ccfa.cli import emit, tool_error
from ccfa.ledger import (
    is_iso_date,
    is_nonempty_str,
    load_ledger,
    missing_fields,
    problem,
)

LEDGER_RELATIVE_PATH = Path("data") / "governance.yaml"
REQUIRED_TOP = (
    "authors",
    "conflicts",
    "ethics",
    "ai_usage",
    "plagiarism",
    "responsible_disclosure",
)
AUTHOR_FIELDS = ("name", "affiliation", "roles", "corresponding")
CONFLICT_FIELDS = ("name", "declared")
ETHICS_FIELDS = ("human_subjects", "data_license")
_PLACEHOLDER = re.compile(
    r"(?<![a-z0-9])("
    r"pending|tbd|todo|placeholder|to[ -]be[ -]determined"
    r")(?![a-z0-9])",
    re.IGNORECASE,
)


def _placeholder(value: object) -> bool:
    return (
        isinstance(value, str)
        and _PLACEHOLDER.search(" ".join(value.casefold().split())) is not None
    )


def _check_authors(path: Path, authors: object) -> tuple[list, set[str]]:
    problems = []
    names: set[str] = set()
    if not isinstance(authors, list) or not authors:
        problems.append(
            problem("governance-invalid", path, None, "authors 必须是非空数组")
        )
        return problems, names
    for index, author in enumerate(authors):
        if not isinstance(author, dict):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"authors[{index}] 必须是映射",
                )
            )
            continue
        missing = missing_fields(author, AUTHOR_FIELDS)
        if missing:
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"authors[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        name = author.get("name")
        if not is_nonempty_str(name):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"authors[{index}].name 必须是非空字符串",
                )
            )
            continue
        name = name.strip()
        if name in names:
            problems.append(
                problem(
                    "governance-duplicate-author",
                    path,
                    None,
                    f"作者重复: {name}",
                )
            )
        names.add(name)
        if not is_nonempty_str(author.get("affiliation")):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"{name}: affiliation 必须是非空字符串",
                )
            )
        roles = author.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or not all(is_nonempty_str(role) for role in roles)
        ):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"{name}: roles 必须是非空字符串数组",
                )
            )
        if not isinstance(author.get("corresponding"), bool):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"{name}: corresponding 必须是布尔值",
                )
            )
    if not any(
        isinstance(author, dict) and author.get("corresponding") is True
        for author in authors
    ):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "至少需要一名 corresponding=true 的作者",
            )
        )
    return problems, names


def _check_conflicts(path: Path, conflicts: object, authors: set[str]) -> list:
    problems = []
    if not isinstance(conflicts, list) or not conflicts:
        problems.append(
            problem("governance-invalid", path, None, "conflicts 必须是非空数组")
        )
        return problems
    seen: set[str] = set()
    for index, conflict in enumerate(conflicts):
        if not isinstance(conflict, dict):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"conflicts[{index}] 必须是映射",
                )
            )
            continue
        missing = missing_fields(conflict, CONFLICT_FIELDS)
        if missing:
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"conflicts[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        name = conflict.get("name")
        if not is_nonempty_str(name):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"conflicts[{index}].name 必须是非空字符串",
                )
            )
            continue
        name = name.strip()
        seen.add(name)
        if name not in authors:
            problems.append(
                problem(
                    "governance-unknown-author",
                    path,
                    None,
                    f"conflicts 中的 {name!r} 不在 authors 中",
                )
            )
        if not is_nonempty_str(conflict.get("declared")):
            problems.append(
                problem(
                    "governance-invalid",
                    path,
                    None,
                    f"{name}: declared 必须是非空字符串（无利益冲突写 none）",
                )
            )
        elif _placeholder(conflict.get("declared")):
            problems.append(
                problem(
                    "governance-placeholder",
                    path,
                    None,
                    f"{name}: 利益冲突声明仍是 pending/placeholder 文本",
                )
            )
    for name in sorted(authors - seen):
        problems.append(
            problem(
                "governance-missing-conflict",
                path,
                None,
                f"{name}: 缺少利益冲突声明",
            )
        )
    return problems


def _check_ethics(path: Path, ethics: object) -> list:
    problems = []
    if not isinstance(ethics, dict):
        return [
            problem("governance-invalid", path, None, "ethics 必须是映射")
        ]
    missing = missing_fields(ethics, ETHICS_FIELDS)
    if missing:
        return [
            problem(
                "governance-invalid",
                path,
                None,
                f"ethics 缺少字段: {', '.join(missing)}",
            )
        ]
    human_subjects = ethics.get("human_subjects")
    if not isinstance(human_subjects, bool):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "ethics.human_subjects 必须是布尔值",
            )
        )
    if not is_nonempty_str(ethics.get("data_license")):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "ethics.data_license 必须是非空字符串",
            )
        )
    if human_subjects is True:
        for field in ("irb_approval", "informed_consent"):
            if not is_nonempty_str(ethics.get(field)):
                problems.append(
                    problem(
                        "governance-missing-ethics",
                        path,
                        None,
                        f"human_subjects=true 时 ethics.{field} 必填",
                    )
                )
    return problems


def _check_ai_usage(path: Path, ai_usage: object) -> list:
    if not isinstance(ai_usage, dict):
        return [
            problem("governance-invalid", path, None, "ai_usage 必须是映射")
        ]
    problems = []
    if ai_usage.get("disclosed") is not True:
        problems.append(
            problem(
                "governance-missing-ai-disclosure",
                path,
                None,
                "ai_usage.disclosed 必须为 true",
            )
        )
    if not is_nonempty_str(ai_usage.get("policy")):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "ai_usage.policy 必须是非空字符串",
            )
        )
    return problems


def _check_plagiarism(path: Path, plagiarism: object) -> list:
    if not isinstance(plagiarism, dict):
        return [
            problem("governance-invalid", path, None, "plagiarism 必须是映射")
        ]
    problems = []
    if plagiarism.get("checked") is not True:
        problems.append(
            problem(
                "governance-missing-plagiarism-check",
                path,
                None,
                "plagiarism.checked 必须为 true",
            )
        )
    if not is_nonempty_str(plagiarism.get("tool")):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "plagiarism.tool 必须是非空字符串",
            )
        )
    elif _placeholder(plagiarism.get("tool")):
        problems.append(
            problem(
                "governance-placeholder",
                path,
                None,
                "plagiarism.tool 仍是 pending/placeholder 文本",
            )
        )
    if not is_iso_date(plagiarism.get("date")):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "plagiarism.date 必须是 YYYY-MM-DD",
            )
        )
    return problems


def _check_disclosure(path: Path, disclosure: object) -> list:
    if not isinstance(disclosure, dict):
        return [
            problem(
                "governance-invalid",
                path,
                None,
                "responsible_disclosure 必须是映射",
            )
        ]
    problems = []
    if disclosure.get("dual_use_reviewed") is not True:
        problems.append(
            problem(
                "governance-missing-dual-use",
                path,
                None,
                "responsible_disclosure.dual_use_reviewed 必须为 true",
            )
        )
    if not is_nonempty_str(disclosure.get("disclosure_contact")):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "responsible_disclosure.disclosure_contact 必须是非空字符串",
            )
        )
    elif _placeholder(disclosure.get("disclosure_contact")):
        problems.append(
            problem(
                "governance-placeholder",
                path,
                None,
                "responsible_disclosure.disclosure_contact 仍是 pending/placeholder 文本",
            )
        )
    if not is_nonempty_str(disclosure.get("notes")):
        problems.append(
            problem(
                "governance-invalid",
                path,
                None,
                "responsible_disclosure.notes 必须是非空字符串",
            )
        )
    return problems


def check(paper_root: Path, ledger: Path | None = None) -> tuple[list, list]:
    paper_root = Path(paper_root)
    path = Path(ledger) if ledger else paper_root / LEDGER_RELATIVE_PATH
    payload, problems = load_ledger(
        path,
        code="governance-ledger-missing",
    )
    if payload is None:
        return problems, []
    missing = missing_fields(payload, REQUIRED_TOP)
    if missing:
        return [
            problem(
                "governance-invalid",
                path,
                None,
                f"治理台账缺少字段: {', '.join(missing)}",
            )
        ], []
    author_problems, authors = _check_authors(path, payload["authors"])
    problems.extend(author_problems)
    problems.extend(_check_conflicts(path, payload["conflicts"], authors))
    problems.extend(_check_ethics(path, payload["ethics"]))
    problems.extend(_check_ai_usage(path, payload["ai_usage"]))
    problems.extend(_check_plagiarism(path, payload["plagiarism"]))
    problems.extend(
        _check_disclosure(path, payload["responsible_disclosure"])
    )
    return problems, []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="检查治理、伦理、利益冲突、AI 使用与负责任披露台账"
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
