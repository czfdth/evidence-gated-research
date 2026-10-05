$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
& "$root/tools/.venv/Scripts/python.exe" -m ccfa.run_log @args
exit $LASTEXITCODE
