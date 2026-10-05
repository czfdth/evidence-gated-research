$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
& "$root/tools/.venv/Scripts/python.exe" -m ccfa.trace_claims @args
exit $LASTEXITCODE
