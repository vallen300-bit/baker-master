#!/usr/bin/env bash
# claude_md_restructure_rollback.sh — Director-only manual fire. <5 min RTO target.
#
# Reverses the CLAUDE.md three-tier restructure migration. Restores:
#   - Tier 1 (~/.claude/CLAUDE.md) from .bak.20260429 if present, else removes.
#   - Tier 0 symlink (~/.claude/dropbox-tier0.md) — removes.
#   - Tier 2 (~/bm-b1/CLAUDE.md) + .claude/docs/* + .gitignore — via git revert + push.
#   - Tier 3 (~/bm-b1/CLAUDE.local.md) — removes (gitignored, not in revert).
#   - Pulls revert commit on all 5 sibling clones (b2/b3/b4/b5 + ~/Desktop/baker-code).
#
# Usage:
#   bash scripts/claude_md_restructure_rollback.sh confirm
#
# Idempotent: safe to re-run. Each step checks state before acting. Safe to run
# pre-migration (no-ops where appropriate).
#
# Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

set -euo pipefail

if [[ "${1:-}" != "confirm" ]]; then
  cat <<'USAGE'
Usage: bash scripts/claude_md_restructure_rollback.sh confirm

Reverses the CLAUDE.md three-tier restructure migration.
Idempotent. <5 min RTO target. Director-only.

Pass `confirm` as the first positional argument to proceed.
USAGE
  exit 1
fi

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
echo "[$(ts)] claude_md_restructure_rollback: START"

REPO="${HOME}/bm-b1"
BACKUP_DATE="20260429"
SIBLING_CLONES=("${HOME}/bm-b2" "${HOME}/bm-b3" "${HOME}/bm-b4" "${HOME}/bm-b5" "${HOME}/Desktop/baker-code")
MIGRATION_TITLE="CLAUDE.md three-tier restructure"

# --- 1. Local restore: Tier 1 (~/.claude/CLAUDE.md) -------------------------
if [[ -f "${HOME}/.claude/CLAUDE.md.bak.${BACKUP_DATE}" ]]; then
  cp "${HOME}/.claude/CLAUDE.md.bak.${BACKUP_DATE}" "${HOME}/.claude/CLAUDE.md"
  echo "[$(ts)] Tier 1 restored from .bak.${BACKUP_DATE}"
else
  rm -f "${HOME}/.claude/CLAUDE.md"
  echo "[$(ts)] Tier 1 removed (no .bak; assumed didn't exist pre-migration)"
fi

# --- 2. Local restore: Tier 0 symlink ---------------------------------------
rm -f "${HOME}/.claude/dropbox-tier0.md"
echo "[$(ts)] Tier 0 symlink removed (idempotent)"

# --- 3. Local restore: Tier 3 (~/bm-b1/CLAUDE.local.md) ---------------------
rm -f "${REPO}/CLAUDE.local.md"
echo "[$(ts)] Tier 3 (CLAUDE.local.md) removed (idempotent)"

# --- 4. Git revert in bm-b1 -------------------------------------------------
cd "${REPO}"

# Ensure clean working tree before reverting
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[$(ts)] [ERROR] working tree dirty — commit/stash before rollback" >&2
  git status --short >&2
  exit 2
fi

# Pull latest origin/main so we revert against current state
git fetch origin main >/dev/null 2>&1 || true
git checkout main >/dev/null 2>&1 || true
git pull --ff-only origin main >/dev/null 2>&1 || true

MIGRATION_HASH=$(git log --grep="${MIGRATION_TITLE}" --format=%H -1 origin/main 2>/dev/null || true)
if [[ -z "${MIGRATION_HASH}" ]]; then
  echo "[$(ts)] [INFO] no migration commit found on origin/main — git step is no-op"
else
  REVERT_HASH=$(git log --grep="Revert .*${MIGRATION_TITLE}" --format=%H -1 origin/main 2>/dev/null || true)
  if [[ -n "${REVERT_HASH}" ]] && git merge-base --is-ancestor "${MIGRATION_HASH}" "${REVERT_HASH}" 2>/dev/null; then
    echo "[$(ts)] migration ${MIGRATION_HASH:0:7} already reverted by ${REVERT_HASH:0:7}; skipping new revert"
  else
    git revert --no-edit "${MIGRATION_HASH}"
    if ! git push origin main; then
      echo "[$(ts)] [ERROR] push rejected — local revert committed but origin not updated" >&2
      echo "[$(ts)] [ERROR] Recovery: cd ${REPO} && git pull --rebase origin main && git push origin main" >&2
      exit 3
    fi
    echo "[$(ts)] reverted + pushed migration ${MIGRATION_HASH:0:7}"
  fi
fi

# --- 5. Pull revert on sibling clones ---------------------------------------
for d in "${SIBLING_CLONES[@]}"; do
  if [[ -d "${d}/.git" ]]; then
    if ( cd "${d}" && git pull --ff-only origin main >/dev/null 2>&1 ); then
      echo "[$(ts)] pulled revert in ${d}"
    else
      echo "[$(ts)] [WARN] pull failed in ${d} — manual cleanup needed (likely uncommitted local changes)"
    fi
  else
    echo "[$(ts)] [INFO] ${d} skipped (not a clone)"
  fi
done

# --- 6. Verify state (eye-check) --------------------------------------------
echo ""
echo "[$(ts)] === VERIFICATION (eye-check) ==="
echo "  Local Tier files:"
for f in "${HOME}/.claude/CLAUDE.md" "${HOME}/.claude/dropbox-tier0.md" "${REPO}/CLAUDE.md" "${REPO}/CLAUDE.local.md"; do
  if [[ -e "${f}" || -L "${f}" ]]; then
    ls -la "${f}" 2>/dev/null | sed 's/^/    /'
  else
    echo "    (absent) ${f}"
  fi
done
echo ""
echo "  Recent commits on main:"
( cd "${REPO}" && git log --oneline -5 | sed 's/^/    /' )
echo ""

echo "[$(ts)] claude_md_restructure_rollback: DONE — verify state above"
