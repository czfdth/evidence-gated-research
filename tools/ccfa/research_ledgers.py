"""Validate machine-readable research-loop ledgers.

This is a structural and cross-reference gate. It does not judge whether a
claim is true; it makes the research graph explicit and rejects dangling links.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from ccfa.bib import load_records
from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import is_iso_date, is_nonempty_str, missing_fields, problem

CLAIM_REGISTRY = Path("data/claim-registry.yaml")
ASSUMPTIONS_LIMITATIONS = Path("data/assumptions-limitations.yaml")
VENUE_CHECKLIST = Path("data/venue-checklist.yaml")
ARTIFACT_PROVENANCE = Path("data/artifact-provenance.yaml")
EXPLORATION_GRAPH = Path("data/exploration-graph.yaml")
COST_LEDGER = Path("data/cost-ledger.yaml")
RISK_REGISTER = Path("data/risk-register.yaml")
HELD_OUT_PLAN = Path("data/held-out-plan.yaml")

CLAIM_FIELDS = (
    "id",
    "statement",
    "type",
    "status",
    "assumptions",
    "limitations",
    "proof",
    "experiments",
    "figures",
    "citations",
)
CLAIM_TYPES = {"theoretical", "empirical", "descriptive"}
# What the claim asserts, not what it is about: "effect" claims a difference,
# "null" claims the absence of one, "descriptive" only characterises (counts,
# taxonomy). A supported effect/null claim is the one a reader can over-read,
# so those have to say which they are; a count does not.
CLAIM_POLARITIES = {"effect", "null", "descriptive"}
# Purely descriptive claims are exempt: "43 of the works do X" asserts no
# direction, so demanding one would be a schema tax rather than a check.
POLARITY_REQUIRED_TYPES = {"theoretical", "empirical"}
CLAIM_STATUSES = {
    "pending-human-review",
    "supported",
    "provisional",
    "dropped",
}
ASSUMPTION_FIELDS = (
    "id",
    "claim_ids",
    "statement",
    "violation_impact",
)
LIMITATION_FIELDS = (
    "id",
    "claim_ids",
    "statement",
    "discussed_in",
)
VENUE_ITEM_FIELDS = ("id", "requirement", "status", "evidence", "owner")
VENUE_STATUSES = {"complete", "pending", "not-applicable", "blocked"}
ARTIFACT_FIELDS = ("id", "path", "decided_by", "source")
DECIDED_BY = {"human", "model", "mixed"}
DEPENDENCY_FIELDS = ("artifact_id", "authority", "evidence")
DEPENDENCY_AUTHORITIES = {"advisory", "verified"}
EXPLORATION_FIELDS = ("id", "kind", "summary", "claim_ids", "run_ids")
EXPLORATION_KINDS = {"pivot", "dead-end", "rejected", "active"}
COST_ENTRY_FIELDS = ("kind", "amount", "unit")
RISK_FIELDS = (
    "id",
    "description",
    "severity",
    "mitigation",
    "evidence",
    "status",
)
RISK_SEVERITIES = {"low", "medium", "high"}
RISK_STATUSES = {"open", "mitigated", "accepted"}
PLACEHOLDER = re.compile(
    r"(?<![a-z0-9])(pending|tbd|todo|placeholder|"
    r"to[ -]be[ -]determined)(?![a-z0-9])",
    re.IGNORECASE,
)


def _load(path: Path, code: str) -> tuple[dict | None, list[Problem]]:
    if not path.is_file():
        return None, []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return None, [problem(code, path, None, f"无法读取台账: {exc}")]
    if not isinstance(payload, dict):
        return None, [problem(code, path, None, "台账顶层必须是映射")]
    if type(payload.get("version")) is not int or payload.get("version") != 1:
        return None, [problem(code, path, None, "台账 version 必须是 1")]
    return payload, []


def _string_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and all(is_nonempty_str(item) for item in value)
    )


def _placeholder(value: object) -> bool:
    return (
        isinstance(value, str)
        and PLACEHOLDER.search(" ".join(value.casefold().split())) is not None
    )


def _exists_inside(paper_root: Path, relative: object) -> bool:
    if not is_nonempty_str(relative):
        return False
    candidate = (paper_root / str(relative)).resolve()
    try:
        candidate.relative_to(paper_root.resolve())
    except ValueError:
        return False
    return candidate.is_file()


def _proof_ids(paper_root: Path) -> set[str]:
    payload, _problems = _load(
        paper_root / "data" / "proof-audit.yaml",
        "proof-audit-invalid",
    )
    if payload is None:
        return set()
    reviews = payload.get("reviews")
    if not isinstance(reviews, list):
        return set()
    return {
        item["id"]
        for item in reviews
        if isinstance(item, dict) and is_nonempty_str(item.get("id"))
    }


def _figure_ids(paper_root: Path) -> set[str]:
    path = paper_root / "figures" / "manifest.yaml"
    if not path.is_file():
        return set()
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return set()
    entries = payload.get("figures") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return set()
    ids: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        value = item.get("name") or item.get("id")
        if is_nonempty_str(value):
            ids.add(value.strip())
    return ids


def _citation_ids(paper_root: Path) -> set[str]:
    path = paper_root / "manuscript" / "references.bib"
    if not path.is_file():
        return set()
    try:
        return set(load_records(path).records)
    except ValueError:
        return set()


def _run_ids(paper_root: Path) -> set[str]:
    log_dir = paper_root / "experiments" / "log"
    if not log_dir.is_dir():
        return set()
    ids: set[str] = set()
    for path in log_dir.glob("*.json"):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(payload, dict) and is_nonempty_str(payload.get("run_id")):
            ids.add(payload["run_id"].strip())
    return ids


# Runs that rule out the obvious confound behind an effect claim.
CONTROL_ROLES = {"negative-control", "ablation"}
KNOWN_RUN_ROLES = CONTROL_ROLES | {"treatment", "baseline"}
# A held-out evaluation is only held out if it was frozen before anyone looked
# at it and the number of looks is bounded, so both facts are part of the
# record rather than of the author's memory.
HELD_OUT_ROLES = {"held-out", "development"}
_MIN_NO_HELD_OUT_REASON = 40


def _run_roles(paper_root: Path) -> dict[str, str]:
    """Map run id -> declared role, ignoring records without a valid one.

    An unreadable or role-less record simply has no role: the claim rule that
    needs a control must fail closed, not treat a missing role as a control.
    """

    log_dir = paper_root / "experiments" / "log"
    if not log_dir.is_dir():
        return {}
    roles: dict[str, str] = {}
    for path in log_dir.glob("*.json"):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(payload, dict):
            continue
        run_id = payload.get("run_id")
        role = payload.get("role")
        if (
            is_nonempty_str(run_id)
            and isinstance(role, str)
            and role in KNOWN_RUN_ROLES
        ):
            roles[run_id.strip()] = role
    return roles


def _held_out_plan(
    paper_root: Path,
    payload: dict | None,
    run_ids: set[str],
) -> tuple[list[Problem], str | None, set[str]]:
    """Validate ``data/held-out-plan.yaml``.

    Returns the problems, the "no held-out evaluation exists" reason when the
    paper documents one, and the set of run ids that count as held-out
    evaluations (a recorded access to a frozen, budgeted split).
    """

    if payload is None:
        return [], None, set()
    path = paper_root / HELD_OUT_PLAN
    problems: list[Problem] = []
    reason = payload.get("no_held_out_reason")
    documented: str | None = None
    if reason is not None:
        if (
            not isinstance(reason, str)
            or len(reason.strip()) < _MIN_NO_HELD_OUT_REASON
            or _placeholder(reason)
        ):
            problems.append(
                problem(
                    "held-out-invalid",
                    path,
                    None,
                    f"no_held_out_reason 必须是至少 {_MIN_NO_HELD_OUT_REASON} 字的"
                    "具体说明，且不能是 placeholder",
                )
            )
        else:
            documented = reason.strip()

    splits = payload.get("splits", [])
    if not isinstance(splits, list):
        problems.append(problem("held-out-invalid", path, None, "splits 必须是数组"))
        return problems, documented, set()
    seen_ids: set[str] = set()
    touched: set[str] = set()
    for index, split in enumerate(splits):
        if not isinstance(split, dict):
            problems.append(
                problem(
                    "held-out-invalid",
                    path,
                    None,
                    f"splits[{index}] 必须是映射",
                )
            )
            continue
        split_id = split.get("id")
        if not is_nonempty_str(split_id):
            problems.append(
                problem(
                    "held-out-invalid",
                    path,
                    None,
                    f"splits[{index}].id 必须是非空字符串",
                )
            )
            continue
        split_id = split_id.strip()
        if split_id in seen_ids:
            problems.append(
                problem("held-out-invalid", path, None, f"split id 重复: {split_id}")
            )
        seen_ids.add(split_id)

        role = split.get("role")
        if role not in HELD_OUT_ROLES:
            problems.append(
                problem(
                    "held-out-invalid",
                    path,
                    None,
                    f"{split_id}: role 非法（应为 "
                    f"{' / '.join(sorted(HELD_OUT_ROLES))}）",
                )
            )
        artifact = split.get("artifact")
        if not is_nonempty_str(artifact):
            problems.append(
                problem(
                    "held-out-invalid",
                    path,
                    None,
                    f"{split_id}: artifact 必须是非空字符串",
                )
            )
        elif "://" not in artifact and not (paper_root / artifact.strip()).exists():
            problems.append(
                problem(
                    "held-out-artifact-missing",
                    path,
                    None,
                    f"{split_id}: artifact 不存在: {artifact}",
                )
            )

        frozen_at = split.get("frozen_at")
        budget = split.get("access_budget")
        if role == "held-out":
            if not is_iso_date(frozen_at):
                problems.append(
                    problem(
                        "held-out-invalid",
                        path,
                        None,
                        f"{split_id}: held-out split 必须写 frozen_at（YYYY-MM-DD）",
                    )
                )
            if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
                problems.append(
                    problem(
                        "held-out-invalid",
                        path,
                        None,
                        f"{split_id}: held-out split 的 access_budget 必须是正整数",
                    )
                )

        accesses = split.get("accesses", [])
        if not isinstance(accesses, list):
            problems.append(
                problem(
                    "held-out-invalid",
                    path,
                    None,
                    f"{split_id}: accesses 必须是数组",
                )
            )
            continue
        for access_index, access in enumerate(accesses):
            where = f"{split_id}.accesses[{access_index}]"
            if not isinstance(access, dict):
                problems.append(
                    problem("held-out-invalid", path, None, f"{where} 必须是映射")
                )
                continue
            run_id = access.get("run_id")
            at = access.get("at")
            why = access.get("reason")
            valid_run = is_nonempty_str(run_id)
            if not valid_run:
                problems.append(
                    problem(
                        "held-out-invalid",
                        path,
                        None,
                        f"{where}.run_id 必须是非空字符串",
                    )
                )
            elif run_id.strip() not in run_ids:
                problems.append(
                    problem(
                        "held-out-unknown-run",
                        path,
                        None,
                        f"{where}: run_id {run_id!r} 不在 experiments/log 里，"
                        "访问记录必须能追到一次真实运行",
                    )
                )
            if not is_iso_date(at):
                problems.append(
                    problem(
                        "held-out-invalid",
                        path,
                        None,
                        f"{where}.at 必须是 YYYY-MM-DD",
                    )
                )
            if not is_nonempty_str(why) or _placeholder(why):
                problems.append(
                    problem(
                        "held-out-invalid",
                        path,
                        None,
                        f"{where}.reason 必填且不能是 placeholder",
                    )
                )
            if (
                role == "held-out"
                and is_iso_date(at)
                and is_iso_date(frozen_at)
                and date.fromisoformat(at) < date.fromisoformat(frozen_at)
            ):
                problems.append(
                    problem(
                        "held-out-access-before-freeze",
                        path,
                        None,
                        f"{where}: 访问发生在冻结日 {frozen_at} 之前，"
                        "那次评估不能再算 held-out",
                    )
                )
            if role == "held-out" and valid_run:
                touched.add(run_id.strip())

        if (
            role == "held-out"
            and isinstance(budget, int)
            and not isinstance(budget, bool)
            and budget > 0
            and len(accesses) > budget
        ):
            problems.append(
                problem(
                    "held-out-budget-exceeded",
                    path,
                    None,
                    f"{split_id}: 已记录 {len(accesses)} 次访问，"
                    f"超过 access_budget={budget}",
                )
            )
    return problems, documented, touched


def _claim_registry(
    paper_root: Path,
    payload: dict,
    *,
    assumption_ids: set[str],
    limitation_ids: set[str],
    proof_ids: set[str],
    figure_ids: set[str],
    citation_ids: set[str],
    run_ids: set[str],
    run_roles: dict[str, str],
    held_out_runs: set[str],
    no_held_out_reason: str | None,
) -> tuple[list[Problem], set[str]]:
    path = paper_root / CLAIM_REGISTRY
    problems: list[Problem] = []
    claims = payload.get("claims")
    if not isinstance(claims, list):
        return [problem("claim-registry-invalid", path, None, "claims 必须是数组")], set()
    if not claims:
        return [], set()
    ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            problems.append(
                problem("claim-registry-invalid", path, None, f"claims[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(claim, CLAIM_FIELDS)
        if missing:
            problems.append(
                problem(
                    "claim-registry-invalid",
                    path,
                    None,
                    f"claims[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        claim_id = claim.get("id")
        if not is_nonempty_str(claim_id):
            problems.append(
                problem("claim-registry-invalid", path, None, f"claims[{index}].id 必须是非空字符串")
            )
            continue
        claim_id = claim_id.strip()
        if claim_id in ids:
            problems.append(
                problem("claim-registry-duplicate", path, None, f"claim id 重复: {claim_id}")
            )
        ids.add(claim_id)
        if not is_nonempty_str(claim.get("statement")):
            problems.append(
                problem("claim-registry-invalid", path, None, f"{claim_id}: statement 必须是非空字符串")
            )
        claim_type = claim.get("type")
        if claim_type not in CLAIM_TYPES:
            problems.append(
                problem("claim-registry-invalid", path, None, f"{claim_id}: type 非法")
            )
        status = claim.get("status")
        if status not in CLAIM_STATUSES:
            problems.append(
                problem("claim-registry-invalid", path, None, f"{claim_id}: status 非法")
            )
        polarity = claim.get("polarity")
        if polarity is not None and polarity not in CLAIM_POLARITIES:
            problems.append(
                problem(
                    "claim-registry-invalid",
                    path,
                    None,
                    f"{claim_id}: polarity 非法（应为 "
                    f"{'、'.join(sorted(CLAIM_POLARITIES))} 之一）",
                )
            )
            polarity = None
        if (
            status == "supported"
            and claim_type in POLARITY_REQUIRED_TYPES
            and polarity is None
        ):
            problems.append(
                problem(
                    "claim-registry-polarity-missing",
                    path,
                    None,
                    f"{claim_id}: supported 的 {claim_type} claim 必须声明 polarity"
                    "（effect/null/descriptive）——不写清方向，就没有人能判断"
                    "证据是否真的支撑它",
                )
            )
        for field in ("assumptions", "limitations", "experiments", "figures", "citations"):
            if not _string_list(claim.get(field)):
                problems.append(
                    problem("claim-registry-invalid", path, None, f"{claim_id}: {field} 必须是字符串数组")
                )
        proof = claim.get("proof")
        if proof is not None and not is_nonempty_str(proof):
            problems.append(
                problem("claim-registry-invalid", path, None, f"{claim_id}: proof 必须是字符串或 null")
            )
        for assumption in claim.get("assumptions", []) if isinstance(claim.get("assumptions"), list) else []:
            if not isinstance(assumption, str):
                continue
            if assumption not in assumption_ids:
                problems.append(
                    problem("claim-registry-unknown-assumption", path, None, f"{claim_id}: assumption {assumption!r} 不存在")
                )
        for limitation in claim.get("limitations", []) if isinstance(claim.get("limitations"), list) else []:
            if not isinstance(limitation, str):
                continue
            if limitation not in limitation_ids:
                problems.append(
                    problem("claim-registry-unknown-limitation", path, None, f"{claim_id}: limitation {limitation!r} 不存在")
                )
        for experiment in claim.get("experiments", []) if isinstance(claim.get("experiments"), list) else []:
            if not isinstance(experiment, str):
                continue
            if experiment not in run_ids:
                problems.append(
                    problem("claim-registry-unknown-experiment", path, None, f"{claim_id}: experiment {experiment!r} 不存在")
                )
        for figure in claim.get("figures", []) if isinstance(claim.get("figures"), list) else []:
            if not isinstance(figure, str):
                continue
            if figure not in figure_ids:
                problems.append(
                    problem("claim-registry-unknown-figure", path, None, f"{claim_id}: figure {figure!r} 不存在")
                )
        for citation in claim.get("citations", []) if isinstance(claim.get("citations"), list) else []:
            if not isinstance(citation, str):
                continue
            if citation not in citation_ids:
                problems.append(
                    problem("claim-registry-unknown-citation", path, None, f"{claim_id}: citation {citation!r} 不存在")
                )
        if proof is not None and proof not in proof_ids:
            problems.append(
                problem("claim-registry-unknown-proof", path, None, f"{claim_id}: proof {proof!r} 不存在")
            )
        if status == "supported" and not any(
            (
                proof is not None,
                bool(claim.get("experiments")) if isinstance(claim.get("experiments"), list) else False,
                bool(claim.get("figures")) if isinstance(claim.get("figures"), list) else False,
                bool(claim.get("citations")) if isinstance(claim.get("citations"), list) else False,
            )
        ):
            problems.append(
                problem("claim-registry-unsupported", path, None, f"{claim_id}: supported claim 至少需要 proof/experiment/figure/citation 之一")
            )
        if status == "supported" and claim_type == "theoretical" and proof is None:
            problems.append(
                problem(
                    "claim-registry-theoretical-proof-missing",
                    path,
                    None,
                    f"{claim_id}: supported theoretical claim 必须绑定 proof",
                )
            )
        if (
            status == "supported"
            and claim_type == "empirical"
            and (
                not isinstance(claim.get("experiments"), list)
                or not claim.get("experiments")
            )
        ):
            problems.append(
                problem(
                    "claim-registry-empirical-experiment-missing",
                    path,
                    None,
                    f"{claim_id}: supported empirical claim 必须绑定 experiment",
                )
            )
        if (
            status == "supported"
            and polarity == "null"
            and not (
                isinstance(claim.get("experiments"), list)
                and claim.get("experiments")
            )
        ):
            problems.append(
                problem(
                    "claim-registry-null-experiment-missing",
                    path,
                    None,
                    f"{claim_id}: polarity=null 的 supported claim 必须绑定 experiment；"
                    "「没有差异」只能由真的对照实验支撑，citation/figure 不算",
                )
            )
        referenced = (
            claim.get("experiments")
            if isinstance(claim.get("experiments"), list)
            else []
        )
        if (
            status == "supported"
            and claim_type == "empirical"
            and polarity == "effect"
            and not any(
                run_roles.get(run) in CONTROL_ROLES
                for run in referenced
                if isinstance(run, str)
            )
        ):
            problems.append(
                problem(
                    "claim-registry-control-run-missing",
                    path,
                    None,
                    f"{claim_id}: supported 的 effect 实证 claim 必须引用至少一个"
                    " role=negative-control 或 ablation 的运行；只有 treatment"
                    " 结果时，无法排除混淆因素",
                )
            )
        if (
            status == "supported"
            and claim_type == "empirical"
            and polarity == "effect"
            and no_held_out_reason is None
            and not any(
                isinstance(run, str) and run in held_out_runs
                for run in referenced
            )
        ):
            problems.append(
                problem(
                    "claim-registry-held-out-missing",
                    path,
                    None,
                    f"{claim_id}: supported 的 effect 实证 claim 必须引用一次"
                    " held-out 评估（data/held-out-plan.yaml 里 role=held-out、"
                    "冻结在前且计入 access_budget 的运行）；这篇论文确实没有 "
                    "held-out 划分时，就在同一个文件里写 no_held_out_reason"
                    f"（至少 {_MIN_NO_HELD_OUT_REASON} 字）说明原因",
                )
            )
    return problems, ids


def _assumptions_limitations(
    paper_root: Path,
    payload: dict,
    claim_ids: set[str] | None,
) -> tuple[list[Problem], set[str], set[str]]:
    path = paper_root / ASSUMPTIONS_LIMITATIONS
    problems: list[Problem] = []
    assumptions = payload.get("assumptions")
    limitations = payload.get("limitations")
    if not isinstance(assumptions, list):
        problems.append(problem("assumptions-limitations-invalid", path, None, "assumptions 必须是数组"))
        assumptions = []
    if not isinstance(limitations, list):
        problems.append(problem("assumptions-limitations-invalid", path, None, "limitations 必须是数组"))
        limitations = []
    assumption_ids: set[str] = set()
    limitation_ids: set[str] = set()
    seen: set[str] = set()
    for prefix, entries, fields, ids in (
        ("assumptions", assumptions, ASSUMPTION_FIELDS, assumption_ids),
        ("limitations", limitations, LIMITATION_FIELDS, limitation_ids),
    ):
        for index, item in enumerate(entries):
            if not isinstance(item, dict):
                problems.append(problem("assumptions-limitations-invalid", path, None, f"{prefix}[{index}] 必须是映射"))
                continue
            missing = missing_fields(item, fields)
            if missing:
                problems.append(problem("assumptions-limitations-invalid", path, None, f"{prefix}[{index}] 缺少字段: {', '.join(missing)}"))
                continue
            item_id = item.get("id")
            if not is_nonempty_str(item_id):
                problems.append(problem("assumptions-limitations-invalid", path, None, f"{prefix}[{index}].id 必须是非空字符串"))
                continue
            item_id = item_id.strip()
            marker = f"{prefix}:{item_id}"
            if marker in seen:
                problems.append(problem("assumptions-limitations-duplicate", path, None, f"{prefix} id 重复: {item_id}"))
            seen.add(marker)
            ids.add(item_id)
            if not _string_list(item.get("claim_ids")) or not item["claim_ids"]:
                problems.append(problem("assumptions-limitations-invalid", path, None, f"{item_id}: claim_ids 必须是非空字符串数组"))
            elif claim_ids is not None:
                for claim_id in item["claim_ids"]:
                    if not isinstance(claim_id, str):
                        continue
                    if claim_id not in claim_ids:
                        problems.append(problem("assumptions-limitations-unknown-claim", path, None, f"{item_id}: claim {claim_id!r} 不存在"))
            if prefix == "assumptions":
                if not is_nonempty_str(item.get("statement")):
                    problems.append(problem("assumptions-limitations-invalid", path, None, f"{item_id}: statement 必须是非空字符串"))
                if not is_nonempty_str(item.get("violation_impact")):
                    problems.append(problem("assumptions-limitations-invalid", path, None, f"{item_id}: violation_impact 必须是非空字符串"))
            else:
                if not is_nonempty_str(item.get("statement")):
                    problems.append(problem("assumptions-limitations-invalid", path, None, f"{item_id}: statement 必须是非空字符串"))
                if not _exists_inside(paper_root, item.get("discussed_in")):
                    problems.append(problem("assumptions-limitations-invalid", path, None, f"{item_id}: discussed_in 文件不存在"))
    return problems, assumption_ids, limitation_ids


def _declared_ids(payload: dict | None, field: str) -> set[str]:
    if payload is None:
        return set()
    entries = payload.get(field)
    if not isinstance(entries, list):
        return set()
    return {
        item["id"].strip()
        for item in entries
        if isinstance(item, dict)
        and is_nonempty_str(item.get("id"))
    }


def _link_map(payload: dict | None, field: str) -> dict[str, set[str]]:
    if payload is None:
        return {}
    entries = payload.get(field)
    if not isinstance(entries, list):
        return {}
    result: dict[str, set[str]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        claim_ids = item.get("claim_ids")
        if (
            is_nonempty_str(item_id)
            and isinstance(claim_ids, list)
            and all(isinstance(claim_id, str) for claim_id in claim_ids)
        ):
            result[item_id.strip()] = set(claim_ids)
    return result


def _asymmetric_links(
    paper_root: Path,
    claim_payload: dict | None,
    assumption_payload: dict | None,
) -> list[Problem]:
    if claim_payload is None or assumption_payload is None:
        return []
    claims = claim_payload.get("claims")
    if not isinstance(claims, list):
        return []
    assumption_links = _link_map(assumption_payload, "assumptions")
    limitation_links = _link_map(assumption_payload, "limitations")
    problems: list[Problem] = []
    path = paper_root / CLAIM_REGISTRY
    claims_by_id = {
        claim["id"].strip(): claim
        for claim in claims
        if isinstance(claim, dict) and is_nonempty_str(claim.get("id"))
    }
    for claim in claims:
        if not isinstance(claim, dict) or not is_nonempty_str(claim.get("id")):
            continue
        claim_id = claim["id"].strip()
        for field, links, code in (
            ("assumptions", assumption_links, "claim-registry-asymmetric-assumption"),
            ("limitations", limitation_links, "claim-registry-asymmetric-limitation"),
        ):
            declared = claim.get(field)
            if not isinstance(declared, list):
                continue
            for item_id in declared:
                if not isinstance(item_id, str):
                    continue
                linked_claims = links.get(item_id, set())
                if claim_id not in linked_claims:
                    problems.append(
                        problem(
                            code,
                            path,
                            None,
                            f"{claim_id}: {field[:-1]} {item_id!r} 没有反向 claim 链接",
                        )
                    )
    for field, links, code in (
        ("assumptions", assumption_links, "claim-registry-asymmetric-assumption"),
        ("limitations", limitation_links, "claim-registry-asymmetric-limitation"),
    ):
        for item_id, linked_claims in links.items():
            for claim_id in linked_claims:
                claim = claims_by_id.get(claim_id)
                if claim is None:
                    continue
                declared = claim.get(field)
                if not isinstance(declared, list) or item_id not in declared:
                    problems.append(
                        problem(
                            code,
                            path,
                            None,
                            f"{claim_id}: {field[:-1]} {item_id!r} 没有在 claim 中反向声明",
                        )
                    )
    return problems


def _venue_checklist(paper_root: Path, payload: dict) -> list[Problem]:
    path = paper_root / VENUE_CHECKLIST
    items = payload.get("items")
    if isinstance(items, list) and not items:
        return []
    problems: list[Problem] = []
    for field in ("venue", "source"):
        if not is_nonempty_str(payload.get(field)):
            problems.append(problem("venue-checklist-invalid", path, None, f"{field} 必须是非空字符串"))
    if not isinstance(items, list) or not items:
        return problems + [problem("venue-checklist-invalid", path, None, "items 必须是非空数组")]
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(problem("venue-checklist-invalid", path, None, f"items[{index}] 必须是映射"))
            continue
        missing = missing_fields(item, VENUE_ITEM_FIELDS)
        if missing:
            problems.append(problem("venue-checklist-invalid", path, None, f"items[{index}] 缺少字段: {', '.join(missing)}"))
            continue
        item_id = item.get("id")
        if not is_nonempty_str(item_id):
            problems.append(problem("venue-checklist-invalid", path, None, f"items[{index}].id 必须是非空字符串"))
            continue
        if item_id in seen:
            problems.append(problem("venue-checklist-duplicate", path, None, f"checklist id 重复: {item_id}"))
        seen.add(item_id)
        status = item.get("status")
        if not isinstance(status, str) or status not in VENUE_STATUSES:
            problems.append(problem("venue-checklist-invalid", path, None, f"{item_id}: status 非法"))
        if not is_nonempty_str(item.get("requirement")):
            problems.append(problem("venue-checklist-invalid", path, None, f"{item_id}: requirement 必须是非空字符串"))
        if not is_nonempty_str(item.get("owner")):
            problems.append(problem("venue-checklist-invalid", path, None, f"{item_id}: owner 必须是非空字符串"))
        if status == "complete":
            evidence = item.get("evidence")
            if not _string_list(evidence) or not evidence:
                problems.append(problem("venue-checklist-evidence-missing", path, None, f"{item_id}: complete item 必须有 evidence"))
            else:
                for relpath in evidence:
                    if not _exists_inside(paper_root, relpath):
                        problems.append(problem("venue-checklist-evidence-missing", path, None, f"{item_id}: evidence 不存在: {relpath}"))
    return problems


def _artifact_provenance(paper_root: Path, payload: dict) -> list[Problem]:
    path = paper_root / ARTIFACT_PROVENANCE
    problems: list[Problem] = []
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, list) and not artifacts:
        return []
    if not isinstance(artifacts, list):
        return [problem("artifact-provenance-invalid", path, None, "artifacts 必须是数组")]
    seen: set[str] = set()
    dependency_records: list[tuple[str, object]] = []
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            problems.append(problem("artifact-provenance-invalid", path, None, f"artifacts[{index}] 必须是映射"))
            continue
        missing = missing_fields(item, ARTIFACT_FIELDS)
        if missing:
            problems.append(problem("artifact-provenance-invalid", path, None, f"artifacts[{index}] 缺少字段: {', '.join(missing)}"))
            continue
        artifact_id = item.get("id")
        if not is_nonempty_str(artifact_id):
            problems.append(problem("artifact-provenance-invalid", path, None, f"artifacts[{index}].id 必须是非空字符串"))
            continue
        if artifact_id in seen:
            problems.append(problem("artifact-provenance-duplicate", path, None, f"artifact id 重复: {artifact_id}"))
        seen.add(artifact_id)
        decided_by = item.get("decided_by")
        if not isinstance(decided_by, str) or decided_by not in DECIDED_BY:
            problems.append(problem("artifact-provenance-invalid", path, None, f"{artifact_id}: decided_by 非法"))
        if not _exists_inside(paper_root, item.get("path")):
            problems.append(problem("artifact-provenance-path-missing", path, None, f"{artifact_id}: path 不存在"))
        if not is_nonempty_str(item.get("source")):
            problems.append(problem("artifact-provenance-source-missing", path, None, f"{artifact_id}: source 必须是非空字符串"))
        if decided_by in {"model", "mixed"} and not is_nonempty_str(item.get("model_family")):
            problems.append(problem("artifact-provenance-model-family-missing", path, None, f"{artifact_id}: model/mixed artifact 需要 model_family"))
        if decided_by in {"model", "mixed"} and not (
            is_nonempty_str(item.get("run_id"))
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(item.get("source_sha256", "")))
        ):
            problems.append(
                problem(
                    "artifact-provenance-binding-missing",
                    path,
                    None,
                    f"{artifact_id}: model/mixed artifact 需要 run_id 或 source_sha256",
                )
            )
        dependency_records.append((artifact_id, item.get("depends_on")))

    graph: dict[str, list[str]] = {}
    for artifact_id, depends_on in dependency_records:
        dependency_ids: list[str] = []
        if depends_on is None:
            graph[artifact_id] = dependency_ids
            continue
        if not isinstance(depends_on, list):
            problems.append(
                problem(
                    "artifact-provenance-dependency-invalid",
                    path,
                    None,
                    f"{artifact_id}: depends_on 必须是数组",
                )
            )
            graph[artifact_id] = dependency_ids
            continue
        for index, dependency in enumerate(depends_on):
            if not isinstance(dependency, dict):
                problems.append(
                    problem(
                        "artifact-provenance-dependency-invalid",
                        path,
                        None,
                        f"{artifact_id}: depends_on[{index}] 必须是映射",
                    )
                )
                continue
            missing_dependency = missing_fields(dependency, DEPENDENCY_FIELDS)
            if missing_dependency:
                problems.append(
                    problem(
                        "artifact-provenance-dependency-invalid",
                        path,
                        None,
                        (
                            f"{artifact_id}: depends_on[{index}] 缺少字段: "
                            f"{', '.join(missing_dependency)}"
                        ),
                    )
                )
                continue
            target = dependency.get("artifact_id")
            authority = dependency.get("authority")
            evidence = dependency.get("evidence")
            if not is_nonempty_str(target):
                problems.append(
                    problem(
                        "artifact-provenance-dependency-invalid",
                        path,
                        None,
                        f"{artifact_id}: depends_on[{index}].artifact_id 必须是非空字符串",
                    )
                )
                continue
            if target not in seen:
                problems.append(
                    problem(
                        "artifact-provenance-dependency-missing",
                        path,
                        None,
                        f"{artifact_id}: 依赖不存在的 artifact: {target}",
                    )
                )
            else:
                dependency_ids.append(target)
            if authority not in DEPENDENCY_AUTHORITIES:
                problems.append(
                    problem(
                        "artifact-provenance-dependency-invalid",
                        path,
                        None,
                        f"{artifact_id}: 非法 dependency authority: {authority!r}",
                    )
                )
            if not is_nonempty_str(evidence):
                problems.append(
                    problem(
                        "artifact-provenance-dependency-evidence-missing",
                        path,
                        None,
                        f"{artifact_id}: dependency 需要非空 evidence",
                    )
                )
            elif authority == "verified" and not _exists_inside(paper_root, evidence):
                problems.append(
                    problem(
                        "artifact-provenance-dependency-evidence-missing",
                        path,
                        None,
                        (
                            f"{artifact_id}: verified dependency 的 evidence "
                            f"不存在: {evidence}"
                        ),
                    )
                )
        graph[artifact_id] = dependency_ids

    for cycle in _dependency_cycles(graph):
        problems.append(
            problem(
                "artifact-provenance-dependency-cycle",
                path,
                None,
                "artifact dependency cycle: " + " -> ".join(cycle),
            )
        )
    return problems


def _dependency_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Return one representative node list for each dependency cycle."""
    cycles: list[list[str]] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            start = visiting.index(node)
            cycle = [*visiting[start:], node]
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if node in visited:
            return
        visiting.append(node)
        for target in graph.get(node, []):
            visit(target)
        visiting.pop()
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return cycles


def _exploration_graph(
    paper_root: Path,
    payload: dict,
    claim_ids: set[str],
    run_ids: set[str],
) -> list[Problem]:
    path = paper_root / EXPLORATION_GRAPH
    problems: list[Problem] = []
    entries = payload.get("entries")
    if isinstance(entries, list) and not entries:
        return []
    if not isinstance(entries, list):
        return [problem("exploration-graph-invalid", path, None, "entries 必须是数组")]
    seen: set[str] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(problem("exploration-graph-invalid", path, None, f"entries[{index}] 必须是映射"))
            continue
        missing = missing_fields(item, EXPLORATION_FIELDS)
        if missing:
            problems.append(problem("exploration-graph-invalid", path, None, f"entries[{index}] 缺少字段: {', '.join(missing)}"))
            continue
        item_id = item.get("id")
        if not is_nonempty_str(item_id):
            problems.append(problem("exploration-graph-invalid", path, None, f"entries[{index}].id 必须是非空字符串"))
            continue
        if item_id in seen:
            problems.append(problem("exploration-graph-duplicate", path, None, f"entry id 重复: {item_id}"))
        seen.add(item_id)
        kind = item.get("kind")
        if not isinstance(kind, str) or kind not in EXPLORATION_KINDS:
            problems.append(problem("exploration-graph-invalid", path, None, f"{item_id}: kind 非法"))
        if not is_nonempty_str(item.get("summary")):
            problems.append(problem("exploration-graph-invalid", path, None, f"{item_id}: summary 必须是非空字符串"))
        bound_claims = item.get("claim_ids")
        bound_runs = item.get("run_ids")
        if not _string_list(bound_claims) or not bound_claims:
            problems.append(problem("exploration-graph-invalid", path, None, f"{item_id}: claim_ids 必须是非空字符串数组"))
        else:
            for claim_id in bound_claims:
                if claim_id not in claim_ids:
                    problems.append(problem("exploration-unknown-claim", path, None, f"{item_id}: claim {claim_id!r} 不存在"))
        if not _string_list(bound_runs) or not bound_runs:
            problems.append(problem("exploration-graph-invalid", path, None, f"{item_id}: run_ids 必须是非空字符串数组"))
        else:
            for run_id in bound_runs:
                if run_id not in run_ids:
                    problems.append(problem("exploration-unknown-run", path, None, f"{item_id}: run {run_id!r} 不存在"))
        if kind in {"dead-end", "rejected", "pivot"} and not is_nonempty_str(item.get("rationale")):
            problems.append(problem("exploration-rationale-missing", path, None, f"{item_id}: {kind} 需要 rationale"))
    return problems


def _cost_ledger(paper_root: Path, payload: dict) -> list[Problem]:
    path = paper_root / COST_LEDGER
    entries = payload.get("entries")
    if isinstance(entries, list) and not entries:
        return []
    problems: list[Problem] = []
    for field in ("currency", "paper"):
        if not is_nonempty_str(payload.get(field)):
            problems.append(problem("cost-ledger-invalid", path, None, f"{field} 必须是非空字符串"))
    if not isinstance(entries, list):
        return problems + [problem("cost-ledger-invalid", path, None, "entries 必须是数组")]
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            problems.append(problem("cost-ledger-invalid", path, None, f"entries[{index}] 必须是映射"))
            continue
        missing = missing_fields(item, COST_ENTRY_FIELDS)
        if missing:
            problems.append(problem("cost-ledger-invalid", path, None, f"entries[{index}] 缺少字段: {', '.join(missing)}"))
            continue
        if not is_nonempty_str(item.get("kind")) or not is_nonempty_str(item.get("unit")):
            problems.append(problem("cost-ledger-invalid", path, None, f"entries[{index}] kind/unit 必须是非空字符串"))
        amount = item.get("amount")
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or amount < 0
        ):
            problems.append(problem("cost-ledger-invalid-amount", path, None, f"entries[{index}].amount 必须是有限非负数"))
    return problems


def _risk_register(paper_root: Path, payload: dict) -> list[Problem]:
    path = paper_root / RISK_REGISTER
    problems: list[Problem] = []
    risks = payload.get("risks")
    if isinstance(risks, list) and not risks:
        return []
    if not isinstance(risks, list):
        return [problem("risk-register-invalid", path, None, "risks 必须是数组")]
    seen: set[str] = set()
    for index, item in enumerate(risks):
        if not isinstance(item, dict):
            problems.append(problem("risk-register-invalid", path, None, f"risks[{index}] 必须是映射"))
            continue
        missing = missing_fields(item, RISK_FIELDS)
        if missing:
            problems.append(problem("risk-register-invalid", path, None, f"risks[{index}] 缺少字段: {', '.join(missing)}"))
            continue
        risk_id = item.get("id")
        if not is_nonempty_str(risk_id):
            problems.append(problem("risk-register-invalid", path, None, f"risks[{index}].id 必须是非空字符串"))
            continue
        if risk_id in seen:
            problems.append(problem("risk-register-duplicate", path, None, f"risk id 重复: {risk_id}"))
        seen.add(risk_id)
        severity = item.get("severity")
        status = item.get("status")
        if not isinstance(severity, str) or severity not in RISK_SEVERITIES:
            problems.append(problem("risk-register-invalid", path, None, f"{risk_id}: severity 非法"))
        if not isinstance(status, str) or status not in RISK_STATUSES:
            problems.append(problem("risk-register-invalid", path, None, f"{risk_id}: status 非法"))
        for field in ("description", "mitigation"):
            if not is_nonempty_str(item.get(field)):
                problems.append(problem("risk-register-invalid", path, None, f"{risk_id}: {field} 必须是非空字符串"))
            elif _placeholder(item.get(field)):
                problems.append(problem("risk-register-placeholder", path, None, f"{risk_id}: {field} 仍是 placeholder"))
        evidence = item.get("evidence")
        if not _string_list(evidence) or not evidence:
            problems.append(problem("risk-register-invalid", path, None, f"{risk_id}: evidence 必须是非空字符串数组"))
        elif any(_placeholder(value) for value in evidence):
            problems.append(problem("risk-register-placeholder", path, None, f"{risk_id}: evidence 仍是 placeholder"))
    return problems


def check(
    paper_root: Path,
    *,
    require_core: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    problems: list[Problem] = []
    advisories: list[Problem] = []

    claim_payload, claim_errors = _load(paper_root / CLAIM_REGISTRY, "claim-registry-invalid")
    assumption_payload, assumption_errors = _load(
        paper_root / ASSUMPTIONS_LIMITATIONS,
        "assumptions-limitations-invalid",
    )
    problems.extend(claim_errors)
    problems.extend(assumption_errors)
    ledger_paths = (
        (CLAIM_REGISTRY, "缺少 claim registry"),
        (ASSUMPTIONS_LIMITATIONS, "缺少 assumptions/limitations 台账"),
        (VENUE_CHECKLIST, "缺少 venue checklist"),
        (ARTIFACT_PROVENANCE, "缺少 artifact provenance"),
        (EXPLORATION_GRAPH, "缺少 exploration graph"),
        (COST_LEDGER, "缺少 cost ledger"),
        (RISK_REGISTER, "缺少 risk register"),
    )
    if require_core:
        for relative, message in ledger_paths:
            if not (paper_root / relative).is_file():
                problems.append(
                    problem(
                        "research-ledger-missing",
                        paper_root / relative,
                        None,
                        message,
                    )
                )

    claim_ids: set[str] = set()
    assumption_ids = _declared_ids(assumption_payload, "assumptions")
    limitation_ids = _declared_ids(assumption_payload, "limitations")

    proof_ids = _proof_ids(paper_root)
    figure_ids = _figure_ids(paper_root)
    citation_ids = _citation_ids(paper_root)
    run_ids = _run_ids(paper_root)
    run_roles = _run_roles(paper_root)
    held_out_payload, held_out_errors = _load(
        paper_root / HELD_OUT_PLAN,
        "held-out-invalid",
    )
    problems.extend(held_out_errors)
    held_out_problems, no_held_out_reason, held_out_runs = _held_out_plan(
        paper_root,
        held_out_payload,
        run_ids,
    )
    problems.extend(held_out_problems)
    if claim_payload is not None:
        claim_problems, claim_ids = _claim_registry(
            paper_root,
            claim_payload,
            assumption_ids=assumption_ids,
            limitation_ids=limitation_ids,
            proof_ids=proof_ids,
            figure_ids=figure_ids,
            citation_ids=citation_ids,
            run_ids=run_ids,
            run_roles=run_roles,
            held_out_runs=held_out_runs,
            no_held_out_reason=no_held_out_reason,
        )
        problems.extend(claim_problems)

    if assumption_payload is not None:
        problems.extend(
            _assumptions_limitations(
                paper_root,
                assumption_payload,
                claim_ids,
            )[0]
        )
        problems.extend(
            _asymmetric_links(
                paper_root,
                claim_payload,
                assumption_payload,
            )
        )

    claims_policy_path = paper_root / "data" / "claims.yaml"
    if claim_payload is not None and claims_policy_path.is_file():
        try:
            policy = yaml.safe_load(claims_policy_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            policy = None
        if isinstance(policy, dict) and "claims" in policy:
            policy_claims = policy.get("claims")
            if not isinstance(policy_claims, list) or not all(
                isinstance(item, str) for item in policy_claims
            ):
                problems.append(
                    problem(
                        "claim-registry-policy-mismatch",
                        claims_policy_path,
                        None,
                        "claims.yaml 的 claims 必须是字符串数组",
                    )
                )
            elif set(policy_claims) != claim_ids:
                problems.append(
                    problem(
                        "claim-registry-policy-mismatch",
                        claims_policy_path,
                        None,
                        "claims.yaml 的 claim 列表与 claim-registry.yaml 不一致",
                    )
                )

    venue_payload, venue_errors = _load(paper_root / VENUE_CHECKLIST, "venue-checklist-invalid")
    problems.extend(venue_errors)
    if venue_payload is not None:
        problems.extend(_venue_checklist(paper_root, venue_payload))

    artifact_payload, artifact_errors = _load(
        paper_root / ARTIFACT_PROVENANCE,
        "artifact-provenance-invalid",
    )
    problems.extend(artifact_errors)
    if artifact_payload is not None:
        problems.extend(_artifact_provenance(paper_root, artifact_payload))

    graph_payload, graph_errors = _load(
        paper_root / EXPLORATION_GRAPH,
        "exploration-graph-invalid",
    )
    problems.extend(graph_errors)
    if graph_payload is not None:
        problems.extend(_exploration_graph(paper_root, graph_payload, claim_ids, run_ids))

    cost_payload, cost_errors = _load(paper_root / COST_LEDGER, "cost-ledger-invalid")
    problems.extend(cost_errors)
    if cost_payload is not None:
        problems.extend(_cost_ledger(paper_root, cost_payload))

    risk_payload, risk_errors = _load(paper_root / RISK_REGISTER, "risk-register-invalid")
    problems.extend(risk_errors)
    if risk_payload is not None:
        problems.extend(_risk_register(paper_root, risk_payload))

    configured = [
        relative
        for relative, _message in ledger_paths
        if (paper_root / relative).is_file()
    ]
    for relative in configured:
        payload, _errors = _load(paper_root / relative, "ledger-invalid")
        if payload is None:
            continue
        key = next(
            (
                field
                for field, value in (
                    ("claims", relative == CLAIM_REGISTRY),
                    ("assumptions", relative == ASSUMPTIONS_LIMITATIONS),
                    ("items", relative == VENUE_CHECKLIST),
                    ("artifacts", relative == ARTIFACT_PROVENANCE),
                    ("entries", relative == EXPLORATION_GRAPH),
                    ("entries", relative == COST_LEDGER),
                    ("risks", relative == RISK_REGISTER),
                )
                if value
            ),
            None,
        )
        values = payload.get(key) if key else None
        if isinstance(values, list) and not values:
            advisories.append(
                problem(
                    "research-ledger-empty",
                    paper_root / relative,
                    None,
                    "台账已创建但尚未填写",
                )
            )
    if not configured and not require_core:
        advisories.append(
            problem(
                "research-ledgers-not-configured",
                paper_root / "data",
                None,
                "尚未配置 claim registry 与研究循环台账",
            )
        )
    return problems, advisories


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="校验 claim 中心的研究循环台账")
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--require-core", action="store_true")
    args = parser.parse_args(argv[1:])
    try:
        problems, advisories = check(
            Path(args.paper_root),
            require_core=args.require_core,
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
