# Workflow Deficiency Checklist

Date: 2026-10-06

This checklist turns the live GitHub comparison into explicit work items.

## P0

| # | Deficiency | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P0-1 | Keep the evidence-first moat instead of chasing automation | Policy adopted | `AGENTS.md` now requires every workflow change to carry a change-log entry; fake-pass detection is documented in `docs/fake-pass-detection.md` |
| P0-2 | Publish fake-pass detection as a reusable artifact | Code + docs ready; publication pending | `tools/ccfa/cross_review.py` is the checker; `docs/fake-pass-detection.md` is the public-facing explanation |
| P0-3a | Citation calibration has no live gold-set evidence | Blocked on gold data | The calibration tool exists and fails closed; a real gold/prediction JSONL pair must be produced and run |
| P0-3b | Reproduction has no second-environment evidence | Blocked on second environment | Repro bundle/verifier exists; a clean second machine or CI run is still required |
| P0-3c | Proof and claim support still need human review | Blocked on humans | `proof-audit.yaml`, `citation-support.yaml`, `figure-support.yaml`, `human-coding-report.json` remain human tasks |
| P0-4 | Worktree drift is not visible or controlled | Code-resolved; cleanup pending | `scripts/worktree-audit.ps1` lists covered/uncovered files; unrelated uncommitted work still needs a logged commit or discard decision |

## P1

| # | Deficiency | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P1-1 | Automatic ARA semantic extraction front-end | Deterministic front-end added | `tools/ccfa/ara_extract.py` maps local tex/bib/figure/run/claim/exploration inputs into `ara-input/` and reports unresolved semantics |
| P1-2 | Inner experiment loop is not truly automatic | Partially addressed | `experiment-loop` records decisions; a real compute-backed driver still needs to connect to `compute.py`/`queue.py` |
| P1-3 | Portability: no pipx/console entry | Resolved | Root `pyproject.toml` + `ccfa.dispatch:run` expose `ccfa <module> ...`; devcontainer is still optional |
| P1-4 | Reference audit is not periodic | Process defined | Re-run the upstream source audit when a reference project publishes a new method-level change; no scheduler yet |

## P2

| # | Deficiency | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P2-1 | Private repo means zero discoverability | Cannot be solved in-repo | Requires an explicit decision to publish a companion/reproducibility repo |
| P2-2 | Desktop packaging | Partially addressed by existing workbench work | Packaging scripts exist in the workbench track; this checklist does not duplicate them |
| P2-3 | Too many tools increases maintenance | Controlled but not reduced | New change-log and worktree-audit checks make changes visible; consolidation is still a future cleanup task |
| P2-4 | Live artifact badge and DOI evidence absent | Blocked on external archive | `artifact-badge` and `artifact-store` exist; third-party evaluated/reusable evidence and DOI must be obtained |

## Current Non-Goals

- Do not fabricate human proof review, dual coding, citations, COI, DOI or
  third-party reuse.
- Do not move paper content into this repository.
- Do not treat `ready=false` as a bug; it is the intended fail-closed result
  while live evidence is missing.
