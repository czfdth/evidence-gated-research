<#
.SYNOPSIS
  Stage a self-contained workflow runtime for the installed workbench.

.DESCRIPTION
  Produces the layout the workbench already looks for next to its executable:

    workflow/
      python/            CPython embeddable distribution
      tools/             workflow sources (no venv)
      tools/site-packages/  dependencies installed with pip --target
      BUNDLED.json       what was staged, and the hashes it was staged from

  The embeddable distribution is deliberate: a venv copied from the build
  machine keeps an absolute pointer to that machine's interpreter in
  pyvenv.cfg, so it breaks on the user's machine. The embed zip does not.

  A "._pth" file next to the embedded interpreter puts python312.zip, ..\tools
  and ..\tools\site-packages on sys.path. Python ignores PYTHONPATH whenever a
  ._pth file is present, which is why the paths have to live there.

  Keep this script ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts as
  GBK and mangles UTF-8.

.PARAMETER Destination
  Target directory. Defaults to dist/ccfa-workbench/workflow.

.PARAMETER PythonVersion
  Embeddable CPython version to fetch. 3.12.10 is the last 3.12 with an embed
  zip; wheels built for any 3.12.x load on it.

.PARAMETER CacheDir
  Where the downloaded zip is cached. Defaults to build/embed-cache.

.PARAMETER HostPython
  Interpreter used to run pip. Defaults to tools/.venv/Scripts/python.exe.

.PARAMETER PipIndexUrl
  Index used for the dependency install. Defaults to the Tsinghua mirror this
  machine needs; pass https://pypi.org/simple where the public index works.
#>
param(
    [string]$Destination = "",
    [string]$PythonVersion = "3.12.10",
    [string]$CacheDir = "",
    [string]$HostPython = "",
    [string]$PipIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple"
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $Destination) { $Destination = Join-Path $root "dist/ccfa-workbench/workflow" }
if (-not $CacheDir) { $CacheDir = Join-Path $root "build/embed-cache" }
if (-not $HostPython) { $HostPython = Join-Path $root "tools/.venv/Scripts/python.exe" }

$dest = [System.IO.Path]::GetFullPath($Destination)
if ($root.StartsWith($dest, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "refusing to stage into $dest : it contains the repository itself"
}
if (-not (Test-Path $HostPython)) {
    throw "host python not found: $HostPython (create tools/.venv first)"
}

$tag = ($PythonVersion -split '\.')[0..1] -join ''
$embedName = "python-$PythonVersion-embed-amd64.zip"
$embedUrl = "https://www.python.org/ftp/python/$PythonVersion/$embedName"
$embedPath = Join-Path $CacheDir $embedName
$pthName = "python$tag._pth"

Write-Host "== fetch embeddable CPython $PythonVersion =="
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
if (-not (Test-Path $embedPath)) {
    Write-Host "downloading $embedUrl"
    & curl.exe -L --fail --silent --show-error -o $embedPath $embedUrl
    if ($LASTEXITCODE -ne 0) { throw "download failed: $embedUrl" }
}
$embedHash = (Get-FileHash -LiteralPath $embedPath -Algorithm SHA256).Hash.ToLower()

Write-Host "== stage $dest =="
if (Test-Path $dest) {
    [System.IO.Directory]::Delete($dest, $true)
}
New-Item -ItemType Directory -Path $dest -Force | Out-Null
$pythonDir = Join-Path $dest "python"
Expand-Archive -LiteralPath $embedPath -DestinationPath $pythonDir -Force

$pth = @(
    "python$tag.zip",
    ".",
    "..\tools",
    "..\tools\site-packages",
    "import site"
)
Set-Content -LiteralPath (Join-Path $pythonDir $pthName) -Value $pth -Encoding ASCII

Write-Host "== copy workflow sources =="
$toolsSource = Join-Path $root "tools"
$toolsTarget = Join-Path $dest "tools"
New-Item -ItemType Directory -Path $toolsTarget -Force | Out-Null
Get-ChildItem -LiteralPath $toolsSource -Force | Where-Object {
    $_.Name -notin @('.venv', '__pycache__', '.pytest_cache', 'tests')
} | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $toolsTarget -Recurse -Force
}

Write-Host "== install dependencies (pip --target) =="
$sitePackages = Join-Path $toolsTarget "site-packages"
$requirements = Join-Path $toolsSource "requirements.txt"
& $HostPython -m pip install --quiet --disable-pip-version-check `
    --only-binary :all: --target $sitePackages -r $requirements `
    --index-url $PipIndexUrl
if ($LASTEXITCODE -ne 0) { throw "pip --target failed (exit $LASTEXITCODE)" }

Write-Host "== self-check: import every workflow module =="
$embedded = Join-Path $pythonDir "python.exe"
# Importing every module is the cheap version of "will the tools actually run":
# the embeddable distribution ships a reduced stdlib (no venv, no tkinter), so a
# missing module must fail here rather than on the user's first click.
$probe = @'
import importlib
import pkgutil
import sys

import ccfa

problems = []
for module in pkgutil.iter_modules(ccfa.__path__):
    if module.name.startswith("_"):
        continue
    try:
        importlib.import_module("ccfa." + module.name)
    except Exception as exc:  # noqa: BLE001 - report, do not stop at the first
        problems.append("%s: %s" % (module.name, exc))
if problems:
    print("FAILED")
    for item in problems:
        print("  " + item)
    sys.exit(1)
print("runtime ok: %d modules import" % len(list(pkgutil.iter_modules(ccfa.__path__))))
'@
$probeOut = & $embedded -c $probe 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "embedded runtime cannot import the workflow: $probeOut"
}
Write-Host $probeOut

$requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLower()
$marker = [ordered]@{
    version = 1
    python_version = $PythonVersion
    embed_sha256 = $embedHash
    requirements_sha256 = $requirementsHash
    created_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
$marker | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dest "BUNDLED.json") -Encoding UTF8

$bytes = (Get-ChildItem -LiteralPath $dest -Recurse -File |
    Measure-Object -Property Length -Sum).Sum
Write-Host ("bundled workflow: {0} ({1:N1} MB)" -f $dest, ($bytes / 1MB))
