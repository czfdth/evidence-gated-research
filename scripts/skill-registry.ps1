$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
Push-Location $root
& "$root/tools/.venv/Scripts/python.exe" -m ccfa.skill_registry @args
exit $LASTEXITCODE
