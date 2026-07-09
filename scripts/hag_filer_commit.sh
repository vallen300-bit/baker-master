#!/usr/bin/env bash
# hag_filer_commit.sh — per-commit git-identity injection for hag-filer filings.
# HAG_FILER_HARNESS_RETROFIT_1 B6 (block 6); lead ruling #6549(2) RATIFIED option A:
# per-commit `git -c user.name/user.email` injection keyed off BAKER_ROLE, symmetric
# with the write-path ACL guard (both read $BAKER_ROLE). NO dedicated checkout.
#
# WHY THIS EXISTS
#   hag-filer files into the SHARED baker-vault checkout. Its filing commits were
#   authoring as the seat's default identity (b3) instead of hag-filer — a broken
#   audit trail on a live legal matter. Because the vault checkout is shared, we
#   must NOT mutate its `.git/config` (git config --local would rewrite identity for
#   every agent sharing the checkout). The correct, drift-free mechanism is
#   per-invocation `git -c` flags — identity travels with THIS commit only.
#
# WHAT IT DOES
#   Runs `git -c user.name='hag-filer worker' -c user.email='hag-filer@brisengroup.com'
#   commit "$@"` in the current repo (whatever cwd — the vault filing checkout).
#   Every remaining arg is passed straight through to `git commit` (-m, -F, -a, etc.).
#
# KEYED OFF BAKER_ROLE (fail-closed — symmetric with the guard)
#   Refuses to run unless $BAKER_ROLE == hag-filer, so no other seat can borrow the
#   hag-filer identity. Bypass for exceptional maintenance: HAG_FILER_COMMIT_FORCE=1.
#
# Usage:
#   BAKER_ROLE=hag-filer bash scripts/hag_filer_commit.sh -m "hagenauer-rg7: file <artefact>"
#   BAKER_ROLE=hag-filer bash scripts/hag_filer_commit.sh -F /path/to/msg.txt
#
# Exit: propagates git's exit code. 2 = wrong role / usage.
set -euo pipefail

FILER_NAME='hag-filer worker'
FILER_EMAIL='hag-filer@brisengroup.com'

ROLE="${BAKER_ROLE:-}"
if [ "$ROLE" != "hag-filer" ] && [ "${HAG_FILER_COMMIT_FORCE:-}" != "1" ]; then
  echo "ERROR: hag_filer_commit.sh requires BAKER_ROLE=hag-filer (got: '${ROLE:-<unset>}')." >&2
  echo "  This wrapper stamps the hag-filer filing identity; only the hag-filer seat may use it." >&2
  echo "  Override for maintenance only with HAG_FILER_COMMIT_FORCE=1." >&2
  exit 2
fi

if [ "$#" -eq 0 ]; then
  echo "Usage: BAKER_ROLE=hag-filer bash scripts/hag_filer_commit.sh <git commit args...>" >&2
  exit 2
fi

# Per-commit identity — travels with THIS commit only; never touches shared .git/config.
exec git -c user.name="$FILER_NAME" -c user.email="$FILER_EMAIL" commit "$@"
