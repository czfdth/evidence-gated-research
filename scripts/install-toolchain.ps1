$ErrorActionPreference='Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:PYTHONPATH="$root/tools"
$env:PYTHONIOENCODING='utf-8'
& "$root/tools/.venv/Scripts/python.exe" "$root/tools/install/fetch_toolchain.py" @args
exit $LASTEXITCODE
