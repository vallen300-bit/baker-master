#!/usr/bin/env bash
# install_picker_dir.sh — create the Cowork/Terminal picker folder for a fleet
# agent so it is visible to the Director's picker without hand-linking.
#
# Usage:
#   install_picker_dir.sh <slug> [--dropbox]
#
#   <slug>       agent slug, e.g. cowork-bb-desk. The picker dir is ~/bm-<slug>.
#   --dropbox    back the picker dir with a Dropbox-synced folder (cross-device):
#                create "<Dropbox>/bm-<slug>" then symlink ~/bm-<slug> -> it.
#                Without this flag the picker dir is a plain local directory.
#
# Idempotent: a second run is a no-op that reports "already wired".
#
# SAFETY: never deletes or overwrites an existing ~/bm-<slug> or Dropbox folder.
# If a real directory already occupies the symlink target, it reports what it
# found and exits 1 rather than clobbering it.
#
# BAKER_OS_V2_C1_PICKER_FOLDER_WIRING_1 (Baker OS V2 roadmap §3 C1).

set -euo pipefail

DROPBOX_ROOT="/Users/dimitry/Vallen Dropbox/Dimitry vallen"

usage() {
    echo "Usage: install_picker_dir.sh <slug> [--dropbox]" >&2
    exit 2
}

SLUG=""
DROPBOX=0
for arg in "$@"; do
    case "$arg" in
        --dropbox) DROPBOX=1 ;;
        -h|--help) usage ;;
        -*) echo "ERROR: unknown flag: $arg" >&2; usage ;;
        *)
            if [ -n "$SLUG" ]; then
                echo "ERROR: multiple slugs given ('$SLUG', '$arg')" >&2
                usage
            fi
            SLUG="$arg"
            ;;
    esac
done

[ -n "$SLUG" ] || usage

PICKER_DIR="$HOME/bm-$SLUG"

# --- checklist state, filled in as we go ---
picker_state=""
symlink_state=""

if [ "$DROPBOX" -eq 1 ]; then
    DROPBOX_DIR="$DROPBOX_ROOT/bm-$SLUG"

    # 1) validate the symlink target BEFORE any side effect: if a real dir/file
    #    already occupies ~/bm-<slug>, refuse without creating the Dropbox folder.
    if [ -e "$PICKER_DIR" ] && [ ! -L "$PICKER_DIR" ]; then
        echo "ERROR: $PICKER_DIR already exists as a real directory/file." >&2
        echo "       NOT overwriting it. Move it aside manually if you want the" >&2
        echo "       Dropbox-backed symlink here." >&2
        exit 1
    fi

    # 2) ensure the Dropbox-backed source folder exists (create-or-keep).
    if [ -d "$DROPBOX_DIR" ]; then
        picker_state="Dropbox folder already present: $DROPBOX_DIR"
    else
        mkdir -p "$DROPBOX_DIR"
        picker_state="Dropbox folder created: $DROPBOX_DIR"
    fi

    # 3) wire ~/bm-<slug> -> Dropbox folder, never clobbering a real dir.
    if [ -L "$PICKER_DIR" ]; then
        current_target="$(readlink "$PICKER_DIR")"
        if [ "$current_target" = "$DROPBOX_DIR" ]; then
            symlink_state="already wired: $PICKER_DIR -> $DROPBOX_DIR"
        else
            echo "ERROR: $PICKER_DIR is a symlink to a DIFFERENT target:" >&2
            echo "         $current_target" >&2
            echo "       expected: $DROPBOX_DIR" >&2
            echo "       Refusing to change it. Resolve by hand." >&2
            exit 1
        fi
    elif [ -e "$PICKER_DIR" ]; then
        echo "ERROR: $PICKER_DIR already exists as a real directory/file." >&2
        echo "       NOT overwriting it. Move it aside manually if you want the" >&2
        echo "       Dropbox-backed symlink here." >&2
        exit 1
    else
        ln -s "$DROPBOX_DIR" "$PICKER_DIR"
        symlink_state="symlink created: $PICKER_DIR -> $DROPBOX_DIR"
    fi
else
    # local (non-Dropbox) picker dir.
    if [ -L "$PICKER_DIR" ]; then
        picker_state="picker dir is a symlink (Dropbox-backed): $PICKER_DIR -> $(readlink "$PICKER_DIR")"
        symlink_state="left as-is (run without --dropbox does not touch existing symlinks)"
    elif [ -d "$PICKER_DIR" ]; then
        picker_state="already wired: $PICKER_DIR (local dir present)"
        symlink_state="n/a (local dir, no symlink)"
    elif [ -e "$PICKER_DIR" ]; then
        echo "ERROR: $PICKER_DIR exists but is not a directory." >&2
        exit 1
    else
        mkdir -p "$PICKER_DIR"
        picker_state="picker dir created: $PICKER_DIR"
        symlink_state="n/a (local dir, no symlink)"
    fi
fi

# --- 3-line closing checklist ---
echo "picker dir : $picker_state"
echo "symlink    : $symlink_state"
echo "next       : add '$SLUG' to _snapshot_path_for() in scripts/generate_agent_identity_artifacts.py, then run: python3 scripts/generate_agent_identity_artifacts.py --write"
