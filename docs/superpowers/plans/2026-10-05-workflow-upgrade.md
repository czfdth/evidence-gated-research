# Research Workflow Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add machine-readable research-loop ledgers and integrate them into readiness without weakening existing fail-closed gates.

**Architecture:** One read-only validator module reads YAML ledgers, validates each contract, and cross-checks references. Readiness invokes it as `research-ledgers`.

**Tech Stack:** Python 3.12, PyYAML, unittest, PowerShell wrapper.

**Spec:** `docs/superpowers/specs/2026-10-05-workflow-upgrade-design.md`

## Global Constraints

- Existing scientific gates remain authoritative; new ledgers do not replace human proof/citation/figure review.
- All checks are read-only and return deterministic problem codes.
- No new dependency beyond PyYAML.
- Targeted tests only during implementation; run full tools tests once at the end.

---

### Task 1: Validator Core

**Files:**
- Create: `tools/ccfa/research_ledgers.py`
- Test: `tools/tests/test_research_ledgers.py`

- [x] Write failing tests for valid/invalid claim and assumption ledgers.
- [x] Implement YAML loading and structural validation.
- [x] Run targeted tests.

### Task 2: Cross-File Reference Checks

**Files:**
- Modify: `tools/ccfa/research_ledgers.py`
- Modify: `tools/tests/test_research_ledgers.py`

- [x] Add failing tests for dangling proof, figure, citation, claim, and assumption links.
- [x] Implement cross-file checks against existing audit ledgers.
- [x] Run targeted tests.

### Task 3: P1 Ledger Contracts

**Files:**
- Modify: `tools/ccfa/research_ledgers.py`
- Modify: `tools/tests/test_research_ledgers.py`

- [x] Add failing tests for venue checklist, artifact provenance, exploration graph, cost ledger, and risk register.
- [x] Implement each validator.
- [x] Run targeted tests.

### Task 4: Readiness Integration

**Files:**
- Modify: `tools/ccfa/readiness.py`
- Modify: `tools/tests/test_readiness.py`
- Create: `scripts/research-ledgers.ps1`

- [x] Add failing readiness test for a `research-ledgers` gate result.
- [x] Wire the validator into readiness.
- [x] Add wrapper and docs inventory entry.
- [x] Run readiness/docs tests.

### Task 5: Templates And Documentation

**Files:**
- Create: example YAML templates under `tools/newpaper/templates/` or the active template structure
- Modify: `README.md`, `docs/workflow-guide.md`
- Create: `docs/autonomy-policy.md`

- [x] Add template files with empty valid ledgers.
- [x] Document when each ledger becomes required.
- [x] Run docs consistency tests.
