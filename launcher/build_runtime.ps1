# Assemble the Python runtime the installer carries.
#
#   pwsh launcher/build_runtime.ps1 -Stage stage -AppZip dist/mangatct-app-1.0.0.zip
#
# Run on a Windows machine (the release workflow's runner). What it makes:
#
#   stage\runtime\python\    a full, relocatable CPython - a python-build-
#                            standalone `install_only_stripped` build: the
#                            python.org layout (Lib\, DLLs\, tcl\) with
#                            tkinter, pip and the VC runtime inside it, no
#                            installer, no registry footprint, no .pdb files
#   stage\app\<version>\     the app zip unpacked, `.complete` written
#
# ...with every package in requirements.txt installed into that Python, and
# then PROVED: the app is imported from the staged folder by the staged
# interpreter, and a Tcl interpreter is started, before the script says it
# is done. An installer whose runtime cannot import the app is the one
# failure the tests on Linux cannot see, so it is checked here, where it can be.
#
# Why not the NuGet `python` package: Release #4 died on it. That package
# leaves tkinter out (no DLLs\_tkinter.pyd, no tcl\), and the folder picker
# is tkinter. The python-build-standalone tarball is pinned by version, by
# the build date of the release it came in, and by sha256 - a download that
# is not that exact file is refused, not staged.
param(
    [string]$Stage = "stage",
    [Parameter(Mandatory = $true)][string]$AppZip,
    [string]$PythonVersion = "3.12.7",
    [string]$PythonBuild = "20241016",
    [string]$PythonSha256 = "fa8ac308a7cd1774d599ad9a29f1e374fbdc11453b12a8c50cc4afdb5c4bfd1a"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # the download progress bar makes Invoke-WebRequest crawl

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path (Get-Location) $Stage
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# --- the interpreter ------------------------------------------------------
$dl = Join-Path $stage "_python"
if (Test-Path $dl) { Remove-Item -Recurse -Force $dl }
New-Item -ItemType Directory -Force -Path $dl | Out-Null
$asset = "cpython-${PythonVersion}+${PythonBuild}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
$url = "https://github.com/astral-sh/python-build-standalone/releases/download/${PythonBuild}/" + $asset.Replace("+", "%2B")
$tgz = Join-Path $dl $asset
Write-Host "== fetching python $PythonVersion (python-build-standalone $PythonBuild)"
Invoke-WebRequest -Uri $url -OutFile $tgz
$got = (Get-FileHash -Algorithm SHA256 $tgz).Hash.ToLower()
if ($got -ne $PythonSha256.ToLower()) { throw "${asset}: sha256 is $got, expected $PythonSha256 - not staging it" }
tar -xzf $tgz -C $dl
if ($LASTEXITCODE -ne 0) { throw "could not unpack $asset" }
$src = Join-Path $dl "python"
if (-not (Test-Path (Join-Path $src "python.exe"))) { throw "no python.exe under $src" }
$py = Join-Path $stage "runtime\python"
if (Test-Path $py) { Remove-Item -Recurse -Force $py }
New-Item -ItemType Directory -Force -Path (Split-Path $py) | Out-Null
Move-Item $src $py
Remove-Item -Recurse -Force $dl
$python = Join-Path $py "python.exe"
# Not just the import: a Tcl interpreter has to come up, which means tcl\ was
# found next to the relocated python.exe. No window is opened, so this runs
# on a headless runner too.
& $python -c "import sys, tkinter; print('python', sys.version.split()[0], 'tk', tkinter.TkVersion, 'tcl', tkinter.Tcl().eval('info patchlevel'))"
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
& $python -c "import mangatl.editor, mangatl.version, mangatl.pickdir, mangatl.window, cv2, numpy, onnxruntime, PIL, webview; print('imports ok', mangatl.version.__version__)"
$ok = $LASTEXITCODE
if ($ok -eq 0) {
    # The app's window rides on WebView2 through pythonnet. Whether THIS
    # runner has the WebView2 runtime is the runner's business (it does -
    # Edge is on it), but pythonnet loading and the interop DLLs being
    # present are the build's, so they are proved here.
    & $python -c "from webview.platforms import winforms; print('webview2 on this runner:', winforms.is_chromium)"
    $ok = $LASTEXITCODE
}
Pop-Location
if ($ok -ne 0) { throw "the staged runtime cannot import the app" }

# --- trim ----------------------------------------------------------------
Get-ChildItem -Path $py -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
$size = [math]::Round((Get-ChildItem -Recurse $stage | Measure-Object -Property Length -Sum).Sum / 1MB)
Write-Host "== stage ready: $size MB under $stage"
