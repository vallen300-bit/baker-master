#!/bin/bash
# SessionEnd — PINNED.md hot-layer size guard (deputy/AH2).
# The delete-on-resolve rule drifts silently when nothing measures it; this warns
# loudly at every close so resolved sections get pruned instead of accumulating.
# Informational only — NEVER blocks session close.
# Anchor: Director 2026-07-04 "will it be a permanent fix?" — prune alone is a mop; this is the guard.
set +e
PIN=/Users/dimitry/baker-vault/_ops/agents/aihead2/PINNED.md
[ -f "$PIN" ] || exit 0

WORDS=$(wc -w < "$PIN" | tr -d ' ')
STOPS=$(grep -c '^## SESSION STOP-POINT' "$PIN" 2>/dev/null || echo 0)
WORD_CAP=1500
STOP_CAP=3

BREACH=0
if [ "$WORDS" -gt "$WORD_CAP" ]; then BREACH=1; fi
if [ "$STOPS" -gt "$STOP_CAP" ]; then BREACH=1; fi

if [ "$BREACH" -eq 1 ]; then
  echo ""
  echo "[AH2 pin-size] WARNING — PINNED.md hot layer over cap:"
  echo "  words: $WORDS (cap $WORD_CAP)   stop-points: $STOPS (cap $STOP_CAP)"
  echo "  Delete-on-resolve: prune resolved SESSION STOP-POINTs + resolved §-sections before close."
  echo "  Keep only §A + live sections + persistent standing lanes (§V2). Detail belongs in handover-archive/."
fi
exit 0
