#!/usr/bin/env bash
# deploy_to_user_global.sh — cp canonical hook fixtures → ~/.claude/hooks/.
# Run post-merge from baker-master repo root after `git pull --rebase origin main`.

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/tests/fixtures/director-facing-filter/hooks"
DST="$HOME/.claude/hooks"
PACKS_DST="$DST/packs"

mkdir -p "$DST" "$PACKS_DST"

for f in "$SRC"/*.sh; do
    cp "$f" "$DST/"
    chmod +x "$DST/$(basename "$f")"
    echo "deployed: $DST/$(basename "$f")"
done

# Synthesis-markers pack
cp "$REPO_ROOT/tests/fixtures/director-facing-filter/packs/synthesis-markers.txt" "$PACKS_DST/"
echo "deployed pack: $PACKS_DST/synthesis-markers.txt"

# Also redeploy recommendation-check.sh (Component 6a reentrancy patch ships in same PR).
cp "$REPO_ROOT/tests/fixtures/recommendation-check.sh" "$DST/"
chmod +x "$DST/recommendation-check.sh"
echo "deployed (patched): $DST/recommendation-check.sh"

echo ""
echo "ALL DEPLOYED. Next: python3 $REPO_ROOT/tests/fixtures/director-facing-filter/scripts/update_user_settings.py"
