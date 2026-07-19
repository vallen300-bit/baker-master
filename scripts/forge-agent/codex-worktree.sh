#!/usr/bin/env bash
# Shared Codex-family worktree helpers.
#
# This file is sourced by the heartbeat ticker and lifecycle watcher. It does
# not print worktree contents or branch names; callers only receive booleans
# and bounded autosave counts.

is_codex_family() {
  case "${1:-}" in
    codex|deputy-codex) return 0 ;;
    *) return 1 ;;
  esac
}

codex_worktree_roots() {
  if [ -n "${FORGE_CODEX_WORKTREE_ROOTS:-}" ]; then
    printf '%s\n' "$FORGE_CODEX_WORKTREE_ROOTS" | tr ':' '\n'
    return 0
  fi

  case "${1:-}" in
    deputy-codex) printf '%s\n' "$HOME/bm-aihead2/.codex-worktrees" ;;
    codex) printf '%s\n' "$HOME/baker-vault/.codex-worktrees" ;;
  esac
}

# Exit 0 when a dirty worktree is found, 1 when all discovered worktrees are
# clean, and 2 when the configured scan cannot be trusted.
codex_worktree_dirty() {
  local alias="${1:-}" root worktree status
  local root_seen=0 repo_seen=0

  while IFS= read -r root; do
    [ -n "$root" ] || continue
    root_seen=1
    [ -d "$root" ] || continue
    for worktree in "$root"/*; do
      [ -d "$worktree" ] || continue
      git -C "$worktree" rev-parse --show-toplevel >/dev/null 2>&1 || continue
      repo_seen=1
      status="$(git -C "$worktree" status --porcelain --untracked-files=normal 2>/dev/null)" || return 2
      [ -n "$status" ] && return 0
    done
  done < <(codex_worktree_roots "$alias")

  if [ "$root_seen" -eq 0 ] || [ "$repo_seen" -eq 0 ]; then
    return 2
  fi
  return 1
}

codex_autosave_dirty_worktrees() {
  local alias="${1:-}" root worktree status stash_hash name ref stamp
  local found=0 saved=0 failed=0 root_seen=0 repo_seen=0
  local log_file="${FORGE_AUTOSAVE_LOG:-$HOME/forge-agent/lifecycle-autosave.log}"
  stamp="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || printf 'unknown')"

  while IFS= read -r root; do
    [ -n "$root" ] || continue
    root_seen=1
    [ -d "$root" ] || continue
    for worktree in "$root"/*; do
      [ -d "$worktree" ] || continue
      git -C "$worktree" rev-parse --show-toplevel >/dev/null 2>&1 || continue
      repo_seen=1
      status="$(git -C "$worktree" status --porcelain --untracked-files=normal 2>/dev/null)" || {
        failed=$((failed + 1))
        continue
      }
      [ -n "$status" ] || continue

      found=$((found + 1))
      name="${worktree##*/}"
      name="$(printf '%s' "$name" | tr -c 'A-Za-z0-9._-' '-')"
      ref="refs/wip/autosave-${stamp}-${alias}-${name}"
      if git -C "$worktree" stash push --include-untracked \
          --message="${ref#refs/}" >/dev/null 2>&1; then
        stash_hash="$(git -C "$worktree" rev-parse --verify refs/stash 2>/dev/null || true)"
        if [ -n "$stash_hash" ]; then
          git -C "$worktree" update-ref "$ref" "$stash_hash" >/dev/null 2>&1 || true
        fi
        saved=$((saved + 1))
      else
        failed=$((failed + 1))
      fi
    done
  done < <(codex_worktree_roots "$alias")

  printf '%s autosave alias=%s found=%s saved=%s failed=%s\n' \
    "$(date -u +%FT%TZ 2>/dev/null || printf 'unknown')" \
    "$alias" "$found" "$saved" "$failed" >> "$log_file" 2>/dev/null || true
  if [ "$root_seen" -eq 0 ] || [ "$repo_seen" -eq 0 ] || [ "$failed" -gt 0 ]; then
    return 1
  fi
  return 0
}
