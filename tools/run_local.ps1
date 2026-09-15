# Run THIS CHECKOUT as the app, in its own window, before it is released.
#
# lee: "can we make a local version to test before realing"
#
# It is the same app the installer puts on the machine, started the same way the
# launcher starts it (the editor, then the window beside it), with two
# differences: the code is this folder rather than %LOCALAPPDATA%\MangaTCT\app\<version>,
# and the window says "MangaTCT (local)" so the two can never be mistaken for
# each other. The Python is the installed runtime's, because that is the Python
# that has pywebview and everything else the app needs - nothing is installed.
#
# It opens the same chapter the installed app does (Documents\MangaTCT\out), so
# the installed app must be CLOSED first: two editors on one project both write
# project.json, and the last one to save wins. It checks, and refuses if it is
# open. Closing the local window stops the local editor.
#
#   powershell -ExecutionPolicy Bypass -File tools\run_local.ps1
#
# The editor's console goes to %LOCALAPPDATA%\MangaTCT\logs\editor-local.log.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot          # tools\ -> the checkout
$parent = Split-Path -Parent $repo                # the folder ABOVE it, so `mangatl` imports
$rt = Join-Path $env:LOCALAPPDATA 'MangaTCT\runtime\python\python.exe'
if (-not (Test-Path $rt)) {
    Write-Host "MangaTCT is not installed on this machine (no $rt)."
    exit 1
}
$port = 8790

# A LOCAL editor left behind by an earlier run - its window closed some other
# way than this script noticing, so the `finally` below never ran - is ours to
# stop: it is on our port and has nothing on screen. It used to make this
# script refuse to start, for a copy of itself.
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'mangatl\.(editor|window)' -and
                   $_.CommandLine -match "--port\s+$port\b" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

# ...but the INSTALLED app is the person's, and it has the same chapter open.
$open = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'mangatl\.(editor|window)' }
if ($open) {
    Write-Host 'Close MangaTCT first - two copies would both write the same project.'
    exit 1
}
$docs = Join-Path $HOME 'Documents'
if (-not (Test-Path $docs)) { $docs = $HOME }
$out = Join-Path $docs 'MangaTCT\out'
$logs = Join-Path $env:LOCALAPPDATA 'MangaTCT\logs'
New-Item -ItemType Directory -Force $logs | Out-Null

# The window waits for the editor's port itself, the way launcher 1.0.4 starts it.
$env:MANGATCT_WINDOW_WAITS = '90'
$editor = Start-Process -FilePath $rt -PassThru -WindowStyle Hidden `
    -WorkingDirectory $parent `
    -RedirectStandardOutput (Join-Path $logs 'editor-local.log') `
    -RedirectStandardError (Join-Path $logs 'editor-local.err.log') `
    -ArgumentList @('-m', 'mangatl.editor', '--port', "$port", '--no-browser',
                    '--output', "`"$out`"")
try {
    Start-Process -FilePath $rt -Wait -WorkingDirectory $parent `
        -ArgumentList @('-m', 'mangatl.window', '--port', "$port",
                        '--title', '"MangaTCT (local)"')
}
finally {
    if (-not $editor.HasExited) { Stop-Process -Id $editor.Id -Force }
}
