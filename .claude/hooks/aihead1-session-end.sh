#!/bin/bash
# AH1 SessionEnd — surface uncommitted baker-vault state in _ops/agents/aihead1/ scope.
# Replaces the auto-memory safety net wiped 2026-05-08 (Director-ratified, AH2 parity).
# Informational only; never blocks session close.
set +e
VAULT=/Users/dimitry/baker-vault
[ -d "$VAULT/.git" ] || exit 0
DIRTY=$(cd "$VAULT" && git status --short _ops/agents/aihead1/ 2>/dev/null)
if [ -n "$DIRTY" ]; then
  echo ""
  echo "[AH1 session-end] WARNING — uncommitted baker-vault changes under _ops/agents/aihead1/:"
  echo "$DIRTY"
  echo "[AH1 session-end] Commit + push before next session opens, or state is local-only."
fi
UNPUSHED=$(cd "$VAULT" && git log --oneline origin/main..HEAD -- _ops/agents/aihead1/ 2>/dev/null)
if [ -n "$UNPUSHED" ]; then
  echo ""
  echo "[AH1 session-end] WARNING — local-only commits in _ops/agents/aihead1/ (not pushed):"
  echo "$UNPUSHED"
fi
exit 0
