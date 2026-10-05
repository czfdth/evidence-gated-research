"""Materialize and validate an ARIS-style proof run directory."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import yaml

from ccfa.cli import Problem, emit, tool_error


RUN_FILES = (
    "task.md",
    "materials.md",
    "local-proof.md",
    "source-manifest.md",
    "codex-ledger.md",
    "audit.md",
    "final.md",
    "next.md",
)
VALID_STATUSES = {
    "LOCAL_ATTEMPT",
    "LOCAL_PROVED",
    "LOCAL_BLOCKED",
    "READY_FOR_DEEPSEEK_REVIEW",
    "DEEPSEEK_REVIEW_BLOCKED",
    "ASK_USER",
    "READY_FOR_MANUAL_GPT_PRO",
    "WAITING_FOR_USER_GPT_PRO_OUTPUT",
    "READY_FOR_CODEX_DISPATCH",
    "WAITING_FOR_GPT_PRO_OUTPUT",
    "NEEDS_GPT_PRO_REDO",
    "AUDIT_FAILED",
    "READY_FOR_USER",
}


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _campaign(paper_root: Path, campaign_id: str) -> dict:
    payload = _load_yaml(paper_root / "data" / "proof-campaign.yaml")
    campaigns = payload.get("campaigns")
    if not isinstance(campaigns, list):
        raise ValueError("proof-campaign 台账缺少 campaigns")
    for campaign in campaigns:
        if isinstance(campaign, dict) and campaign.get("id") == campaign_id:
            return campaign
    raise ValueError(f"找不到 proof campaign: {campaign_id!r}")


def _resolve_run_dir(paper_root: Path, run_dir: Path) -> Path:
    resolved = run_dir if run_dir.is_absolute() else paper_root / run_dir
    resolved = resolved.resolve()
    try:
        resolved.relative_to(paper_root.resolve())
    except ValueError as exc:
        raise ValueError(f"run directory 必须位于 paper root 内: {resolved}") from exc
    return resolved


def _attempts_text(campaign: dict) -> str:
    attempts = campaign.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return "- No attempts recorded."
    lines = []
    for item in attempts:
        if isinstance(item, dict):
            lines.append(
                f"- {item.get('id', '?')}: {item.get('strategy', '')} "
                f"[{item.get('status', '')}] {item.get('result', '')}"
            )
    return "\n".join(lines)


def materialize_run(
    paper_root: Path,
    run_dir: Path,
    *,
    campaign_id: str,
    force: bool = False,
) -> dict:
    """Create one append-only proof run directory from a campaign."""
    paper_root = Path(paper_root).resolve()
    campaign = _campaign(paper_root, campaign_id)
    resolved = _resolve_run_dir(paper_root, Path(run_dir))
    if resolved.exists():
        if not force:
            raise ValueError(f"proof run 目录已存在，拒绝覆盖: {resolved}")
        shutil.rmtree(resolved)
    (resolved / "sources").mkdir(parents=True)
    status = "LOCAL_ATTEMPT"
    theorem_id = campaign.get("theorem_id", "Not specified")
    claim_id = campaign.get("claim_id", "Not specified")
    next_action = "Attempt the local proof and write local-proof.md."
    task = f"""# Proof Task

- campaign: `{campaign_id}`
- claim: `{claim_id}`
- theorem: `{theorem_id}`
- status: `{status}`

Freeze the target before changing any assumptions or conclusion.
"""
    materials = """# Materials

Include definitions, givens, notation, and source excerpts here.
"""
    local_proof = """# Local Proof

Not attempted yet.
"""
    source_manifest = """# Source Manifest

| Local path | Browser-visible name | Why needed | Upload status |
| --- | --- | --- | --- |
| none | none | No source snapshot prepared yet | missing |
"""
    ledger = f"""# Codex Ledger

- status: {status}
- campaign: {campaign_id}
- theorem: {theorem_id}

## Attempts

{_attempts_text(campaign)}
"""
    audit = """# Proof Audit

Core semantic objects retained: 0/0 (0%)
Undefined symbols: 0
Symbol collisions: 0
One-use definitions: 0/0 (0%)
Maximum parallel representations of one object: 0
Maximum alias-chain depth: 0
Maximum active nonstandard symbols in one proof step: 0
Top-down derivation structure: NOT_APPLICABLE

## Correctness

Draft gap: local correctness audit not performed.
"""
    final = """# Final Proof

Draft gap: not ready for user.
"""
    next_md = f"""# Next Obligation

{next_action}
"""
    for name, content in (
        ("task.md", task),
        ("materials.md", materials),
        ("local-proof.md", local_proof),
        ("source-manifest.md", source_manifest),
        ("codex-ledger.md", ledger),
        ("audit.md", audit),
        ("final.md", final),
        ("next.md", next_md),
    ):
        (resolved / name).write_text(content, encoding="utf-8")
    return {
        "run_dir": str(resolved),
        "campaign_id": campaign_id,
        "status": status,
        "files": list(RUN_FILES),
    }


def _ledger_status(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^\s*-\s*status:\s*([A-Z_]+)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else None


def check_run(
    run_dir: Path,
    *,
    notation_required: bool = False,
    require_closed: bool = False,
) -> tuple[list[Problem], list[Problem]]:
    run_dir = Path(run_dir)
    problems: list[Problem] = []
    if not run_dir.is_dir():
        return [
            Problem("proof-run-missing", str(run_dir), None, "proof run 目录不存在")
        ], []
    for name in RUN_FILES:
        path = run_dir / name
        if not path.is_file():
            problems.append(
                Problem("proof-run-missing-file", str(path), None, f"缺少 {name}")
            )
        elif path.stat().st_size <= 10:
            problems.append(
                Problem("proof-run-empty-file", str(path), None, f"{name} 过短")
            )
    status = _ledger_status(run_dir / "codex-ledger.md")
    if status not in VALID_STATUSES:
        problems.append(
            Problem(
                "proof-run-invalid-status",
                str(run_dir / "codex-ledger.md"),
                None,
                f"status 非法: {status!r}",
            )
        )
    if require_closed:
        if status != "READY_FOR_USER":
            problems.append(
                Problem(
                    "proof-run-not-closed",
                    str(run_dir / "codex-ledger.md"),
                    None,
                    f"proof run 仍为 {status!r}",
                )
            )
        final = run_dir / "final.md"
        if final.is_file() and "Draft gap" in final.read_text(
            encoding="utf-8",
            errors="replace",
        ):
            problems.append(
                Problem(
                    "proof-run-final-draft",
                    str(final),
                    None,
                    "final.md 仍是 draft",
                )
            )
    audit = run_dir / "audit.md"
    if notation_required:
        try:
            text = audit.read_text(encoding="utf-8")
        except OSError:
            text = ""
        retention = re.search(
            r"Core semantic objects retained:\s*(\d+)/(\d+)\s*\((\d+)%\)",
            text,
        )
        undefined = re.search(r"Undefined symbols:\s*(\d+)", text)
        collisions = re.search(r"Symbol collisions:\s*(\d+)", text)
        if retention is None:
            problems.append(
                Problem(
                    "proof-run-notation-missing",
                    str(audit),
                    None,
                    "缺少 notation scorecard",
                )
            )
        elif (
            retention.group(1) != retention.group(2)
            or retention.group(3) != "100"
        ):
            problems.append(
                Problem(
                    "proof-run-notation-retention",
                    str(audit),
                    None,
                    "core semantic objects retained 必须为 100%",
                )
            )
        if undefined is not None and int(undefined.group(1)) != 0:
            problems.append(
                Problem(
                    "proof-run-undefined-symbols",
                    str(audit),
                    None,
                    "undefined symbols 必须为 0",
                )
            )
        if collisions is not None and int(collisions.group(1)) != 0:
            problems.append(
                Problem(
                    "proof-run-symbol-collisions",
                    str(audit),
                    None,
                    "symbol collisions 必须为 0",
                )
            )
    derivation = re.search(
        r"Top-down derivation structure:\s*(PASS|FAIL|NOT_APPLICABLE)",
        audit.read_text(encoding="utf-8", errors="replace")
        if audit.is_file()
        else "",
    )
    if require_closed and (derivation is None or derivation.group(1) != "PASS"):
        problems.append(
            Problem(
                "proof-run-derivation-gate",
                str(audit),
                None,
                "Top-down derivation structure 必须为 PASS",
            )
        )
    return problems, []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ARIS 风格 proof run directory")
    sub = parser.add_subparsers(dest="command", required=True)
    materialize = sub.add_parser("materialize")
    materialize.add_argument("--paper-root", required=True)
    materialize.add_argument("--out", required=True)
    materialize.add_argument("--campaign", required=True)
    materialize.add_argument("--force", action="store_true")
    check = sub.add_parser("check")
    check.add_argument("--run-dir", required=True)
    check.add_argument("--notation-required", action="store_true")
    check.add_argument("--require-closed", action="store_true")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        if args.command == "materialize":
            result = materialize_run(
                Path(args.paper_root),
                Path(args.out),
                campaign_id=args.campaign,
                force=args.force,
            )
            import json

            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        problems, advisories = check_run(
            Path(args.run_dir),
            notation_required=args.notation_required,
            require_closed=args.require_closed,
        )
        return emit(problems, advisories)
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
