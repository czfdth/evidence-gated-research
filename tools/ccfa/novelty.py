"""Validate a structured novelty audit.

This gate cannot prove that an idea is novel. It requires the author to
record the search surface, date, at least three nearest neighbors, what each
neighbor overlaps with, what it does not cover, and which claim each
comparison addresses. It also rejects unsupported "no one has done it"
language.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ccfa.bib import load_records
from ccfa.cli import emit, tool_error
from ccfa.ledger import (
    is_iso_date,
    is_nonempty_str,
    load_ledger,
    missing_fields,
    problem,
)

LEDGER_RELATIVE_PATH = Path("data") / "novelty-audit.yaml"
TOP_FIELDS = ("search", "neighbors", "claims")
SEARCH_FIELDS = ("databases", "queries", "searched_at", "cutoff")
NEIGHBOR_FIELDS = (
    "id",
    "title",
    "venue",
    "overlap",
    "difference",
    "claim_ids",
)
BANNED_PHRASES = (
    "没人做过",
    "无人做过",
    "no one has done",
    "first to",
)


def _check_search(path: Path, search: object) -> list:
    if not isinstance(search, dict):
        return [
            problem("novelty-invalid", path, None, "search 必须是映射")
        ]
    missing = missing_fields(search, SEARCH_FIELDS)
    if missing:
        return [
            problem(
                "novelty-invalid",
                path,
                None,
                f"search 缺少字段: {', '.join(missing)}",
            )
        ]
    problems = []
    databases = search.get("databases")
    if (
        not isinstance(databases, list)
        or len(databases) < 2
        or not all(is_nonempty_str(item) for item in databases)
    ):
        problems.append(
            problem(
                "novelty-thin-search",
                path,
                None,
                "search.databases 至少需要两个非空数据库名",
            )
        )
    elif len(
        {item.strip().casefold() for item in databases}
    ) != len(databases):
        problems.append(
            problem(
                "novelty-duplicate-database",
                path,
                None,
                "search.databases 不能包含重复项",
            )
        )
    queries = search.get("queries")
    if (
        not isinstance(queries, list)
        or not queries
        or not all(is_nonempty_str(item) for item in queries)
    ):
        problems.append(
            problem(
                "novelty-thin-search",
                path,
                None,
                "search.queries 必须是非空字符串数组",
            )
        )
    searched_at = search.get("searched_at")
    cutoff = search.get("cutoff")
    if not is_iso_date(searched_at):
        problems.append(
            problem(
                "novelty-invalid",
                path,
                None,
                "search.searched_at 必须是 YYYY-MM-DD",
            )
        )
    if not is_iso_date(cutoff):
        problems.append(
            problem(
                "novelty-invalid",
                path,
                None,
                "search.cutoff 必须是 YYYY-MM-DD",
            )
        )
    if is_iso_date(searched_at) and is_iso_date(cutoff) and cutoff > searched_at:
        problems.append(
            problem(
                "novelty-invalid",
                path,
                None,
                "search.cutoff 不能晚于 searched_at",
            )
        )
    return problems


def _check_neighbors(
    path: Path,
    neighbors: object,
    claims: list[str],
    bib_keys: set[str],
) -> list:
    problems = []
    if not isinstance(neighbors, list) or len(neighbors) < 3:
        return [
            problem(
                "novelty-thin-neighbors",
                path,
                None,
                "neighbors 至少需要三篇最近邻工作",
            )
        ]
    ids: set[str] = set()
    titles: set[str] = set()
    covered: set[str] = set()
    for index, neighbor in enumerate(neighbors):
        if not isinstance(neighbor, dict):
            problems.append(
                problem(
                    "novelty-invalid",
                    path,
                    None,
                    f"neighbors[{index}] 必须是映射",
                )
            )
            continue
        missing = missing_fields(neighbor, NEIGHBOR_FIELDS)
        if missing:
            problems.append(
                problem(
                    "novelty-invalid",
                    path,
                    None,
                    f"neighbors[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        neighbor_id = neighbor.get("id")
        if not is_nonempty_str(neighbor_id):
            problems.append(
                problem(
                    "novelty-invalid",
                    path,
                    None,
                    f"neighbors[{index}].id 必须是非空字符串",
                )
            )
            continue
        neighbor_id = neighbor_id.strip()
        if neighbor_id in ids:
            problems.append(
                problem(
                    "novelty-duplicate-neighbor",
                    path,
                    None,
                    f"neighbor id 重复: {neighbor_id}",
                )
            )
        ids.add(neighbor_id)
        if neighbor_id not in bib_keys:
            problems.append(
                problem(
                    "novelty-unknown-neighbor",
                    path,
                    None,
                    f"neighbor {neighbor_id!r} 不在 manuscript/references.bib 中",
                )
            )
        for field in ("title", "venue", "overlap", "difference"):
            if not is_nonempty_str(neighbor.get(field)):
                problems.append(
                    problem(
                        "novelty-invalid",
                        path,
                        None,
                        f"{neighbor_id}: {field} 必须是非空字符串",
                    )
                )
        title = neighbor.get("title")
        if is_nonempty_str(title):
            normalised_title = _normalise_title(title)
            if normalised_title in titles:
                problems.append(
                    problem(
                        "novelty-duplicate-neighbor-title",
                        path,
                        None,
                        f"neighbor title 重复: {title.strip()}",
                    )
                )
            titles.add(normalised_title)
        for field in ("overlap", "difference"):
            text = neighbor.get(field)
            if is_nonempty_str(text):
                lowered = text.casefold()
                for phrase in BANNED_PHRASES:
                    if phrase.casefold() in lowered:
                        problems.append(
                            problem(
                                "novelty-unsupported-claim",
                                path,
                                None,
                                f"{neighbor_id}: {field} 含未支撑表述 {phrase!r}",
                            )
                        )
        claim_ids = neighbor.get("claim_ids")
        if (
            not isinstance(claim_ids, list)
            or not claim_ids
            or not all(is_nonempty_str(item) for item in claim_ids)
        ):
            problems.append(
                problem(
                    "novelty-invalid",
                    path,
                    None,
                    f"{neighbor_id}: claim_ids 必须是非空字符串数组",
                )
            )
        else:
            normalised_claim_ids = {item.strip() for item in claim_ids}
            for claim_id in sorted(normalised_claim_ids - set(claims)):
                problems.append(
                    problem(
                        "novelty-unknown-claim",
                        path,
                        None,
                        f"{neighbor_id}: claim_ids 引用了未声明的 {claim_id!r}",
                    )
                )
            covered.update(normalised_claim_ids)
    for claim in claims:
        if claim not in covered:
            problems.append(
                problem(
                    "novelty-uncovered-claim",
                    path,
                    None,
                    f"claim {claim!r} 没有任何最近邻差异记录",
                )
            )
    return problems


def _normalise_title(value: str) -> str:
    return " ".join(value.casefold().split())


def check(
    paper_root: Path,
    ledger: Path | None = None,
    bib: Path | None = None,
) -> tuple[list, list]:
    paper_root = Path(paper_root)
    path = Path(ledger) if ledger else paper_root / LEDGER_RELATIVE_PATH
    bib_path = (
        Path(bib)
        if bib
        else paper_root / "manuscript" / "references.bib"
    )
    payload, problems = load_ledger(path, code="novelty-ledger-missing")
    if payload is None:
        return problems, []
    missing = missing_fields(payload, TOP_FIELDS)
    if missing:
        return [
            problem(
                "novelty-invalid",
                path,
                None,
                f"novelty 台账缺少字段: {', '.join(missing)}",
            )
        ], []
    problems.extend(_check_search(path, payload["search"]))
    claims_raw = payload.get("claims")
    if (
        not isinstance(claims_raw, list)
        or not claims_raw
        or not all(is_nonempty_str(item) for item in claims_raw)
    ):
        problems.append(
            problem(
                "novelty-invalid",
                path,
                None,
                "claims 必须是非空字符串数组",
            )
        )
        claims: list[str] = []
    else:
        claims = [item.strip() for item in claims_raw]
        if len(claims) != len(set(claims)):
            problems.append(
                problem(
                    "novelty-duplicate-claim",
                    path,
                    None,
                    "claims 不能包含重复项",
                )
            )
    bib_keys = set(load_records(bib_path).records)
    problems.extend(
        _check_neighbors(path, payload["neighbors"], claims, bib_keys)
    )
    return problems, []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="检查新颖性审计：检索范围、最近邻、逐 claim 差异"
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--ledger")
    parser.add_argument("--bib")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.paper_root),
            Path(args.ledger) if args.ledger else None,
            Path(args.bib) if args.bib else None,
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
