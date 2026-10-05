"""Build a one-page readiness report for a paper project.

This report is deliberately conservative. It summarizes state, evidence,
environment and repository posture, but it never infers that a scientific
claim is correct just because deterministic files are present.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from ccfa import (
    argument_audit,
    artifact_badge,
    artifact_store,
    citation_guard,
    cross_review,
    experiment_loop,
    final_check,
    formal_check,
    governance_map,
    governance,
    latex_check,
    novelty,
    passport_ledger,
    post_submission,
    proof_orchestrator,
    repro_package,
    repro_env,
    research_ledgers,
    resubmit_pipeline,
    review_loop,
    run_ledger,
    rigor,
    stats_plan,
    talk_pipeline,
    trace_claims,
)
from ccfa.cli import Problem, ToolEnvironmentError, save_text_atomically, tool_error
from ccfa.milestones import due_report, stage_report
from ccfa.stages import gate_for
from ccfa.texscan import iter_tex_files
from ccfa.validate import validate_yaml

PROFILES = ("minimal", "standard", "high-assurance")
DEFAULT_PROFILE = "standard"

# ARIS (the open-source workflow Modex-MH-Agent is built on) splits depth from
# audit strictness: ``effort`` says how much work to do, ``assurance`` says
# whether the audits are load-bearing. Conflating them let ``effort: beast``
# skip every submission audit whenever a content detector said "not applicable".
# We keep ``profile`` as the effort axis and add assurance on top of it.
ASSURANCE_LEVELS = ("draft", "submission")

EVIDENCE_LEDGER_PATHS = {
    "claim-registry": Path("data/claim-registry.yaml"),
    "assumptions-limitations": Path("data/assumptions-limitations.yaml"),
    "venue-checklist": Path("data/venue-checklist.yaml"),
    "artifact-provenance": Path("data/artifact-provenance.yaml"),
    "exploration-graph": Path("data/exploration-graph.yaml"),
    "cost-ledger": Path("data/cost-ledger.yaml"),
    "risk-register": Path("data/risk-register.yaml"),
    "experiment-loop": Path("data/experiment-loop.yaml"),
    "proof": Path("data/proof-audit.yaml"),
    "citation-support": Path("data/citation-support.yaml"),
    "figure-support": Path("data/figure-support.yaml"),
    "governance": Path("data/governance.yaml"),
    "novelty": Path("data/novelty-audit.yaml"),
    "statistics": Path("data/statistics-plan.yaml"),
    "repro-environment": Path("data/repro-environment.yaml"),
    "human-coding": Path("data/human-coding-report.json"),
    "post-submission": Path("data/post-submission.yaml"),
    "rigor-rubric": Path("data/rigor-rubric.yaml"),
    "proof-orchestrator": Path("data/proof-campaign.yaml"),
    "artifact-badge": Path("data/artifact-badge.yaml"),
    "formal-checks": Path("data/formal-checks.yaml"),
}

PROFILE_REQUIRED_LEDGERS = {
    "minimal": ("novelty",),
    "standard": (
        "claim-registry",
        "assumptions-limitations",
        "venue-checklist",
        "artifact-provenance",
        "exploration-graph",
        "cost-ledger",
        "risk-register",
        "experiment-loop",
        "rigor-rubric",
        "proof-orchestrator",
        "citation-support",
        "figure-support",
        "novelty",
        "statistics",
        "repro-environment",
    ),
    "high-assurance": tuple(EVIDENCE_LEDGER_PATHS),
}

PENDING_REVIEW_STATUSES = {
    "pending",
    "pending-human-review",
    "pending-human-dual-coding",
    "not-started",
    "not_started",
}

LEDGER_GATE_NAMES = {
    "proof": "argument-audit",
    "citation-support": "argument-audit",
    "figure-support": "argument-audit",
    "governance": "governance",
    "novelty": "novelty",
    "statistics": "statistics",
    "repro-environment": "repro-environment",
    "human-coding": "human-coding",
    "experiment-loop": "experiment-loop",
    "rigor-rubric": "rigor-rubric",
    "proof-orchestrator": "proof-orchestrator",
    "artifact-badge": "artifact-badge",
}

# A guard is only trustworthy once it has been seen to reject something. With
# ~25 gates it is easy to accumulate guards that have never fired, and a guard
# that cannot fail is indistinguishable from one that is not wired up. The
# drill ledger records, per gate, how it was deliberately broken and where the
# failing output lives; gates without one are reported as ``unproven-guard``.
GATE_DRILLS_RELATIVE_PATH = Path("data") / "gate-failure-drills.yaml"

# Human review is the one dimension no script can decide. Each pending ledger
# is therefore expanded into a checkpoint record, following the shape used by
# Modex-MH-Agent's ``checkpoints`` table: the question being asked, the payload
# the human is shown, and where the answer has to be written. ``pending`` stays
# as a plain key list so existing consumers keep working.
HUMAN_CHECKPOINT_SPECS = {
    "proof": {
        "type": "approve",
        "stage": "internal-review",
        "question": "主证明逐行成立吗？每一步推理与所依赖的假设是否都站得住？",
        "answer_with": "写 reviewer、结论与复核证据路径",
    },
    "citation-support": {
        "type": "approve",
        "stage": "writing",
        "question": "关键引用是否真的支撑它所在的那句论断，而不只是存在？",
        "answer_with": "逐条写 supports 与判定依据",
    },
    "figure-support": {
        "type": "approve",
        "stage": "writing",
        "question": "每张图和表是否真的展示了正文声称的效应？",
        "answer_with": "逐图写 figure 与判定依据",
    },
    "human-coding": {
        "type": "feedback",
        "stage": "results-ready",
        "question": "第二位人类编码者完成盲法编码了吗？一致率达到预设门槛了吗？",
        "answer_with": "写 coders、agreement、kappa 与分歧裁决",
    },
    "cross-review": {
        "type": "approve",
        "stage": "internal-review",
        "question": (
            "是否有真实跨族、gate-capable 的独立评审，"
            "且确定性 gate 不再否决模型 pass？"
        ),
        "answer_with": (
            "配置可验证的跨族 provider 后重跑评审，"
            "或完成外部人类评审并写 reviewer、结论与证据"
        ),
    },
}


@dataclass(frozen=True)
class GitSummary:
    present: bool
    dirty: bool | None
    commit: str | None
    remotes: list[str]
    workflows_present: bool
    error: str | None = None


def _load_state(paper_root: Path) -> dict:
    path = paper_root / "ccfa.yaml"
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"无法读取 {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 顶层必须是映射")
    return payload


def _profile(state: dict, override: str | None) -> str:
    if override:
        value = override
    else:
        workflow = state.get("workflow")
        value = workflow.get("profile") if isinstance(workflow, dict) else None
        if value is None:
            value = DEFAULT_PROFILE
    if value not in PROFILES:
        raise ValueError(
            f"未知 readiness profile: {value!r}，应为 {', '.join(PROFILES)}"
        )
    return value


def _assurance(state: dict) -> str | None:
    """Read the optional audit-strictness axis; unknown values fail closed."""

    workflow = state.get("workflow")
    if not isinstance(workflow, dict):
        return None
    value = workflow.get("assurance")
    if value is None:
        return None
    if not isinstance(value, str) or value not in ASSURANCE_LEVELS:
        raise ValueError(
            f"未知 assurance: {value!r}，应为 {', '.join(ASSURANCE_LEVELS)}"
        )
    return value


def _default_assurance(profile: str) -> str:
    return "submission" if profile == "high-assurance" else "draft"


def _audit_profile(profile: str, assurance: str | None) -> str:
    """Return the profile whose audit chain applies.

    ``submission`` raises the audit chain to high-assurance regardless of how
    much work the run does; ``draft`` is the explicit escape hatch for a
    high-assurance-labelled project whose audits are advisory for now.
    """

    if assurance == "submission":
        return "high-assurance"
    if assurance == "draft" and profile == "high-assurance":
        return "standard"
    return profile


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        shell=False,
        check=False,
    )


def _git_summary(paper_root: Path) -> GitSummary:
    inside = _git(["rev-parse", "--is-inside-work-tree"], paper_root)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitSummary(False, None, None, [], False, "not a git worktree")
    commit = _git(["rev-parse", "--short", "HEAD"], paper_root)
    status = _git(["status", "--porcelain"], paper_root)
    remotes = _git(["remote"], paper_root)
    workflows_present = (paper_root / ".github" / "workflows").is_dir()
    records = [
        line
        for line in status.stdout.splitlines()
        if line.strip() and not _is_generated_readiness_record(line)
    ]
    return GitSummary(
        True,
        bool(records) if status.returncode == 0 else None,
        commit.stdout.strip() if commit.returncode == 0 else None,
        [line for line in remotes.stdout.splitlines() if line.strip()]
        if remotes.returncode == 0
        else [],
        workflows_present,
        None,
    )


def _is_generated_readiness_record(line: str) -> bool:
    """Ignore the report files this command writes into ``reviews/``."""
    path = line[3:].strip().strip('"').replace("\\", "/")
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.startswith("reviews/readiness") and path.endswith(
        (".json", ".md", ".err.txt")
    )


def _ledger_status(paper_root: Path, profile: str) -> dict:
    required = set(PROFILE_REQUIRED_LEDGERS[profile])
    ledgers = {}
    missing_required = []
    for key, relative in EVIDENCE_LEDGER_PATHS.items():
        exists = (paper_root / relative).is_file()
        ledgers[key] = {
            "path": relative.as_posix(),
            "present": exists,
            "required": key in required,
        }
        if key in required and not exists:
            missing_required.append(key)
    return {"items": ledgers, "missing_required": sorted(missing_required)}


def _problem_dict(problem: Problem) -> dict:
    return {
        "code": problem.code,
        "path": problem.path,
        "line": problem.line,
        "message": problem.message,
    }


def _gate_result(
    name: str,
    problems: list[Problem],
    advisories: list[Problem] | None = None,
) -> dict:
    advisories = advisories or []
    return {
        "name": name,
        "status": "problem" if problems else "pass",
        "problem_count": len(problems),
        "advisory_count": len(advisories),
        "problems": [_problem_dict(problem) for problem in problems],
        "advisories": [_problem_dict(problem) for problem in advisories],
    }


def _run_gate(name: str, runner) -> dict:
    try:
        outcome = runner()
    except ToolEnvironmentError as exc:
        return _gate_result(
            name,
            [Problem("gate-environment-error", name, None, str(exc))],
        )
    except (OSError, ValueError) as exc:
        return _gate_result(
            name,
            [Problem("gate-error", name, None, str(exc))],
        )
    if isinstance(outcome, list):
        problems, advisories = outcome, []
    else:
        problems, advisories = outcome
    return _gate_result(name, list(problems), list(advisories))


def _schema_gate(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    path = paper_root / "ccfa.yaml"
    problems = [
        Problem("schema-invalid", str(path), None, message)
        for message in validate_yaml(path)
    ]
    return problems, []


def _human_coding_gate(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    path = paper_root / "data" / "human-coding-report.json"
    if not path.is_file():
        return [
            Problem(
                "human-coding-report-missing",
                str(path),
                None,
                "缺少真人双编码报告",
            )
        ], []
    payload = _load_structured(path)
    status = payload.get("status") if payload else None
    if (
        not isinstance(status, str)
        or status.strip().casefold() in PENDING_REVIEW_STATUSES
    ):
        return [
            Problem(
                "human-coding-pending",
                str(path),
                None,
                "真人双编码尚未完成",
            )
        ], []
    accepted = {"complete", "completed", "human-attested", "passed"}
    if status.strip().casefold() not in accepted:
        return [
            Problem(
                "human-coding-unknown-status",
                str(path),
                None,
                f"未知真人双编码状态: {status!r}",
            )
        ], []
    return [], []


def _formal_check_gate(paper_root: Path) -> tuple[list[Problem], list[Problem]]:
    problems, advisories, _results = formal_check.run_checks(paper_root)
    return problems, advisories


def _gate_specs(paper_root: Path, profile: str) -> list[tuple[str, object]]:
    specs: dict[str, object] = {
        "schema-valid": lambda: _schema_gate(paper_root),
    }
    runners = {
        "argument-audit": lambda: argument_audit.check(paper_root),
        "governance": lambda: governance.check(paper_root),
        "human-coding": lambda: _human_coding_gate(paper_root),
        "novelty": lambda: novelty.check(paper_root),
        "repro-environment": lambda: repro_env.check(paper_root),
        "statistics": lambda: stats_plan.check(paper_root),
        "experiment-loop": lambda: experiment_loop.check(paper_root),
        "rigor-rubric": lambda: rigor.check(
            paper_root,
            require_complete=profile == "high-assurance",
        ),
        "proof-orchestrator": lambda: proof_orchestrator.check(
            paper_root,
            require_complete=profile == "high-assurance",
        ),
        "artifact-badge": lambda: artifact_badge.check(
            paper_root,
            require_verified=profile == "high-assurance",
        ),
    }
    for ledger in PROFILE_REQUIRED_LEDGERS[profile]:
        if not (paper_root / EVIDENCE_LEDGER_PATHS[ledger]).is_file():
            continue
        gate_name = LEDGER_GATE_NAMES.get(ledger)
        if gate_name is not None:
            specs[gate_name] = runners[gate_name]

    if profile == "minimal":
        return list(specs.items())

    if (paper_root / EVIDENCE_LEDGER_PATHS["post-submission"]).is_file():
        specs["post-submission"] = lambda: post_submission.check(paper_root)
    if (paper_root / "experiments" / "log" / "run-ledger.jsonl").is_file():
        specs["run-ledger"] = lambda: run_ledger.check_ledger(paper_root)
    if (paper_root / "reviews" / "review-loop-state.json").is_file():
        specs["review-loop"] = lambda: review_loop.check_loop(paper_root)
    if (
        (paper_root / "data" / "capability-matrix.yaml").is_file()
        or (paper_root / "data" / "data-flows.yaml").is_file()
    ):
        specs["governance-map"] = lambda: governance_map.check(paper_root)
    if (
        paper_root
        / "ccfa-workfiles"
        / "artifact-store"
        / "manifest.json"
    ).is_file():
        specs["artifact-store"] = lambda: artifact_store.verify_store(paper_root)
    if (paper_root / "data" / "formal-checks.yaml").is_file():
        specs["formal-check"] = lambda: _formal_check_gate(paper_root)
    if (paper_root / "data" / "resubmit-plan.yaml").is_file():
        specs["resubmit-pipeline"] = lambda: resubmit_pipeline.check(paper_root)
    if (paper_root / "data" / "talk-plan.yaml").is_file():
        specs["talk-pipeline"] = lambda: talk_pipeline.check(paper_root)
    if (
        paper_root / "ccfa-workfiles" / "passport" / "run-ledger.yaml"
    ).is_file():
        specs["passport-ledger"] = lambda: passport_ledger.check_ledger(paper_root)

    specs["research-ledgers"] = lambda: research_ledgers.check(
        paper_root,
        require_core=True,
    )

    manuscript = paper_root / "manuscript"
    bib = manuscript / "references.bib"
    if manuscript.is_dir():
        specs["latex-structure"] = lambda: latex_check.check(manuscript, bib)
        tex_files = list(iter_tex_files(manuscript))
        if tex_files:
            specs["trace-claims"] = lambda: trace_claims.check(
                tex_files,
                base_dir=paper_root,
            )
    citation_ledger = paper_root / "data" / "citation-ledger.json"
    if manuscript.is_dir() and bib.is_file() and citation_ledger.is_file():
        specs["citation-guard"] = lambda: citation_guard.check(
            manuscript,
            bib,
            citation_ledger,
        )
    pdf = paper_root / "submission" / "final.pdf"
    if pdf.is_file():
        specs["final-check"] = lambda: final_check.check(
            manuscript,
            pdf=pdf,
            paper_root=paper_root,
        )
    if (paper_root / "reviews" / "cross-review.json").is_file():
        specs["cross-review"] = lambda: (
            cross_review.check_review(
                paper_root,
                strict_cross_family=profile == "high-assurance",
            ),
            [],
        )
    if (paper_root / "submission" / "repro" / "MANIFEST.json").is_file():
        specs["repro-package"] = lambda: repro_package.verify_bundle(
            paper_root / "submission" / "repro"
        )
    return list(specs.items())


def _run_gates(paper_root: Path, profile: str) -> list[dict]:
    return [
        _run_gate(name, runner)
        for name, runner in _gate_specs(paper_root, profile)
    ]


def _load_structured(path: Path) -> dict | None:
    try:
        if path.suffix.casefold() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_gate_drills(paper_root: Path) -> tuple[dict[str, dict], list[Problem]]:
    """Index valid failure-drill records by gate name.

    A record only counts when it says the gate actually triggered *and* points
    at an existing evidence file. A claim without evidence is a problem, not a
    pass; a gate with no record at all is handled by the caller as unproven.
    """
    path = paper_root / GATE_DRILLS_RELATIVE_PATH
    if not path.is_file():
        return {}, []
    payload = _load_structured(path)
    if payload is None:
        return {}, [
            Problem(
                "gate-drills-invalid",
                str(path),
                None,
                "失败演练台账必须是合法 YAML 映射",
            )
        ]
    drills = payload.get("drills")
    if not isinstance(drills, list):
        return {}, [
            Problem(
                "gate-drills-invalid",
                str(path),
                None,
                "失败演练台账必须包含 drills 列表",
            )
        ]
    index: dict[str, dict] = {}
    problems: list[Problem] = []
    for position, entry in enumerate(drills):
        if not isinstance(entry, dict):
            problems.append(
                Problem(
                    "gate-drills-invalid",
                    str(path),
                    None,
                    f"drills[{position}] 必须是映射",
                )
            )
            continue
        gate = entry.get("gate")
        if not isinstance(gate, str) or not gate.strip():
            problems.append(
                Problem(
                    "gate-drills-invalid",
                    str(path),
                    None,
                    f"drills[{position}] 缺少 gate",
                )
            )
            continue
        gate = gate.strip()
        if entry.get("triggered") is not True:
            problems.append(
                Problem(
                    "gate-drill-not-triggered",
                    str(path),
                    None,
                    f"{gate}: triggered 必须为 true——"
                    "没有被破坏输入触发过的 gate 不算已演练",
                )
            )
            continue
        method = entry.get("method")
        if not isinstance(method, str) or not method.strip():
            problems.append(
                Problem(
                    "gate-drill-invalid",
                    str(path),
                    None,
                    f"{gate}: 缺少 method（说明如何故意破坏）",
                )
            )
            continue
        evidence = entry.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip():
            problems.append(
                Problem(
                    "gate-drill-evidence-missing",
                    str(path),
                    None,
                    f"{gate}: 缺少 evidence（失败输出的存放路径）",
                )
            )
            continue
        evidence_path = paper_root / evidence.strip()
        if not evidence_path.is_file():
            problems.append(
                Problem(
                    "gate-drill-evidence-missing",
                    str(path),
                    None,
                    f"{gate}: evidence 不存在: {evidence.strip()}",
                )
            )
            continue
        if evidence_path.suffix.casefold() == ".json":
            try:
                payload = json.loads(
                    evidence_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = None
            if (
                isinstance(payload, dict)
                and payload.get("triggered") is not True
            ):
                problems.append(
                    Problem(
                        "gate-drill-evidence-not-triggered",
                        str(path),
                        None,
                        f"{gate}: evidence {evidence.strip()} 里 "
                        "triggered 不是 true——失败必须真的发生过",
                    )
                )
                continue
        index[gate] = {
            "gate": gate,
            "method": method.strip(),
            "evidence": evidence.strip(),
        }
    return index, problems


def _gate_drill_advisories(
    drills: dict[str, dict],
    executed: list[str],
) -> list[Problem]:
    path = GATE_DRILLS_RELATIVE_PATH
    return [
        Problem(
            "unproven-guard",
            gate,
            None,
            f"{path} 里没有 {gate} 的失败演练记录；"
            "没有失败过的 guard 与没接线的 guard 无法区分",
        )
        for gate in executed
        if gate not in drills
    ]


def _human_review_status(
    paper_root: Path,
    profile: str,
    gate_results: list[dict] | None = None,
) -> dict:
    pending = []
    if profile == "high-assurance":
        for key in ("proof", "citation-support", "figure-support", "human-coding"):
            path = paper_root / EVIDENCE_LEDGER_PATHS[key]
            payload = _load_structured(path) if path.is_file() else None
            status = payload.get("status") if payload else None
            if not isinstance(status, str) or status.strip().casefold() in PENDING_REVIEW_STATUSES:
                pending.append(key)
    else:
        codes = {
            str(problem.get("code", ""))
            for result in (gate_results or [])
            for problem in result.get("problems", [])
            if isinstance(problem, dict)
        }
        if any("proof-review-not-verified" in code for code in codes):
            pending.append("proof")
        if any("citation-support" in code for code in codes):
            pending.append("citation-support")
        if any("figure-support" in code for code in codes):
            pending.append("figure-support")
        if any("human-coding" in code for code in codes):
            pending.append("human-coding")
    review_codes = {
        str(problem.get("code", ""))
        for result in (gate_results or [])
        if result.get("name") == "cross-review"
        for problem in result.get("problems", [])
        if isinstance(problem, dict)
    }
    if review_codes:
        pending.append("cross-review")
    pending = list(dict.fromkeys(pending))
    if not pending:
        status = "human-attested" if profile == "high-assurance" else "not-required"
        return {"status": status, "pending": [], "checkpoints": []}
    return {
        "status": "pending-human-review",
        "pending": pending,
        "checkpoints": _human_checkpoints(pending),
    }


def _human_checkpoints(pending: list[str]) -> list[dict]:
    """Expand pending human ledgers into question / answer-location records."""

    checkpoints = []
    for key in pending:
        spec = HUMAN_CHECKPOINT_SPECS.get(key)
        ledger = EVIDENCE_LEDGER_PATHS.get(key)
        checkpoints.append(
            {
                "id": key,
                "type": spec["type"] if spec else "approve",
                "stage": spec["stage"] if spec else None,
                "status": "pending",
                "question": spec["question"] if spec else f"{key} 需要人工复核",
                "answer_with": spec["answer_with"] if spec else "",
                "ledger": ledger.as_posix() if ledger else None,
            }
        )
    return checkpoints


def _scientific_status(paper_root: Path) -> dict:
    path = paper_root / "data" / "scientific-acceptance.yaml"
    if not path.is_file():
        return {
            "status": "not-claimed",
            "path": path.relative_to(paper_root).as_posix(),
            "reason": "脚本不能自动证明结论正确；需要外部人类复核台账。",
        }
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {
            "status": "invalid-attestation",
            "path": path.relative_to(paper_root).as_posix(),
            "reason": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "status": "invalid-attestation",
            "path": path.relative_to(paper_root).as_posix(),
            "reason": "台账顶层必须是映射。",
        }
    reviewer = payload.get("external_human_reviewer")
    verdict = payload.get("verdict")
    if isinstance(reviewer, str) and reviewer.strip() and verdict == "accepted":
        return {
            "status": "human-attested",
            "path": path.relative_to(paper_root).as_posix(),
            "reviewer": reviewer.strip(),
        }
    return {
        "status": "invalid-attestation",
        "path": path.relative_to(paper_root).as_posix(),
        "reason": "需要 external_human_reviewer 与 verdict: accepted。",
    }


def build_report(
    paper_root: Path,
    *,
    profile: str | None = None,
    today: date | None = None,
) -> dict:
    paper_root = Path(paper_root).resolve()
    state = _load_state(paper_root)
    selected_profile = _profile(state, profile)
    assurance = _assurance(state)
    audit_profile = _audit_profile(selected_profile, assurance)
    state_path = paper_root / "ccfa.yaml"
    schema_problems = validate_yaml(state_path)
    stage = stage_report(paper_root)
    mode = state.get("target_venue", {}).get("mode", "conference")
    gate = gate_for(mode, stage["current"])
    due = due_report(paper_root, today or date.today())
    ledgers = _ledger_status(paper_root, audit_profile)
    git = _git_summary(paper_root)
    scientific = _scientific_status(paper_root)
    gate_results = _run_gates(paper_root, audit_profile)
    human_review = _human_review_status(paper_root, audit_profile, gate_results)
    executed_gates = [result["name"] for result in gate_results]
    drills, drill_problems = _load_gate_drills(paper_root)
    unproven_advisories = _gate_drill_advisories(drills, executed_gates)
    gate_results.append(
        _gate_result("gate-drills", drill_problems, unproven_advisories)
    )
    unproven_guards = [advisory.path for advisory in unproven_advisories]

    blocking = []
    if schema_problems:
        blocking.append("ccfa.yaml schema/state is invalid")
    blocking.extend(
        f"missing required {audit_profile} ledger: {key}"
        for key in ledgers["missing_required"]
    )
    if due.get("problems"):
        blocking.append("deadline or gate milestone problems are present")
    if git.present and git.dirty:
        blocking.append("paper git worktree is dirty")
    for result in gate_results:
        if result["status"] in {"problem", "error"}:
            codes = ", ".join(
                problem["code"] for problem in result["problems"][:5]
            ) or "unknown"
            blocking.append(f"{result['name']} gate failed: {codes}")
    if selected_profile != "minimal":
        if not git.present:
            blocking.append("paper is not a git worktree")
        elif not git.remotes:
            blocking.append("paper git remote is missing")
        if not git.workflows_present:
            blocking.append("GitHub Actions workflows are missing")
    if (
        audit_profile == "high-assurance"
        and human_review["status"] == "pending-human-review"
    ):
        blocking.append("required human review is incomplete")

    review_status = "independent-evidence-present"
    if audit_profile == "minimal":
        review_status = "not-required"
    elif audit_profile == "high-assurance":
        required_human = {"proof", "human-coding", "citation-support", "figure-support"}
        missing_human = required_human.intersection(ledgers["missing_required"])
        review_status = (
            "missing-human-evidence"
            if missing_human
            else human_review["status"]
        )
    else:
        audit = next(
            (
                result
                for result in gate_results
                if result["name"] == "argument-audit"
            ),
            None,
        )
        if audit is None:
            review_status = "missing-human-evidence"
        elif audit["status"] != "pass":
            review_status = "pending-human-review"

    gate_verified = "pass"
    if any(result["status"] != "pass" for result in gate_results):
        gate_verified = "problem"
    elif ledgers["missing_required"]:
        gate_verified = "not-run"

    collaboration_ready = (
        git.present and bool(git.remotes) and git.workflows_present
    )

    return {
        "paper_root": str(paper_root),
        "profile": selected_profile,
        "assurance": assurance or _default_assurance(selected_profile),
        "audit_profile": audit_profile,
        "stage": {
            **stage,
            "gate_criterion": gate.criterion,
        },
        "dimensions": {
            "schema-valid": "pass" if not schema_problems else "problem",
            "evidence-present": "pass" if not ledgers["missing_required"] else "problem",
            "gate-verified": gate_verified,
            "independently-reviewed": review_status,
            "scientifically-accepted": scientific["status"],
            "collaboration-ready": "pass" if collaboration_ready else "problem",
        },
        "schema_problems": schema_problems,
        "evidence": ledgers,
        "deadline": {
            "due": due.get("due", []),
            "problems": due.get("problems", []),
            "advisories": due.get("advisories", []),
        },
        "gate_results": gate_results,
        "git": {
            "present": git.present,
            "dirty": git.dirty,
            "commit": git.commit,
            "remotes": git.remotes,
            "workflows_present": git.workflows_present,
            "error": git.error,
        },
        "scientific_acceptance": scientific,
        "human_review": human_review,
        "unproven_guards": unproven_guards,
        "blocking": blocking,
        "ready": not blocking,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Readiness Report",
        "",
        f"- paper: `{report['paper_root']}`",
        f"- profile: `{report['profile']}`",
        f"- assurance: `{report.get('assurance')}` "
        f"(audit chain `{report.get('audit_profile')}`)",
        f"- stage: `{report['stage']['current']}` / gate `{report['stage']['gate']}`",
        f"- ready: `{str(report['ready']).lower()}`",
        "",
        "## Dimensions",
        "",
    ]
    for key, value in report["dimensions"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Blocking", ""])
    if report["blocking"]:
        lines.extend(f"- {item}" for item in report["blocking"])
    else:
        lines.append("- none")
    checkpoints = report.get("human_review", {}).get("checkpoints", [])
    lines.extend(["", "## Human Checkpoints", ""])
    if checkpoints:
        for item in checkpoints:
            lines.append(
                f"- `{item['id']}` ({item['type']}, stage `{item['stage']}`): "
                f"{item['question']}"
            )
            lines.append(
                f"  - 回答位置: `{item['ledger']}` — {item['answer_with']}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence Ledgers", ""])
    for key, item in report["evidence"]["items"].items():
        marker = "present" if item["present"] else "missing"
        required = "required" if item["required"] else "optional"
        lines.append(f"- `{key}`: `{marker}` ({required}) `{item['path']}`")
    lines.extend(["", "## Gate Verification", ""])
    for result in report["gate_results"]:
        codes = ", ".join(
            problem["code"] for problem in result["problems"]
        ) or "none"
        lines.append(
            f"- `{result['name']}`: `{result['status']}` "
            f"(problems: {result['problem_count']}; codes: {codes})"
        )
    lines.extend(["", "## Git And CI", ""])
    git = report["git"]
    lines.append(f"- git: `{'present' if git['present'] else 'missing'}`")
    lines.append(f"- dirty: `{git['dirty']}`")
    lines.append(f"- commit: `{git['commit']}`")
    lines.append(f"- remotes: `{', '.join(git['remotes']) or 'none'}`")
    lines.append(f"- GitHub Actions workflows: `{git['workflows_present']}`")
    lines.extend(["", "## Scientific Boundary", ""])
    lines.append(
        "- This report does not certify that proofs, statistics, citations, "
        "or claims are scientifically correct."
    )
    status = report["scientific_acceptance"]
    lines.append(f"- scientific acceptance: `{status['status']}`")
    if status.get("reason"):
        lines.append(f"- reason: {status['reason']}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成一页式论文 readiness report")
    parser.add_argument("--paper-root", default=".")
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--today", help="注入今天日期 YYYY-MM-DD（默认系统日期）")
    parser.add_argument(
        "--out",
        help="可选 Markdown 输出路径；相对路径按 paper-root 解析",
    )
    parser.add_argument(
        "--checkpoints-only",
        action="store_true",
        help="只输出人工复核 checkpoint，不执行 gate（给桌面工作台用）",
    )
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv[1:])
    try:
        today = date.fromisoformat(args.today) if args.today else None
        paper_root = Path(args.paper_root)
        if args.checkpoints_only:
            # The workbench needs the human queue, not 25 gate subprocesses.
            state = _load_state(paper_root)
            selected_profile = _profile(state, args.profile)
            assurance = _assurance(state)
            audit_profile = _audit_profile(selected_profile, assurance)
            payload = {
                "paper_root": str(paper_root),
                "profile": selected_profile,
                "assurance": assurance or _default_assurance(selected_profile),
                "audit_profile": audit_profile,
                "human_review": _human_review_status(paper_root, audit_profile),
            }
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return 0
        report = build_report(paper_root, profile=args.profile, today=today)
        if args.out:
            out = Path(args.out)
            if not out.is_absolute():
                out = paper_root / out
            save_text_atomically(out, render_markdown(report), "readiness report")
    except (OSError, ValueError) as exc:
        return tool_error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
