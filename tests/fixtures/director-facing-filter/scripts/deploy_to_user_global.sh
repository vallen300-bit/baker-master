#!/usr/bin/env bash
# deploy_to_user_global.sh — cp canonical hook fixtures → ~/.claude/hooks/.
# Run post-merge from baker-master repo root after `git pull --rebase origin main`.
# Phase 2 (v1.1): also stages lib/ (call_validator.py) + skills/ (validator
# SKILL.md files) + pip-installs the runtime Python deps.

set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/tests/fixtures/director-facing-filter/hooks"
LIB_SRC="$REPO_ROOT/tests/fixtures/director-facing-filter/lib"
SKILLS_SRC="$REPO_ROOT/tests/fixtures/director-facing-filter/skills"
DST="$HOME/.claude/hooks"
LIB_DST="$DST/lib"
PACKS_DST="$DST/packs"
SKILLS_DST="$HOME/.claude/skills"

mkdir -p "$DST" "$LIB_DST" "$PACKS_DST" "$SKILLS_DST"

for f in "$SRC"/*.sh; do
    cp "$f" "$DST/"
    chmod +x "$DST/$(basename "$f")"
    echo "deployed: $DST/$(basename "$f")"
done

# Phase 2: lib/ — call_validator.py + __init__.py
for f in "$LIB_SRC"/*.py; do
    cp "$f" "$LIB_DST/"
    echo "deployed: $LIB_DST/$(basename "$f")"
done

# Phase 2: validator skill files
for skill_dir in "$SKILLS_SRC"/*/; do
    name="$(basename "$skill_dir")"
    mkdir -p "$SKILLS_DST/$name"
    cp "$skill_dir"*.md "$SKILLS_DST/$name/" 2>/dev/null || true
    echo "deployed skill: $SKILLS_DST/$name/"
done

# Synthesis-markers pack
cp "$REPO_ROOT/tests/fixtures/director-facing-filter/packs/synthesis-markers.txt" "$PACKS_DST/"
echo "deployed pack: $PACKS_DST/synthesis-markers.txt"

# Also redeploy recommendation-check.sh (Phase 1 reentrancy patch ships in same PR).
cp "$REPO_ROOT/tests/fixtures/recommendation-check.sh" "$DST/"
chmod +x "$DST/recommendation-check.sh"
echo "deployed (patched): $DST/recommendation-check.sh"

# Phase 2: pip-install runtime deps for hook Python env (idempotent — pip
# skips already-installed). --user keeps it out of system site-packages.
echo ""
echo "Installing hook Python deps (anthropic + pyyaml) — idempotent..."
pip3 install --user --quiet anthropic pyyaml || {
    echo "WARN: pip3 install failed. Validator hooks will degrade to PASS until anthropic SDK is importable from the hook Python env."
    echo "      Manual fix: pip3 install --user anthropic pyyaml"
}

echo ""
echo "ALL DEPLOYED. Next: python3 $REPO_ROOT/tests/fixtures/director-facing-filter/scripts/update_user_settings.py"
