$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
$env:PYTHONIOENCODING='utf-8'
& "$root/tools/.venv/Scripts/python.exe" -m install.fetch_toolchain @args
exit $LASTEXITCODE
