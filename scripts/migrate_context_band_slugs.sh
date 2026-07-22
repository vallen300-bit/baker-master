#!/usr/bin/env bash
# Migrate legacy underscore-named context-band current links/files to the
# canonical cockpit slug form. This is intentionally a one-shot cleanup.

set -u
set -o pipefail

CONTEXT_BAND_DIR="${CONTEXT_BAND_DIR:-$HOME/forge-agent/context-band}"

if [[ ! -d "$CONTEXT_BAND_DIR" ]]; then
  printf 'context-band directory not found: %s\n' "$CONTEXT_BAND_DIR"
  exit 0
fi

migrated=0
failed=0

for source in "$CONTEXT_BAND_DIR"/*_*.current; do
  [[ -e "$source" || -L "$source" ]] || continue

  source_name="${source##*/}"
  canonical_name="${source_name//_/-}"
  canonical="$CONTEXT_BAND_DIR/$canonical_name"
  [[ "$source" == "$canonical" ]] && continue

  if [[ -L "$source" ]]; then
    target="$(readlink "$source" 2>/dev/null || true)"
    case "$target" in
      ""|*/*|*[!A-Za-z0-9._-]*)
        printf 'SKIP %s: unsafe symlink target\n' "$source" >&2
        failed=$((failed + 1))
        continue
        ;;
    esac
    if [[ ! -e "$CONTEXT_BAND_DIR/$target" ]]; then
      printf 'SKIP %s: target is missing\n' "$source" >&2
      failed=$((failed + 1))
      continue
    fi
    tmp="$(mktemp "$CONTEXT_BAND_DIR/.${canonical_name}.migration.XXXXXX" 2>/dev/null || true)"
    if [[ -z "$tmp" ]]; then
      printf 'SKIP %s: could not allocate temporary link\n' "$source" >&2
      failed=$((failed + 1))
      continue
    fi
    rm -f "$tmp"
    if ! ln -s "$target" "$tmp" || ! mv -f "$tmp" "$canonical"; then
      rm -f "$tmp"
      printf 'SKIP %s: could not install canonical link\n' "$source" >&2
      failed=$((failed + 1))
      continue
    fi
    rm -f "$source"
  else
    if ! mv -f "$source" "$canonical"; then
      printf 'SKIP %s: could not move canonical file\n' "$source" >&2
      failed=$((failed + 1))
      continue
    fi
  fi

  printf 'MIGRATED %s -> %s\n' "$source_name" "$canonical_name"
  migrated=$((migrated + 1))
done

printf 'context-band slug migration: migrated=%s failed=%s\n' "$migrated" "$failed"
[[ "$failed" -eq 0 ]]
