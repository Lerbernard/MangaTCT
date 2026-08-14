#!/usr/bin/env bash
# ====================================================================
#  MangaTCT -> GitHub, in one go. The Git Bash / WSL twin of push.bat.
#
#      ./push.sh "the boxes stopped merging"
#      ./push.sh                 # asks for a message
#
#  Stages everything git is not ignoring, commits, pulls with a rebase
#  so your commit sits on top of what is already on GitHub, and pushes.
#  Anything that goes wrong stops it before the push.
# ====================================================================
set -u
cd "$(dirname "$0")" || exit 1

say() { printf '  %s\n' "$*"; }
die() { printf '\n  Stopped: %s\n  NOTHING was pushed.\n\n' "$*"; exit 1; }

echo
echo "  MangaTCT -> GitHub"
echo "  ------------------"

command -v git >/dev/null 2>&1 || die "git is not on your PATH."
git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || die "this folder is not a git repository."

branch=$(git rev-parse --abbrev-ref HEAD)
[ "$branch" = "HEAD" ] && die "you are not on a branch (detached HEAD)."
say "branch: $branch"

# A lock left behind by a run that was killed, or by OneDrive.
if [ -f .git/index.lock ]; then
  say "clearing a leftover .git/index.lock"
  rm -f .git/index.lock
fi

msg="${1-}"
if [ -z "$msg" ]; then
  printf '  message (blank for a dated one): '
  read -r msg
fi
[ -z "$msg" ] && msg="work in progress $(date '+%Y-%m-%d %H:%M')"

git add -A || die "git add failed."

# --quiet exits non-zero when there IS something staged.
if git diff --cached --quiet; then
  echo
  say "Nothing has changed since the last push. Nothing to do."
  echo
  exit 0
fi

echo
say "sending:"
git diff --cached --stat
echo

git commit -m "$msg" || die "the commit failed."

if ! git pull --rebase origin "$branch"; then
  cat <<'EOF'

  The rebase stopped, which means GitHub has a change that touches the
  same lines as yours. Your commit is SAFE and is still here. Sort it
  out with:
      git status
      git rebase --continue     (after fixing the files)
      git rebase --abort        (to put things back)
  then run this again.

EOF
  exit 1
fi

git push origin "$branch" || die "the push was refused."

echo
say "Pushed to GitHub."
git log --oneline -1
echo
