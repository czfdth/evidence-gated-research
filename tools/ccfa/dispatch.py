"""Portable ``ccfa <command> ...`` dispatcher.

Every ``scripts/*.ps1`` wrapper has an equivalent command here, so the workflow
runs on Linux and macOS without PowerShell. ``python -m ccfa <command>``, the
installed ``ccfa`` console script and ``scripts/ccfa`` all land in this module.

Command names deliberately match the wrapper file stems, including the
irregular ones (``archive`` -> ``archive_client``, ``statistics`` ->
``stats_plan``), because those names are already in the documentation.
"""

from __future__ import annotations

import importlib
import sys

VERSION = "ccfa-research-workflow 0.1.0"

# command -> importable module. Keep this in sync with scripts/*.ps1; the parity
# test fails closed when a wrapper is neither dispatched nor declared
# platform-specific.
COMMANDS: dict[str, str] = {
    "ara-compile": "ccfa.ara_compile",
    "ara-extract": "ccfa.ara_extract",
    "archive": "ccfa.archive_client",
    "argument-audit": "ccfa.argument_audit",
    "artifact-badge": "ccfa.artifact_badge",
    "artifact-store": "ccfa.artifact_store",
    "autoresearch": "ccfa.autoresearch",
    "change-log": "ccfa.change_log",
    "citation-calibration": "ccfa.citation_calibration",
    "citation-guard": "ccfa.citation_guard",
    "claim-extract": "ccfa.claim_extract",
    "compute": "ccfa.compute",
    "cross-review": "ccfa.cross_review",
    "dashboard": "ccfa.dashboard",
    "doctor": "ccfa.doctor",
    "e2e-check": "ccfa.e2e_check",
    "experiment-loop": "ccfa.experiment_loop",
    "experiment-optimize": "ccfa.experiment_optimizer",
    "external-adapters": "ccfa.external_adapters",
    "final-check": "ccfa.final_check",
    "formal-check": "ccfa.formal_check",
    "friction-log": "ccfa.friction_log",
    "governance": "ccfa.governance",
    "governance-map": "ccfa.governance_map",
    "human-coding": "ccfa.human_coding",
    "install-toolchain": "install.fetch_toolchain",
    "latex-check": "ccfa.latex_check",
    "library": "ccfa.library",
    "long-task": "ccfa.long_task",
    "memory": "ccfa.memory",
    "meta-optimize": "ccfa.meta_optimize",
    "milestones": "ccfa.milestones",
    "new-paper": "newpaper.create",
    "novelty": "ccfa.novelty",
    "passport-ledger": "ccfa.passport_ledger",
    "post-submission": "ccfa.post_submission",
    "proof-orchestrator": "ccfa.proof_orchestrator",
    "proof-run": "ccfa.proof_run",
    "provenance": "ccfa.provenance",
    "queue": "ccfa.queue",
    "readiness": "ccfa.readiness",
    "reference-audit": "ccfa.reference_audit",
    "repro-container": "ccfa.repro_container",
    "repro-env": "ccfa.repro_env",
    "repro-package": "ccfa.repro_package",
    "research-ledgers": "ccfa.research_ledgers",
    "research-state": "ccfa.research_state",
    "research-version": "ccfa.research_version",
    "research-wiki": "ccfa.research_wiki",
    "resubmit-pipeline": "ccfa.resubmit_pipeline",
    "review-loop": "ccfa.review_loop",
    "revision-ledger": "ccfa.revision_ledger",
    "rigor-rubric": "ccfa.rigor",
    "run-ledger": "ccfa.run_ledger",
    "run-log": "ccfa.run_log",
    "session-replay": "ccfa.session_replay",
    "skill-registry": "ccfa.skill_registry",
    "skillpack": "ccfa.skillpack",
    "stages": "ccfa.stages",
    "state": "ccfa.state",
    "statistics": "ccfa.stats_plan",
    "talk-pipeline": "ccfa.talk_pipeline",
    "test-impact": "ccfa.test_impact",
    "trace-claims": "ccfa.trace_claims",
    "validate": "ccfa.validate",
    "venue-fixtures": "ccfa.venue_fixtures",
    "verifiers": "ccfa.verifiers",
    "watch": "ccfa.watch",
    "worktree-audit": "ccfa.worktree_audit",
}

# Wrappers with no portable equivalent: they build a Windows installer, stage a
# Windows embeddable CPython runtime, or publish through PowerShell 7. Declaring
# them here keeps the parity test honest instead of silently ignoring them. A
# declaration may name a wrapper that a parallel branch adds later, so the test
# asserts commands against the wrapper set but treats this map as intent.
PLATFORM_SPECIFIC_COMMANDS: dict[str, str] = {
    "build-workbench": "PyInstaller + Inno Setup Windows installer build",
    "bundle-workflow": "stages a Windows embeddable CPython runtime",
    "publish-public": "PowerShell 7 sanitized public-mirror publisher",
}


def resolve(name: str) -> str | None:
    """Return the module for *name*, accepting dash or underscore spelling."""
    if not isinstance(name, str):
        return None
    key = name.strip()
    if key in COMMANDS:
        return COMMANDS[key]
    dashed = key.replace("_", "-")
    if dashed in COMMANDS:
        return COMMANDS[dashed]
    return None


def _usage() -> str:
    return "\n".join(
        [
            "usage: ccfa <command> [args...]",
            "       ccfa list",
            "",
            f"{len(COMMANDS)} portable commands; the same names as scripts/*.ps1.",
            "Every command forwards its arguments to the tool's own parser;",
            "run `ccfa <command> --help` for the flags of one tool.",
        ]
    )


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(_usage())
        return 0
    if argv[0] in {"list", "commands"}:
        for name in sorted(COMMANDS):
            print(name)
        return 0
    if argv[0] in {"-V", "--version", "version"}:
        print(VERSION)
        return 0

    module_name = resolve(argv[0])
    if module_name is None:
        print(f"unknown ccfa command: {argv[0]}", file=sys.stderr)
        print("run `ccfa list` to see the portable commands", file=sys.stderr)
        return 2
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"cannot import {module_name}: {exc}", file=sys.stderr)
        return 2
    entry = getattr(module, "main", None)
    if not callable(entry):
        print(f"{module_name} has no main()", file=sys.stderr)
        return 2
    try:
        return int(entry([f"ccfa {argv[0]}", *argv[1:]]) or 0)
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == "__main__":
    raise SystemExit(run())
