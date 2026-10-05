# Security Policy

This repository is intended for private research workflow use. Keep active paper repositories private during double-blind review.

## Reporting

For private use, record suspected security issues in `docs/sdd/2026-10-03-evidence-tracking-progress.md` or a private GitHub issue. Do not publish credentials, unpublished manuscripts, private PDFs, reviewer identities, or dual-use details in public issues.

## Required Checks

- Run targeted secret scanning before pushing changes that touch settings, registries, CI, or generated logs.
- Keep API keys in the OS keyring or GitHub encrypted secrets, never in YAML, JSON, TOML, logs, or tool audit files.
- Use private repositories for active manuscripts and review artifacts.
- Treat generated release bundles, supplementary archives, and raw literature PDFs as artifacts, not normal source files.
