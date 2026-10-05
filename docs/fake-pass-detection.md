# Fake-Pass Detection

## Problem

A model review can return `pass` while the gate is not actually satisfied. The
research workflow must not accept a model's self-declared success as an
acquittal.

## Mechanical Rule

`tools/ccfa/cross_review.py` enforces:

- the stored review must have complete provider provenance;
- the review model and the execution model must be cross-family for a gate pass;
- same-family or unknown-family `pass` is downgraded to `blocking`;
- `family_override` can explain an exception but cannot create an acquittal;
- blocking items must quote evidence that exists in the reviewed inputs;
- the review prompt, input hashes, provider endpoint and provider config are
  bound into the record;
- a changed input, prompt or provider config makes the record stale.

## Reproduce

```powershell
scripts/cross-review.ps1 check --paper-root <paper> --out-dir reviews --strict-cross-family
```

## Honest Boundary

This detects self-acquittal and record inconsistency. It cannot prove that a
valid-looking cross-family review is scientifically correct, and it cannot stop
someone who can rewrite the record and every referenced file. The trust boundary
is stated in `docs/design/2026-10-03-research-workflow-design.md`.
