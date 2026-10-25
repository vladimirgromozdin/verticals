#!/usr/bin/env bash
# Deploys the board from the `deploy` branch, and only as it is on GitHub: a stale worktree or a local change never
# reaches the live board. Run it from anywhere in the checkout.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
branch=deploy
remote=$(git config "branch.$branch.remote" || true)
[ -n "$remote" ] || { echo "No remote for '$branch'. Run: git branch -u <remote>/$branch $branch" >&2; exit 1; }

[ "$(git branch --show-current)" = "$branch" ] || { echo "Switch to '$branch' first." >&2; exit 1; }
git diff --quiet HEAD -- || { echo "Commit or stash the changes first: the board is built from the working tree." >&2; exit 1; }
git fetch -q "$remote" "$branch"
[ "$(git rev-parse HEAD)" = "$(git rev-parse "$remote/$branch")" ] \
  || { echo "'$branch' differs from $remote/$branch. Pull or push first." >&2; exit 1; }

cd deploy/cloudflare
[ -f wrangler.jsonc ] || { echo "deploy/cloudflare/wrangler.jsonc is missing (copy wrangler.example.jsonc)." >&2; exit 1; }
if [ "$(uname -m)" != x86_64 ] && [ ! -e /proc/sys/fs/binfmt_misc/qemu-x86_64 ] && [ "$(uname)" = Linux ]; then
  echo "Docker cannot build amd64 here. Run: docker run --privileged --rm tonistiigi/binfmt --install amd64" >&2; exit 1
fi

echo "Deploying $(git log --oneline -1 HEAD)"
npx wrangler deploy
