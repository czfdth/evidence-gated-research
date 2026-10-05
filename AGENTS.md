# Workflow Engineering Contract

## Change Log Is Mandatory

Every change to the research workflow must add one append-only entry to
`docs/workflow-change-log.jsonl` in the same commit or pull request.

This applies to changes under:

- `tools/`
- `scripts/`
- `app/`
- `.github/`
- `automation/`
- `checklists/`
- `docs/` (except the change-log files themselves)
- root workflow files such as `README.md`, `ccfa.yaml.template`, and dependency/lock files

The log entry must record:

- what changed;
- why it changed;
- every affected repository-relative file;
- the tests or checks that were actually run;
- whether the change is complete or pending;
- who or what made the change.

The canonical machine-readable source is
`docs/workflow-change-log.jsonl`. `docs/workflow-change-log.md` is generated and
must be refreshed from the JSONL source.

Use:

```powershell
scripts/change-log.ps1 add `
    --summary "<what changed>" `
    --reason "<why>" `
    --file tools/ccfa/example.py `
    --test "tools.tests.test_example" `
    --author codex

scripts/change-log.ps1 check --base origin/master
scripts/change-log.ps1 render
```

`change-log check` fails closed when a workflow file changed since the base ref
is not covered by any log entry. Do not bypass this check by deleting or
rewriting old entries. Never write a log that claims a test or human review was
completed when it was not.

## Scope Boundary

- `papers/<slug>/` is a separate paper repository and is not logged here.
- `library/` stores shared literature, not workflow code.
- Generated runtime data (`ccfa-workfiles/`, `build/`, `dist/`,
  `.ruff_cache/`, and similar) is not a workflow source change.
