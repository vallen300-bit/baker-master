#!/usr/bin/env bash
# Install the tracked Codex review wrapper and its worktree helper.
#
# Run from any checkout containing this script:
#   scripts/install-codex-verify.sh
#
# The repository copies are canonical. The files under ~/.local/bin are
# installed artifacts and are replaced atomically on every run.

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
INSTALL_DIR="${CODEX_VERIFY_INSTALL_DIR:-$HOME/.local/bin}"

install_one() {
    local source="$1"
    local target="$2"
    local temp

    [ -f "$source" ] || {
        echo "install-codex-verify: missing source: $source" >&2
        exit 1
    }
    mkdir -p "$INSTALL_DIR"
    temp="$(mktemp "$INSTALL_DIR/.codex-verify.XXXXXX")"
    cp -p "$source" "$temp"
    chmod 755 "$temp"
    mv -f "$temp" "$target"
}

install_one "$SCRIPT_DIR/codex-review-worktree.sh" "$INSTALL_DIR/codex-review-worktree.sh"
install_one "$SCRIPT_DIR/codex-verify" "$INSTALL_DIR/codex-verify"

echo "installed: $INSTALL_DIR/codex-review-worktree.sh"
echo "installed: $INSTALL_DIR/codex-verify"
echo "zshrc: cv/cvr/cdx entrypoints remain user-global and resolve codex-verify by PATH"
