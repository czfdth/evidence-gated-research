"""Track long-running proof campaigns across attempts and sessions.

The orchestrator records what was tried, why it failed, what is blocked, and
what the next concrete action is. A campaign may only be marked ``proved``
when it points to a verified human review in ``proof-audit.yaml``; model
review alone cannot acquit a theorem.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import is_nonempty_str, load_ledger, missing_fields, problem


PROOF_CAMPAIGN = Path("data/proof-campaign.yaml")
PROOF_AUDIT = Path("data/proof-audit.yaml")
CLAIM_REGISTRY = Path("data/claim-registry.yaml")
RUN_LOG_DIR = Path("experiments/log")

CAMPAIGN_FIELDS = ("id", "claim_id", "theorem_id", "status", "attempts")
ATTEMPT_FIELDS = (
    "id",
    "strategy",
    "status",
    "result",
    "evidence",
    "failure_reason",
    "next_action",
)
PROOF_REVIEW_FIELDS = (
    "review_id",
    "reviewer",
    "reviewed_at",
    "method",
    "status",
)
CAMPAIGN_STATUSES = {"open", "blocked", "proved", "refuted", "abandoned"}
ATTEMPT_STATUSES = {"failed", "partial", "succeeded", "blocked"}
PROOF_METHODS = {
    "line-by-line",
    "independent-reproduction",
    "external-expert",
    "formal-proof",
}
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


def _string_list(value: object, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    return all(is_nonempty_str(item) for item in value)


def _valid_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _human_reviewer(value: object) -> bool:
    return (
        is_nonempty_str(value)
        and MODEL_REVIEWER.search(value) is None
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


def _proof_reviews(paper_root: Path) -> dict[str, dict]:
    path = paper_root / PROOF_AUDIT
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    reviews = payload.get("reviews") if isinstance(payload, dict) else None
    if not isinstance(reviews, list):
        return {}
    return {
        item["id"]: item
        for item in reviews
        if isinstance(item, dict) and is_nonempty_str(item.get("id"))
    }


def _evidence_known(
    paper_root: Path,
    value: object,
    *,
    run_ids: set[str],
) -> bool:
    if not is_nonempty_str(value):
        return False
    text = value.strip()
    if text in run_ids:
        return True
    candidate = (paper_root / text).resolve()
    try:
        candidate.relative_to(paper_root.resolve())
    except ValueError:
        return False
    return candidate.is_file()


def _load_campaign(
    paper_root: Path,
) -> tuple[dict | None, list[Problem], list[Problem]]:
    path = paper_root / PROOF_CAMPAIGN
    if not path.is_file():
        return None, [], [
            problem(
                "proof-campaign-not-configured",
                path,
                None,
                "尚未配置 proof campaign",
            )
        ]
    payload, problems = load_ledger(path, code="proof-campaign-invalid")
    return payload if isinstance(payload, dict) else None, problems, []


def _validate_attempt(
    paper_root: Path,
    attempt: object,
    *,
    campaign_id: str,
    run_ids: set[str],
    path: Path,
) -> list[Problem]:
    if not isinstance(attempt, dict):
        return [
            problem(
                "proof-campaign-invalid",
                path,
                None,
                f"{campaign_id}: attempt 必须是映射",
            )
        ]
    missing = missing_fields(attempt, ATTEMPT_FIELDS)
    if missing:
        return [
            problem(
                "proof-campaign-attempt-incomplete",
                path,
                None,
                f"{campaign_id}: attempt 缺少字段: {', '.join(missing)}",
            )
        ]
    attempt_id = attempt.get("id")
    problems: list[Problem] = []
    if not is_nonempty_str(attempt_id):
        problems.append(
            problem(
                "proof-campaign-invalid",
                path,
                None,
                f"{campaign_id}: attempt.id 必须是非空字符串",
            )
        )
        return problems
    for field in ("strategy", "result"):
        value = attempt.get(field)
        if not is_nonempty_str(value):
            problems.append(
                problem(
                    "proof-campaign-attempt-incomplete",
                    path,
                    None,
                    f"{campaign_id}/{attempt_id}: {field} 必须是非空字符串",
                )
            )
        elif _placeholder(value):
            problems.append(
                problem(
                    "proof-campaign-placeholder",
                    path,
                    None,
                    f"{campaign_id}/{attempt_id}: {field} 仍是 placeholder",
                )
            )
    status = attempt.get("status")
    if status not in ATTEMPT_STATUSES:
        problems.append(
            problem(
                "proof-campaign-invalid",
                path,
                None,
                f"{campaign_id}/{attempt_id}: attempt.status 非法",
            )
        )
    if status in {"failed", "blocked"}:
        reason = attempt.get("failure_reason")
        if not is_nonempty_str(reason):
            problems.append(
                problem(
                    "proof-campaign-attempt-incomplete",
                    path,
                    None,
                    f"{campaign_id}/{attempt_id}: failed/blocked attempt 需要 failure_reason",
                )
            )
        elif _placeholder(reason):
            problems.append(
                problem(
                    "proof-campaign-placeholder",
                    path,
                    None,
                    f"{campaign_id}/{attempt_id}: failure_reason 仍是 placeholder",
                )
            )
    evidence = attempt.get("evidence")
    if not _string_list(evidence):
        problems.append(
            problem(
                "proof-campaign-attempt-incomplete",
                path,
                None,
                f"{campaign_id}/{attempt_id}: evidence 必须是非空字符串数组",
            )
        )
    else:
        for value in evidence:
            if not _evidence_known(paper_root, value, run_ids=run_ids):
                problems.append(
                    problem(
                        "proof-campaign-unknown-run",
                        path,
                        None,
                        f"{campaign_id}/{attempt_id}: evidence 不是已有 run 或仓库内文件: {value!r}",
                    )
                )
    return problems


def _validate_proof_review(
    campaign: dict,
    *,
    campaign_id: str,
    proof_reviews: dict[str, dict],
    path: Path,
) -> list[Problem]:
    review = campaign.get("proof_review")
    if not isinstance(review, dict):
        return [
            problem(
                "proof-campaign-proof-not-verified",
                path,
                None,
                f"{campaign_id}: proved 需要 proof_review",
            )
        ]
    missing = missing_fields(review, PROOF_REVIEW_FIELDS)
    if missing:
        return [
            problem(
                "proof-campaign-proof-not-verified",
                path,
                None,
                f"{campaign_id}: proof_review 缺少字段: {', '.join(missing)}",
            )
        ]
    review_id = review.get("review_id")
    if review_id != campaign.get("theorem_id"):
        return [
            problem(
                "proof-campaign-proof-not-verified",
                path,
                None,
                f"{campaign_id}: proof_review.review_id 必须等于 theorem_id",
            )
        ]
    stored = proof_reviews.get(review_id)
    if not stored:
        return [
            problem(
                "proof-campaign-unknown-theorem",
                path,
                None,
                f"{campaign_id}: proof-audit 中没有 {review_id!r}",
            )
        ]
    problems: list[Problem] = []
    if review.get("status") != "verified" or stored.get("status") != "verified":
        problems.append(
            problem(
                "proof-campaign-proof-not-verified",
                path,
                None,
                f"{campaign_id}: proof_review 与 proof-audit 都必须是 verified",
            )
        )
    if not _human_reviewer(review.get("reviewer")) or not _human_reviewer(
        stored.get("reviewer")
    ):
        problems.append(
            problem(
                "proof-campaign-proof-not-human",
                path,
                None,
                f"{campaign_id}: proof_review 必须由真人 reviewer 完成",
            )
        )
    if not _valid_date(review.get("reviewed_at")) or not _valid_date(
        stored.get("reviewed_at")
    ):
        problems.append(
            problem(
                "proof-campaign-proof-not-verified",
                path,
                None,
                f"{campaign_id}: proof_review.reviewed_at 非法",
            )
        )
    if review.get("method") not in PROOF_METHODS:
        problems.append(
            problem(
                "proof-campaign-proof-not-verified",
                path,
                None,
                f"{campaign_id}: proof_review.method 非法",
            )
        )
    return problems


def _validate_campaign(
    paper_root: Path,
    campaign: object,
    *,
    claim_ids: set[str],
    run_ids: set[str],
    proof_reviews: dict[str, dict],
    path: Path,
) -> list[Problem]:
    if not isinstance(campaign, dict):
        return [
            problem(
                "proof-campaign-invalid",
                path,
                None,
                "campaign 必须是映射",
            )
        ]
    missing = missing_fields(campaign, CAMPAIGN_FIELDS)
    if missing:
        return [
            problem(
                "proof-campaign-invalid",
                path,
                None,
                f"campaign 缺少字段: {', '.join(missing)}",
            )
        ]
    campaign_id = campaign.get("id")
    if not is_nonempty_str(campaign_id):
        return [
            problem(
                "proof-campaign-invalid",
                path,
                None,
                "campaign.id 必须是非空字符串",
            )
        ]
    problems: list[Problem] = []
    claim_id = campaign.get("claim_id")
    if claim_id not in claim_ids:
        problems.append(
            problem(
                "proof-campaign-unknown-claim",
                path,
                None,
                f"{campaign_id}: claim {claim_id!r} 不存在",
            )
        )
    theorem_id = campaign.get("theorem_id")
    if theorem_id not in proof_reviews:
        problems.append(
            problem(
                "proof-campaign-unknown-theorem",
                path,
                None,
                f"{campaign_id}: theorem {theorem_id!r} 不在 proof-audit 中",
            )
        )
    status = campaign.get("status")
    if status not in CAMPAIGN_STATUSES:
        problems.append(
            problem(
                "proof-campaign-invalid",
                path,
                None,
                f"{campaign_id}: status 非法",
            )
        )
    attempts = campaign.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        problems.append(
            problem(
                "proof-campaign-attempt-incomplete",
                path,
                None,
                f"{campaign_id}: attempts 必须是非空数组",
            )
        )
        attempts = []
    attempt_ids: set[str] = set()
    last_attempt: dict | None = None
    for attempt in attempts:
        problems.extend(
            _validate_attempt(
                paper_root,
                attempt,
                campaign_id=campaign_id,
                run_ids=run_ids,
                path=path,
            )
        )
        if isinstance(attempt, dict):
            attempt_id = attempt.get("id")
            if is_nonempty_str(attempt_id):
                if attempt_id in attempt_ids:
                    problems.append(
                        problem(
                            "proof-campaign-duplicate",
                            path,
                            None,
                            f"{campaign_id}: attempt id 重复: {attempt_id}",
                        )
                    )
                attempt_ids.add(attempt_id)
                last_attempt = attempt
    if status in {"open", "blocked"}:
        next_action = (
            last_attempt.get("next_action")
            if isinstance(last_attempt, dict)
            else None
        )
        if not is_nonempty_str(next_action):
            problems.append(
                problem(
                    "proof-campaign-attempt-incomplete",
                    path,
                    None,
                    f"{campaign_id}: open/blocked campaign 需要 last attempt.next_action",
                )
            )
        elif _placeholder(next_action):
            problems.append(
                problem(
                    "proof-campaign-placeholder",
                    path,
                    None,
                    f"{campaign_id}: next_action 仍是 placeholder",
                )
            )
    if status == "proved":
        problems.extend(
            _validate_proof_review(
                campaign,
                campaign_id=campaign_id,
                proof_reviews=proof_reviews,
                path=path,
            )
        )
    if status == "refuted":
        counterexample = campaign.get("counterexample")
        if not _string_list(counterexample):
            problems.append(
                problem(
                    "proof-campaign-counterexample-missing",
                    path,
                    None,
                    f"{campaign_id}: refuted 需要非空 counterexample 证据",
                )
            )
        else:
            for value in counterexample:
                if not _evidence_known(paper_root, value, run_ids=run_ids):
                    problems.append(
                        problem(
                            "proof-campaign-unknown-run",
                            path,
                            None,
                            f"{campaign_id}: counterexample 不是已有 run 或仓库内文件: {value!r}",
                        )
                    )
    if status == "abandoned" and not is_nonempty_str(campaign.get("abandon_reason")):
        problems.append(
            problem(
                "proof-campaign-abandon-reason-missing",
                path,
                None,
                f"{campaign_id}: abandoned 需要 abandon_reason",
            )
        )
    return problems


def check(
    paper_root: Path,
    *,
    require_complete: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_campaign(paper_root)
    if payload is None:
        if require_complete:
            return [
                problem(
                    "proof-campaign-missing",
                    paper_root / PROOF_CAMPAIGN,
                    None,
                    "缺少 proof campaign 台账",
                )
            ], []
        return problems, advisories
    path = paper_root / PROOF_CAMPAIGN
    not_applicable = payload.get("not_applicable", False)
    if not isinstance(not_applicable, bool):
        return [
            problem(
                "proof-campaign-invalid",
                path,
                None,
                "not_applicable 必须是布尔值",
            )
        ], advisories
    if not_applicable:
        reason = payload.get("not_applicable_reason")
        if not is_nonempty_str(reason):
            problems.append(
                problem(
                    "proof-campaign-na-reason-missing",
                    path,
                    None,
                    "not_applicable=true 需要非空具体理由",
                )
            )
        return problems, advisories

    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list):
        return [
            problem(
                "proof-campaign-invalid",
                path,
                None,
                "campaigns 必须是数组",
            )
        ], advisories
    if not campaigns:
        if require_complete:
            problems.append(
                problem(
                    "proof-campaign-not-complete",
                    path,
                    None,
                    "campaigns 为空，不能作为 high-assurance 的证明战役记录",
                )
            )
        else:
            advisories.append(
                problem(
                    "proof-campaign-empty",
                    path,
                    None,
                    "台账已创建但尚未填写",
                )
            )
        return problems, advisories

    claim_ids = _claim_ids(paper_root)
    run_ids = _run_ids(paper_root)
    proof_reviews = _proof_reviews(paper_root)
    seen: set[str] = set()
    for campaign in campaigns:
        if isinstance(campaign, dict):
            campaign_id = campaign.get("id")
            if is_nonempty_str(campaign_id):
                if campaign_id in seen:
                    problems.append(
                        problem(
                            "proof-campaign-duplicate",
                            path,
                            None,
                            f"campaign id 重复: {campaign_id}",
                        )
                    )
                seen.add(campaign_id)
        problems.extend(
            _validate_campaign(
                paper_root,
                campaign,
                claim_ids=claim_ids,
                run_ids=run_ids,
                proof_reviews=proof_reviews,
                path=path,
            )
        )
        if require_complete and isinstance(campaign, dict):
            if campaign.get("status") in {"open", "blocked"}:
                problems.append(
                    problem(
                        "proof-campaign-not-complete",
                        path,
                        None,
                        f"{campaign.get('id')}: campaign 仍为 {campaign.get('status')}",
                    )
                )
    return problems, advisories


def next_actions(paper_root: Path) -> dict:
    """Return the next concrete action for each open or blocked campaign."""
    paper_root = Path(paper_root).resolve()
    payload, problems, advisories = _load_campaign(paper_root)
    if payload is None:
        detail = problems[0].message if problems else advisories[0].message
        raise ValueError(detail)
    checked, _checked_advisories = check(paper_root)
    if checked:
        first = checked[0]
        raise ValueError(
            f"proof-campaign 台账存在问题: {first.code}: {first.message}"
        )
    if payload.get("not_applicable") is True:
        return {
            "campaigns": [],
            "reason": payload.get("not_applicable_reason", ""),
        }
    actions = []
    for campaign in payload.get("campaigns", []):
        if not isinstance(campaign, dict):
            continue
        if campaign.get("status") not in {"open", "blocked"}:
            continue
        attempts = campaign.get("attempts")
        last = attempts[-1] if isinstance(attempts, list) and attempts else {}
        actions.append(
            {
                "id": campaign.get("id"),
                "status": campaign.get("status"),
                "action": (
                    last.get("next_action")
                    if isinstance(last, dict)
                    else "记录下一次证明尝试"
                ),
            }
        )
    return {"campaigns": actions}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="记录并校验跨会话 proof campaigns"
    )
    parser.add_argument(
        "action",
        choices=("check", "next"),
        nargs="?",
        default="check",
    )
    parser.add_argument("--paper-root", default=".")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="高风险论文要求所有 proof campaign 都有终态",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    paper_root = Path(args.paper_root)
    if args.action == "next":
        try:
            print(json.dumps(next_actions(paper_root), ensure_ascii=False))
        except (OSError, ValueError) as exc:
            return tool_error(str(exc))
        return 0
    try:
        problems, advisories = check(
            paper_root,
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
