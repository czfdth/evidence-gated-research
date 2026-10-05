# Research Wiki

Cross-project, machine-readable Markdown notes live here. Each note has YAML
frontmatter with `id`, `kind`, `title`, `status`, `tags`, `projects`,
`evidence`, `related`, and `updated_at`.

Validate, index, and search with:

```powershell
scripts/research-wiki.ps1 check --dir library/wiki
scripts/research-wiki.ps1 index --dir library/wiki --out library/wiki/index.json
scripts/research-wiki.ps1 search --index library/wiki/index.json --query "artifact"
```

The index is generated and may be rebuilt. The Markdown notes are the source
of truth.
