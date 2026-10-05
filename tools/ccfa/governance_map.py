"""Validate risk/control/evidence mappings and machine-readable data flows."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


from ccfa.cli import Problem, emit, tool_error
from ccfa.ledger import is_nonempty_str, load_ledger, missing_fields, problem
from ccfa.friction_log import write_text_output


CAPABILITY_MATRIX = Path("data/capability-matrix.yaml")
RISK_REGISTER = Path("data/risk-register.yaml")
DATA_FLOWS = Path("data/data-flows.yaml")
CAPABILITY_STATUSES = {"DESIGNED", "NOT_RUN", "MEASURED", "MIXED"}
CAPABILITY_FIELDS = ("id", "stage", "control", "status", "evidence")
RISK_GOVERNANCE_FIELDS = ("controls", "evidence_status", "residual_gap")
NETWORK_FIELDS = (
    "id",
    "endpoint",
    "purpose",
    "sends",
    "credentials",
    "off_switch",
)
STORE_FIELDS = ("id", "path", "content", "lifetime", "delete")
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _load_optional(path: Path, code: str) -> tuple[dict | None, list[Problem]]:
    if not path.is_file():
        return None, []
    payload, problems = load_ledger(path, code=code)
    return payload if isinstance(payload, dict) else None, problems


def _string_list(value: object, *, allow_empty: bool = False) -> bool:
    if not isinstance(value, list):
        return False
    if not value and not allow_empty:
        return False
    return all(is_nonempty_str(item) for item in value)


def _plaintext_secret(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _capability_matrix(paper_root: Path) -> tuple[set[str], list[Problem], list[Problem]]:
    path = paper_root / CAPABILITY_MATRIX
    payload, problems = _load_optional(path, "governance-map-invalid")
    advisories: list[Problem] = []
    if payload is None:
        if not problems:
            advisories.append(
                problem(
                    "governance-map-capability-missing",
                    path,
                    None,
                    "尚未配置 capability matrix",
                )
            )
        return set(), problems, advisories
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        return set(), [
            problem("governance-map-invalid", path, None, "capabilities 必须是数组")
        ], advisories
    ids: set[str] = set()
    for index, item in enumerate(capabilities):
        if not isinstance(item, dict):
            problems.append(
                problem("governance-map-invalid", path, None, f"capabilities[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(item, CAPABILITY_FIELDS)
        if missing:
            problems.append(
                problem(
                    "governance-map-invalid",
                    path,
                    None,
                    f"capabilities[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        item_id = item.get("id")
        if not is_nonempty_str(item_id):
            problems.append(
                problem("governance-map-invalid", path, None, "capability id 必须是非空字符串")
            )
            continue
        if item_id in ids:
            problems.append(
                problem("governance-map-duplicate", path, None, f"capability id 重复: {item_id}")
            )
        ids.add(item_id)
        if item.get("status") not in CAPABILITY_STATUSES:
            problems.append(
                problem("governance-map-invalid", path, None, f"{item_id}: status 非法")
            )
        if not _string_list(item.get("evidence")):
            problems.append(
                problem("governance-map-invalid", path, None, f"{item_id}: evidence 必须是非空数组")
            )
    return ids, problems, advisories


def _risk_register(
    paper_root: Path,
    capability_ids: set[str],
) -> tuple[list[Problem], list[Problem]]:
    path = paper_root / RISK_REGISTER
    payload, problems = _load_optional(path, "governance-map-invalid")
    advisories: list[Problem] = []
    if payload is None:
        if not problems:
            advisories.append(
                problem(
                    "governance-map-risk-missing",
                    path,
                    None,
                    "尚未配置 risk register",
                )
            )
        return problems, advisories
    risks = payload.get("risks")
    if not isinstance(risks, list):
        return [
            problem("governance-map-invalid", path, None, "risks 必须是数组")
        ], advisories
    for index, item in enumerate(risks):
        if not isinstance(item, dict):
            problems.append(
                problem("governance-map-invalid", path, None, f"risks[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(item, RISK_GOVERNANCE_FIELDS)
        if capability_ids and missing:
            problems.append(
                problem(
                    "governance-map-risk-incomplete",
                    path,
                    None,
                    f"risks[{index}] 缺少字段: {', '.join(missing)}",
                )
            )
            continue
        controls = item.get("controls", [])
        if capability_ids and not _string_list(controls):
            problems.append(
                problem("governance-map-risk-incomplete", path, None, f"risks[{index}].controls 必须是非空数组")
            )
        else:
            for control in controls:
                if capability_ids and control not in capability_ids:
                    problems.append(
                        problem(
                            "governance-map-unknown-control",
                            path,
                            None,
                            f"risks[{index}] 引用了不存在的 control: {control!r}",
                        )
                    )
        evidence_status = item.get("evidence_status")
        if capability_ids and evidence_status not in CAPABILITY_STATUSES:
            problems.append(
                problem("governance-map-invalid", path, None, f"risks[{index}].evidence_status 非法")
            )
        if capability_ids and not is_nonempty_str(item.get("residual_gap")):
            problems.append(
                problem("governance-map-risk-incomplete", path, None, f"risks[{index}].residual_gap 不能为空")
            )
    return problems, advisories


def _data_flows(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    path = paper_root / DATA_FLOWS
    payload, problems = _load_optional(path, "governance-map-invalid")
    advisories: list[Problem] = []
    if payload is None:
        if not problems:
            advisories.append(
                problem(
                    "governance-map-data-flows-missing",
                    path,
                    None,
                    "尚未配置 data flows",
                )
            )
        return problems, advisories
    network = payload.get("network")
    stores = payload.get("stores")
    if not isinstance(network, list) or not isinstance(stores, list):
        return [
            problem("governance-map-invalid", path, None, "network/stores 必须是数组")
        ], advisories
    for index, item in enumerate(network):
        if not isinstance(item, dict):
            problems.append(
                problem("governance-map-invalid", path, None, f"network[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(item, NETWORK_FIELDS)
        if missing:
            problems.append(
                problem("governance-map-invalid", path, None, f"network[{index}] 缺少字段: {', '.join(missing)}")
            )
            continue
        for field in ("id", "endpoint", "purpose", "sends", "credentials", "off_switch"):
            value = item.get(field)
            if not is_nonempty_str(value):
                problems.append(
                    problem("governance-map-invalid", path, None, f"network[{index}].{field} 必须是非空字符串")
                )
        if _plaintext_secret(item.get("credentials")):
            problems.append(
                problem(
                    "governance-map-plaintext-credential",
                    path,
                    None,
                    f"network[{index}].credentials 含明文凭据形状",
                )
            )
    for index, item in enumerate(stores):
        if not isinstance(item, dict):
            problems.append(
                problem("governance-map-invalid", path, None, f"stores[{index}] 必须是映射")
            )
            continue
        missing = missing_fields(item, STORE_FIELDS)
        if missing:
            problems.append(
                problem("governance-map-invalid", path, None, f"stores[{index}] 缺少字段: {', '.join(missing)}")
            )
            continue
        for field in STORE_FIELDS:
            if not is_nonempty_str(item.get(field)):
                problems.append(
                    problem("governance-map-invalid", path, None, f"stores[{index}].{field} 必须是非空字符串")
                )
    return problems, advisories


def check(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    paper_root = Path(paper_root).resolve()
    capability_ids, capability_problems, capability_advisories = _capability_matrix(paper_root)
    risk_problems, risk_advisories = _risk_register(paper_root, capability_ids)
    flow_problems, flow_advisories = _data_flows(paper_root)
    return (
        [*capability_problems, *risk_problems, *flow_problems],
        [*capability_advisories, *risk_advisories, *flow_advisories],
    )


def render_data_flows(payload: dict) -> str:
    lines = [
        "# Data Flows",
        "",
        "This file is generated from `data/data-flows.yaml`.",
        "",
        "## Network Touchpoints",
        "",
        "| id | endpoint | purpose | sends | credentials | off switch |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in payload.get("network", []):
        if isinstance(item, dict):
            lines.append(
                "| "
                + " | ".join(
                    str(item.get(field, "")).replace("|", "\\|")
                    for field in NETWORK_FIELDS
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Local Stores",
            "",
            "| id | path | content | lifetime | delete |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("stores", []):
        if isinstance(item, dict):
            lines.append(
                "| "
                + " | ".join(
                    str(item.get(field, "")).replace("|", "\\|")
                    for field in STORE_FIELDS
                )
                + " |"
            )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="校验 governance map 与 data flows")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--paper-root", required=True)
    render = sub.add_parser("render")
    render.add_argument("--paper-root", required=True)
    render.add_argument("--out", required=True)
    render.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        paper_root = Path(args.paper_root)
        if args.command == "check":
            problems, advisories = check(paper_root)
            return emit(problems, advisories)
        payload, problems = _load_optional(
            paper_root / DATA_FLOWS,
            "governance-map-invalid",
        )
        if payload is None:
            raise ValueError(problems[0].message if problems else "缺少 data-flows.yaml")
        write_text_output(
            Path(args.out),
            render_data_flows(payload),
            force=args.force,
        )
        return 0
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
