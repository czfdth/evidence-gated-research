## Summary

-

## Scope

- [ ] Tools/workflow code
- [ ] App/workbench code
- [ ] Documentation only
- [ ] Paper/project artifact

## Targeted Verification

List only the tests or checks relevant to the changed files.

- [ ] `scripts/change-log.ps1 check --base origin/master`
- [ ] `scripts/test-impact.ps1 plan --base origin/master`
- [ ] `scripts/test-impact.ps1 run --base origin/master`
- [ ] `git diff --check`
- [ ] `scripts/readiness.ps1 --paper-root <paper> --out reviews/readiness.md`

## Scientific Boundary

- [ ] This change does not claim scientific acceptance from deterministic checks alone.
- [ ] Any human review, proof audit, coding adjudication, or citation/figure support claim is backed by a named ledger entry.

## Data And Secrets

- [ ] No private paper PDFs, API keys, tokens, credentials, or generated release bundles are added.
- [ ] Large artifacts are kept out of git or attached through an approved release/archive route.
