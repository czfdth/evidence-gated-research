# Readiness Gate Hardening Plan

Date: 2026-10-05

## Goal

Make readiness reports fail closed when downstream gates fail, remove stale
model provenance assumptions, and correct the known reproducibility metadata
drift.

## Phases

- [x] Phase 1: Add regression coverage for gate aggregation and provenance failures.
- [x] Phase 2: Implement readiness gate execution and explicit `gate-verified` status.
- [x] Phase 3: Tighten cross-review provenance validation and remove stale constants.
- [x] Phase 4: Correct the paper lockfile hash and verify downstream checks.
- [x] Phase 5: Update documentation and run targeted verification.

## Key Questions

1. Which gates are required for each readiness profile?
2. How should missing artifacts differ from present artifacts that fail a gate?
3. How should legacy cross-review records fail without breaking useful diagnostics?

## Decisions Made

- Keep `evidence-present` as a presence-only dimension; add a separate
  `gate-verified` dimension.
- Run gate checks in-process and report problem/advisory codes plus counts.
- Treat incomplete provenance as a problem even when a same-family override is present.

## Errors Encountered

- The first readiness implementation treated missing ledgers as failed checks;
  changed it to report `gate-verified: not-run` and leave missing evidence to the
  `evidence-present` dimension.

## Status

**Complete** - targeted verification passed; commit and remote push remain.
