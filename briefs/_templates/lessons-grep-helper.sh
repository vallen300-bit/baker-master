#!/usr/bin/env bash
# lessons-grep-helper.sh — rank tasks/lessons.md entries by keyword overlap with a PR diff.
# Usage: bash lessons-grep-helper.sh <pr_number|branch>. Deps: gh, git, grep, awk, comm.
# Ranking is token-intersection only — candidate list for B2 review attention, not a gate.
# Migrates to ~/baker-vault/_ops/processes/baker-review/ when SOT_OBSIDIAN_UNIFICATION_1 Phase B ships.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
LESSONS="${REPO_ROOT}/tasks/lessons.md"
TARGET="${1:?usage: $0 <pr_number|branch>}"

if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
  DIFF="$(gh pr diff "$TARGET")"
  LABEL="PR #${TARGET}"
  HEAD_SHA="$(gh pr view "$TARGET" --json headRefOid -q .headRefOid 2>/dev/null | cut -c1-7 || echo "unknown")"
else
  DIFF="$(git diff "main...${TARGET}")"
  LABEL="branch ${TARGET}"
  HEAD_SHA="$(git rev-parse --short "$TARGET")"
fi

DIFF_TOKENS="$(echo "$DIFF" | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z_][a-z_]{5,}' | sort -u)"
DIFF_FILES="$(echo "$DIFF" | grep -E '^\+\+\+ b/' | cut -c7- | grep -v '^/dev/null' | sort -u || true)"

RANKED="$(mktemp)"; trap 'rm -f "$RANKED"' EXIT

awk '/^### [0-9]+\./{if(num!="")print num"\t"title"\t"body; num=$2; sub(/\.$/,"",num); title=$0; sub(/^### [0-9]+\. /,"",title); sub(/ \([0-9\/-]+\)$/,"",title); body=""; next}{body=body" "$0}END{if(num!="")print num"\t"title"\t"body}' "$LESSONS" | \
while IFS=$'\t' read -r num title body; do
  lesson_tokens="$(echo "$body" | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z_][a-z_]{5,}' | sort -u)"
  score=$(comm -12 <(echo "$DIFF_TOKENS") <(echo "$lesson_tokens") | wc -l | tr -d ' ')
  [ "$score" -gt 0 ] && printf '%s\t%s\t%s\n' "$score" "$num" "$title"
done | sort -rn -k1 -k2 | head -5 > "$RANKED"

echo "[lessons-grep] Top 5 lessons for ${LABEL} (head ${HEAD_SHA}):"
echo
if [ ! -s "$RANKED" ]; then
  echo "  (no token overlap — diff is likely docs/config-only or scoped to tokens <6 chars)"
else
  awk -F'\t' '{printf "  #%s (score %s) — %s\n", $2, $1, $3}' "$RANKED"
  echo; echo "  Candidate files in diff:"
  echo "${DIFF_FILES:-  (none)}" | sed 's/^/    /'
fi
