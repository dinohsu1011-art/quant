#!/bin/bash
# Publish docs/ to the gh-pages branch as a single force-replaced commit.
#
# The cube is ~28 MB of dense numeric JS that git cannot delta (measured: 82 of
# 83 blobs stored in full even at --window=250), so versioning a daily rebuild
# would add ~9 MB/day — about 2.3 GB a year — to a public repo. Instead the site
# is published as a history-free branch: every deploy replaces it wholesale, so
# the published payload costs one commit's worth of space, permanently.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$REPO/docs"
REMOTE="github.com/dinohsu1011-art/quant.git"
GH="$(command -v gh || echo /opt/homebrew/bin/gh)"

die() { echo "deploy aborted: $*" >&2; exit 1; }

# Never force-push a broken or half-written site over a working one.
[ -s "$SITE/market-lab.html" ]       || die "docs/market-lab.html missing or empty"
[ -s "$SITE/market-lab-themes.html" ] || die "docs/market-lab-themes.html missing or empty"
[ -s "$SITE/cube/index.js" ]          || die "docs/cube/index.js missing or empty"
shards=$(find "$SITE/cube" -name '*.js' | wc -l | tr -d ' ')
[ "$shards" -ge 80 ] || die "only $shards cube shards, expected >= 80"
mb=$(du -sm "$SITE" | cut -f1)
[ "$mb" -ge 20 ] || die "docs/ is only ${mb} MB, expected >= 20"

token="$("$GH" auth token 2>/dev/null)" || die "gh auth token failed"
[ -n "$token" ] || die "no gh token"

as_of=$(grep -o '"as_of":"[^"]*"' "$SITE/cube/index.js" | head -1 | cut -d'"' -f4)
tmp=$(mktemp -d) || die "mktemp failed"
trap 'rm -rf "$tmp"' EXIT

cp -R "$SITE"/. "$tmp"/ || die "copy failed"
cd "$tmp" || die "cd failed"
touch .nojekyll   # stop Jekyll from swallowing files, and skip its build entirely

git init -q -b gh-pages                                   || die "git init failed"
git add -A                                                || die "git add failed"
git -c user.name="quant-daily" -c user.email="quant-daily@localhost" \
    commit -q -m "site as of ${as_of:-unknown}"           || die "commit failed"
git push -q --force "https://x-access-token:${token}@${REMOTE}" gh-pages \
                                                          || die "push failed"

echo "deployed site as of ${as_of:-unknown} (${mb} MB, ${shards} shards) -> gh-pages"
