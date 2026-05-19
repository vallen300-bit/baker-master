#!/usr/bin/env bash
# eval_gate.sh — run the director-facing-filter pytest suite and emit a one-line
# PASS/FAIL summary. Wired into Cortex M4 model-bump eval gate.

set -u
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT" || exit 2

OUTPUT="$(python3 -m pytest tests/test_director_facing_filter_v1.py -q 2>&1)"
RC=$?

if [ "$RC" -eq 0 ]; then
    SUMMARY="$(echo "$OUTPUT" | grep -E '^[0-9]+ passed' | tail -1)"
    echo "director-facing-filter eval_gate: PASS — ${SUMMARY:-all green}"
    exit 0
else
    echo "director-facing-filter eval_gate: FAIL (pytest rc=$RC)"
    echo "$OUTPUT" | tail -15
    exit 1
fi
