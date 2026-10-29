#!/usr/bin/env bash
# 推送到 GitHub：./push.sh [仓库地址]
# 缺省用 Sylvia-Muse/qingmeng-studio
set -euo pipefail
REMOTE="${1:-git@github.com:Sylvia-Muse/qingmeng-studio.git}"
export GIT_SSH_COMMAND="ssh -i $HOME/.ssh/id_ed25519_github -o IdentitiesOnly=yes"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi
echo "remote: $(git remote get-url origin)"
git push -u origin main || git push -u origin master
