# Workflow Deficiency Checklist

Date: 2026-10-06

This checklist turns the live GitHub comparison into explicit work items.

## P0

| # | Deficiency | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P0-1 | Keep the evidence-first moat instead of chasing automation | Policy adopted | `AGENTS.md` now requires every workflow change to carry a change-log entry; fake-pass detection is documented in `docs/fake-pass-detection.md` |
| P0-2 | Publish fake-pass detection as a reusable artifact | Code + docs ready; publication pending | `tools/ccfa/cross_review.py` is the checker; `docs/fake-pass-detection.md` is the public-facing explanation |
| P0-3a | Citation calibration has no live gold-set evidence | Blocked on gold data | The calibration tool exists and fails closed; a real gold/prediction JSONL pair must be produced and run |
| P0-3b | Reproduction has no second-environment evidence | Code + live evidence resolved | `repro-container` runs the bundle in a pinned, network-disabled Docker image; the paper receipt `reviews/repro-container.json` records `status=pass`, `exit_code=0`, and `repro_env` validates it |
| P0-3c | Proof and claim support still need human review | Blocked on humans | `proof-audit.yaml`, `citation-support.yaml`, `figure-support.yaml`, `human-coding-report.json` remain human tasks |
| P0-4 | Worktree drift is not visible or controlled | Code-resolved; cleanup pending | `scripts/worktree-audit.ps1` lists covered/uncovered files; unrelated uncommitted work still needs a logged commit or discard decision |

## P1

| # | Deficiency | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P1-1 | Automatic ARA semantic extraction front-end | Candidate extraction code-resolved | `claim_extract.py` extracts PDF/repo text into `claim-candidates.yaml` with source hash, page/line, verbatim quote, Ollama or heuristic extraction, and `status=proposed`; promotion to claim registry stays human. `ara_extract.py` still maps structured inputs into `ara-input/` |
| P1-2 | Inner experiment loop is not truly automatic | Code-resolved for parameter search | `experiment_optimizer.py` runs grid/random trials under budget, parses objective metrics, tracks best/patience, writes per-trial logs and a keep/revert proposal. It does not mutate code or auto-promote claims; proposals remain human-reviewed |
| P1-3 | Portability: no pipx/console entry | Resolved | Root `pyproject.toml` + `ccfa.dispatch:run` expose `ccfa <module> ...`; devcontainer is still optional |
| P1-4 | Reference audit is not periodic | Code-resolved | `docs/reference-registry.yaml` pins audited commits; `reference-audit.yml` checks monthly and fails closed on upstream drift |
| P1-5 | Automatic code mutation and new research-plan generation | Sandboxed code-resolved | `autoresearch.py` generates `research-plan-candidates.yaml` and model-authored file replacements for explicitly allowed files; mutations are applied and tested in a disposable sandbox, recorded as diffs, and never modify the source repo or claim registry |
| P1-6 | Cross-session long-task continuation | Code-resolved | `long_task.py` stores a task spec and hash-chained append-only events under `ccfa-workfiles/tasks/`; `resume` replays state from disk and `run-next` executes the next command with run-log evidence |
| P1-7 | Skill composability and independent installation | Code-resolved; P0 external skills registered | `skills/registry.yaml` resolves `repo`/`codex`/`agents` source roots, rejects cycles, derives content-hash versions for unversioned external skills, builds verifiable `.skillpack` archives, and installs selected skills with dependencies. The 15 P0 CCF skills are now registered without copying their source |
| P1-8 | Nature/Cell P1 methodology skills are outside the registry | Registered | The 18 `nature-*` skills plus `cell-cns-figure` are registered via the `codex` source root, dependency-checked, and pack/install verified without copying their source trees |
| P1-9 | External-service skills have no capability boundary | Adapter layer added | `skills/adapters.yaml` and `external_adapters.py` record service, auth mode and env-var names; probes distinguish installed/configured/functional and never read or print secret values |

## P2

| # | Deficiency | Status | Evidence / remaining work |
| --- | --- | --- | --- |
| P2-1 | Private repo means zero discoverability | Cannot be solved in-repo | Requires an explicit decision to publish a companion/reproducibility repo |
| P2-2 | Desktop packaging | Partially addressed by existing workbench work | Packaging scripts exist in the workbench track; this checklist does not duplicate them |
| P2-3 | Too many tools increases maintenance | Controlled but not reduced | New change-log and worktree-audit checks make changes visible; consolidation is still a future cleanup task |
| P2-4 | Live artifact badge and DOI evidence absent | Blocked on external archive | `artifact-badge` and `artifact-store` exist; third-party evaluated/reusable evidence and DOI must be obtained |
| P2-5 | open-science added advisory cross-language artifact dependency edges | Ledger-level aligned | `artifact-provenance.yaml` now supports `depends_on` edges with explicit `authority: advisory` or `verified`; `verified` requires existing evidence, unknown targets fail, and cycles are rejected. Runtime file-read observation remains out of scope |

## Current Non-Goals

- Do not fabricate human proof review, dual coding, citations, COI, DOI or
  third-party reuse.
- Do not move paper content into this repository.
- Do not treat `ready=false` as a bug; it is the intended fail-closed result
  while live evidence is missing.
