$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
Push-Location $root
& "$root/tools/.venv/Scripts/python.exe" -m ccfa.worktree_audit @args
exit $LASTEXITCODE
