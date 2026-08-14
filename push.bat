@echo off
REM ===================================================================
REM  MangaTCT -> GitHub, in one go.
REM
REM  Double-click it, or run it with a message:
REM      push.bat "the boxes stopped merging"
REM
REM  It stages everything git is not ignoring, commits, pulls with a
REM  rebase so your commit sits on top of anything that is already on
REM  GitHub, and pushes. Anything that goes wrong stops it before the
REM  push rather than half way through.
REM ===================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo   MangaTCT -^> GitHub
echo   ------------------

git --version >nul 2>&1
if errorlevel 1 (
  echo   ERROR: git is not on your PATH.
  echo   Install Git for Windows, or run this from Git Bash.
  goto :done
)

git rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
  echo   ERROR: this folder is not a git repository.
  goto :done
)

REM ---- which branch, and where it goes
for /f "delims=" %%B in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%B"
if "%BRANCH%"=="HEAD" (
  echo   ERROR: you are not on a branch ^(detached HEAD^).
  echo   Run:  git checkout main
  goto :done
)
echo   branch: %BRANCH%

REM ---- a lock left behind by a run that was killed, or by OneDrive
if exist ".git\index.lock" (
  echo   clearing a leftover .git\index.lock
  echo   ^(if git really is running in another window, stop this now^)
  del /f /q ".git\index.lock" >nul 2>&1
)

REM ---- the message: the argument, or asked for, or a dated one
set "MSG=%~1"
if not defined MSG set /p "MSG=  message (blank for a dated one): "
if not defined MSG (
  for /f "delims=" %%D in ('powershell -NoProfile -Command "Get-Date -Format \"yyyy-MM-dd HH:mm\""') do set "MSG=work in progress %%D"
)

REM ---- stage everything not ignored, including deletions
git add -A
if errorlevel 1 goto :failed

REM ---- anything to send? --quiet exits 1 when there IS something staged
git diff --cached --quiet
if not errorlevel 1 (
  echo.
  echo   Nothing has changed since the last push. Nothing to do.
  goto :done
)

echo.
echo   sending:
git diff --cached --stat
echo.

git commit -m "%MSG%"
if errorlevel 1 goto :failed

REM ---- put your commit on top of whatever is already up there, so the
REM      push cannot be rejected for being behind
git pull --rebase origin %BRANCH%
if errorlevel 1 (
  echo.
  echo   The rebase stopped, which means GitHub has a change that
  echo   touches the same lines as yours. Your commit is SAFE and is
  echo   still here. Sort it out with:
  echo       git status
  echo       git rebase --continue     ^(after fixing the files^)
  echo       git rebase --abort        ^(to put things back^)
  echo   then run this again.
  goto :done
)

git push origin %BRANCH%
if errorlevel 1 goto :failed

echo.
echo   Pushed to GitHub.
git log --oneline -1
goto :done

:failed
echo.
echo   Stopped: the command above failed. NOTHING was pushed.

:done
echo.
pause
endlocal
