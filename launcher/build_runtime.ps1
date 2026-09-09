# Assemble the Python runtime the installer carries.
#
#   pwsh launcher/build_runtime.ps1 -Stage stage -AppZip dist/mangatct-app-1.0.0.zip
#
# Run on a Windows machine (the release workflow's runner). What it makes:
#
#   stage\runtime\python\    a full, relocatable CPython - the NuGet `python`
#                            package, which is the same build python.org
#                            ships, with tkinter (the folder picker needs it)
#                            and pip, and no registry footprint
#   stage\app\<version>\     the app zip unpacked, `.complete` written
#
# ...with every package in requirements.txt installed into that Python, and
# then PROVED: the app is imported from the staged folder by the staged
# interpreter, and tkinter is imported, before the script says it is done.
# An installer whose runtime cannot import the app is the one failure the
# tests on Linux cannot see, so it is checked here, where it can be.
param(
    [string]$Stage = "stage",
    [Parameter(Mandatory = $true)][string]$AppZip,
    [string]$PythonVersion = "3.12.7"
)
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path (Get-Location) $Stage
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# --- the interpreter ------------------------------------------------------
$nugetDir = Join-Path $stage "_nuget"
New-Item -ItemType Directory -Force -Path $nugetDir | Out-Null
Write-Host "== fetching python $PythonVersion (nuget)"
nuget install python -Version $PythonVersion -OutputDirectory $nugetDir -ExcludeVersion | Out-Null
$src = Join-Path $nugetDir "python\tools"
if (-not (Test-Path (Join-Path $src "python.exe"))) { throw "no python.exe under $src" }
$py = Join-Path $stage "runtime\python"
if (Test-Path $py) { Remove-Item -Recurse -Force $py }
New-Item -ItemType Directory -Force -Path (Split-Path $py) | Out-Null
Copy-Item -Recurse $src $py
Remove-Item -Recurse -Force $nugetDir
$python = Join-Path $py "python.exe"
& $python -c "import sys, tkinter; print('python', sys.version.split()[0], 'tk', tkinter.TkVersion)"
if ($LASTEXITCODE -ne 0) { throw "the staged python cannot import tkinter" }

# --- the app -------------------------------------------------------------
# The version comes out of the ZIP, by a subcommand rather than an inline
# one-liner: the one-liner needed a literal double quote, and in PowerShell
# that is backtick-quote, not backslash-quote - the backslash ended the string, and the whole script
# failed to PARSE, on every release, before running a line. release.py is
# standard library only, so the bare staged python can run it.
$version = (& $python (Join-Path $PSScriptRoot "..\tools\release.py") zip-version $AppZip).Trim()
if ($LASTEXITCODE -ne 0 -or -not $version) { throw "could not read the version out of $AppZip" }
Write-Host "== app version $version"
$appDir = Join-Path $stage "app\$version"
if (Test-Path $appDir) { Remove-Item -Recurse -Force $appDir }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
Expand-Archive -Path $AppZip -DestinationPath $appDir -Force
Set-Content -Path (Join-Path $appDir ".complete") -Value (Get-Date -Format o)

# --- the packages --------------------------------------------------------
Write-Host "== pip"
& $python -m pip install --upgrade pip --no-warn-script-location --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $python -m pip install --no-warn-script-location --disable-pip-version-check -r (Join-Path $appDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# The launcher records which requirements the runtime was synced to, so the
# first start does not run pip again for nothing. Same hash it computes.
$reqHash = (Get-FileHash -Algorithm SHA256 (Join-Path $appDir "requirements.txt")).Hash.ToLower()
Set-Content -Path (Join-Path $stage "state.json") -Value (@{ requirements_sha256 = $reqHash; app = $version } | ConvertTo-Json)

# --- the proof -----------------------------------------------------------
Write-Host "== proving the staged runtime imports the staged app"
Push-Location $appDir
$env:PYTHONNOUSERSITE = "1"
& $python -c "import mangatl.editor, mangatl.version, mangatl.pickdir, cv2, numpy, onnxruntime, PIL; print('imports ok', mangatl.version.__version__)"
$ok = $LASTEXITCODE
Pop-Location
if ($ok -ne 0) { throw "the staged runtime cannot import the app" }

# --- trim ----------------------------------------------------------------
Get-ChildItem -Path $py -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
$size = [math]::Round((Get-ChildItem -Recurse $stage | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host "== stage ready: $size MB under $stage"
