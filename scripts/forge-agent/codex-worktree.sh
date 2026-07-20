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
  local alias="${1:-}" root worktree status stash_hash name ref stamp archive
  local found=0 saved=0 archived=0 failed=0 root_seen=0 repo_seen=0
  local log_file="${FORGE_AUTOSAVE_LOG:-$HOME/forge-agent/lifecycle-autosave.log}"
  local archive_root="${FORGE_AUTOSAVE_DIR:-$HOME/forge-agent/autosave}"
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

      # `git stash create` snapshots tracked changes without mutating the
      # checkout. Keep the object reachable under a durable WIP ref.
      stash_hash="$(git -C "$worktree" stash create "$ref" 2>/dev/null || true)"
      if [ -n "$stash_hash" ] && git -C "$worktree" update-ref "$ref" "$stash_hash" >/dev/null 2>&1; then
        saved=$((saved + 1))
      elif [ -n "$stash_hash" ]; then
        failed=$((failed + 1))
      fi

      # `stash create` excludes untracked files. Archive those separately,
      # still without touching the live checkout.
      archive="$archive_root/$alias/${stamp}-${name}.tar.gz"
      if python3 - "$worktree" "$archive" <<'PY'
import subprocess
import sys
import tarfile
from pathlib import Path

root = Path(sys.argv[1]).resolve()
archive = Path(sys.argv[2])
try:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    paths = [Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]
    if not paths:
        raise SystemExit(0)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as bundle:
        for relative in paths:
            candidate = (root / relative).resolve()
            if candidate == root or root not in candidate.parents:
                raise RuntimeError("untracked path escaped worktree")
            bundle.add(candidate, arcname=str(relative), recursive=True)
except Exception:
    raise SystemExit(1)
PY
      then
        [ -f "$archive" ] && archived=$((archived + 1))
      else
        # No untracked files is a successful no-op; archive errors are real
        # failures and keep the lifecycle id unacknowledged for retry.
        if [ -n "$(git -C "$worktree" ls-files --others --exclude-standard 2>/dev/null | sed -n '1p')" ]; then
          failed=$((failed + 1))
        fi
      fi
    done
  done < <(codex_worktree_roots "$alias")

  printf '%s autosave alias=%s found=%s saved=%s archived=%s failed=%s\n' \
    "$(date -u +%FT%TZ 2>/dev/null || printf 'unknown')" \
    "$alias" "$found" "$saved" "$archived" "$failed" >> "$log_file" 2>/dev/null || true
  if [ "$failed" -gt 0 ]; then
    return 1
  fi
  # No configured/discovered worktrees is a handled no-op, not a retry loop.
  return 0
}
