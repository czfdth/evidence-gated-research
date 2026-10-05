# Research Workflow Upgrade Design

Date: 2026-10-05

## Goal

Upgrade the workflow from a set of strict evidence gates into a more complete
research loop: claims are first-class, assumptions and limitations are
explicit, exploration and dead ends are preserved, artifact provenance is
attributable, venue methodology is machine-checkable, and cost/risk context
travels with the paper.

## Scope

This upgrade implements the P0 and structural P1 items from
`docs/research-workflow-benchmark-2026-10-05.md`:

1. `data/claim-registry.yaml` ties claims to proof, experiments, figures,
   citations, assumptions, and limitations.
2. `data/assumptions-limitations.yaml` records assumptions, violation impact,
   limitations, and manuscript locations.
3. `data/venue-checklist.yaml` records official venue checklist items and
   evidence links.
4. `data/artifact-provenance.yaml` labels major artifacts as human, model, or
   mixed and records source or run references.
5. `data/exploration-graph.yaml` records pivots, dead ends, rejection reasons,
   claim links, and run links.
6. `data/cost-ledger.yaml` records GPU/model/token costs and rerun counts.
7. `data/risk-register.yaml` records known risks, controls, evidence, and open
   status.
8. `docs/autonomy-policy.md` states which stages are automatic and which
   require human approval.
9. `readiness` aggregates a new `research-ledgers` gate when these ledgers are
   present and, for standard/high-assurance profiles, reports missing P0/P1
   evidence without fabricating scientific acceptance.

## Architecture

Add one focused validator module, `tools/ccfa/research_ledgers.py`, plus one
PowerShell wrapper. The validator reads YAML files and cross-checks references
between them. It does not judge scientific truth; it enforces that the
research graph is structurally complete and has no dangling links.

`readiness` calls the validator as a gate when any of these ledgers or the
autonomy policy exists. Missing required files for `standard` profile are
reported as `not-run` rather than silently passing.

## Data Contracts

### Claim Registry

Each claim requires:

- `id`, `statement`, `type`, `status`
- `assumptions`, `limitations`
- `proof`, `experiments`, `figures`, `citations`

Allowed claim types are `theoretical`, `empirical`, and `descriptive`.
Allowed statuses include `pending-human-review`, `supported`, `provisional`,
and `dropped`.

### Assumptions And Limitations

Assumptions require `id`, `claim_ids`, `statement`, and `violation_impact`.
Limitations require `id`, `claim_ids`, `statement`, and `discussed_in`.
Every referenced claim must exist in the registry.

### Venue Checklist

Each item requires `id`, `requirement`, `status`, `evidence`, and `owner`.
Status is one of `complete`, `pending`, `not-applicable`, or `blocked`.
`complete` requires nonempty evidence.

### Artifact Provenance

Each artifact requires `id`, `path`, `decided_by`, and `source`.
`decided_by` is one of `human`, `model`, or `mixed`.
Model/mixed artifacts must include `model_family`; generated artifacts must
include a run id or source hash.

### Exploration Graph

Each item requires `id`, `kind`, `summary`, `claim_ids`, and `run_ids`.
`kind` is one of `pivot`, `dead-end`, `rejected`, or `active`.
Claim links must exist in the registry.

### Cost Ledger

The ledger requires `currency`, `paper`, and `entries`.
Each entry requires `kind`, `amount`, and `unit`.
Amount must be non-negative and finite.

### Risk Register

Each risk requires `id`, `description`, `severity`, `mitigation`, `evidence`,
and `status`.
Severity is `low`, `medium`, or `high`.
Status is `open`, `mitigated`, or `accepted`.

## Error Handling

All invalid structures return deterministic problem codes. Cross-file dangling
references are problems, not advisories. The validator never writes files.

## Testing

Each contract gets unit tests for valid and invalid forms. A cross-file test
proves dangling claim, proof, figure, citation, run, and assumption references
are rejected. A readiness test proves the new gate participates in
`gate-verified`.

