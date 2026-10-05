$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
& "$root/tools/.venv/Scripts/python.exe" -m ccfa.passport_ledger @args
exit $LASTEXITCODE
