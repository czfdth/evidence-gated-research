<#
.SYNOPSIS
  Build the Windows installer for the paper workbench.

.DESCRIPTION
  PyInstaller freezes app/ into dist/ccfa-workbench/, then Inno Setup wraps it
  into dist/ccfa-workbench-setup-<version>.exe.

  Only the workbench itself is bundled: it drives the research workflow over
  the CLI, so an installed copy needs the workflow directory configured in the
  settings dialog (or CCFA_WORKFLOW_ROOT). Keep this script ASCII-only:
  Windows PowerShell 5.1 reads BOM-less scripts as GBK and mangles UTF-8.

.PARAMETER SkipInstaller
  Run PyInstaller only, to check the frozen app without building a setup exe.
#>
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$appDir = Join-Path $root "app"
$python = Join-Path $appDir ".venv/Scripts/python.exe"

if (-not (Test-Path $python)) {
    throw "app/.venv is missing; create it and install requirements-dev.txt"
}

Write-Host "== PyInstaller =="
$specArgs = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean",
    "--distpath", (Join-Path $root "dist"),
    "--workpath", (Join-Path $root "build/pyinstaller"),
    (Join-Path $appDir "ccfa-workbench.spec")
)
& $python @specArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

$frozen = Join-Path $root "dist/ccfa-workbench/ccfa-workbench.exe"
if (-not (Test-Path $frozen)) { throw "missing $frozen" }
Write-Host "frozen app: $frozen"

if ($SkipInstaller) { exit 0 }

Write-Host "== Inno Setup =="
$candidates = @()
if ($env:LOCALAPPDATA) {
    $candidates += Join-Path $env:LOCALAPPDATA "Programs/Inno Setup 6/ISCC.exe"
}
if (${env:ProgramFiles(x86)}) {
    $candidates += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6/ISCC.exe"
}
if ($env:ProgramFiles) {
    $candidates += Join-Path $env:ProgramFiles "Inno Setup 6/ISCC.exe"
}
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "ISCC.exe not found; run: winget install JRSoftware.InnoSetup"
}
& $iscc (Join-Path $appDir "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }

$setup = Join-Path $root "dist/ccfa-workbench-setup-0.1.0.exe"
if (-not (Test-Path $setup)) { throw "missing $setup" }
Write-Host "installer: $setup"
