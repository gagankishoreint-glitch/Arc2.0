#!/usr/bin/env bash
# Push ARC to a fresh GitHub repository under YOUR account.
# Prereq: GitHub CLI (`gh`) installed and logged in  -  OR  -  create the repo
# on github.com first and this script just pushes.
set -euo pipefail
cd "$(dirname "$0")"

REPO_NAME="${1:-arc}"
REMOTE_URL=""

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "Creating private repo $REPO_NAME with gh ..."
  gh repo create "$REPO_NAME" --private --source=. --remote=origin --push 2>/dev/null \
    || gh repo create "$REPO_NAME" --public --source=. --remote=origin --push
  echo "Done: $(gh repo view --json url -q .url)"
else
  echo "GitHub CLI not available."
  echo "1) Create an empty repo named '$REPO_NAME' on github.com (no README)."
  echo "2) Then run:"
  echo "     git remote add origin https://github.com/<YOUR-USERNAME>/$REPO_NAME.git"
  echo "     git push -u origin main"
  exit 1
fi
