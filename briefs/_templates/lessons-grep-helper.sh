#!/usr/bin/env bash
# lessons-grep-helper.sh v2 — rank tasks/lessons.md by IDF-weighted token overlap with a PR's +-added lines.
# Usage: bash lessons-grep-helper.sh <pr_number|branch> [--repo owner/name]
# Env:   LESSONS_FILE=<path>   override lessons.md (default: <repo_root>/tasks/lessons.md)
# Deps:  gh, git, grep, awk, sort.  Migrates to baker-vault/_ops/processes/baker-review/ in SOT Phase B.
# Smoke: PR #21→#42 in top5; PR #22→#37 in top5; PR #24→#26/#33 in top5; bv#3 (scaffold)→fallback fires.
set -euo pipefail

REPO_FLAG=""; TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO_FLAG="--repo $2"; shift 2 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) [ -z "$TARGET" ] && TARGET="$1" || { echo "unknown arg: $1" >&2; exit 2; }; shift ;;
  esac
done
[ -n "$TARGET" ] || { echo "usage: $0 <pr_number|branch> [--repo owner/name]" >&2; exit 2; }

LESSONS="${LESSONS_FILE:-$(git rev-parse --show-toplevel)/tasks/lessons.md}"
[ -f "$LESSONS" ] || { echo "lessons file not found: $LESSONS" >&2; exit 2; }

if [[ "$TARGET" =~ ^[0-9]+$ ]]; then
  DIFF="$(gh pr diff $REPO_FLAG "$TARGET")"
  LABEL="PR #${TARGET}"
  HEAD_SHA="$(gh pr view $REPO_FLAG "$TARGET" --json headRefOid -q .headRefOid 2>/dev/null | cut -c1-7 || echo "unknown")"
else
  DIFF="$(git diff "main...${TARGET}")"; LABEL="branch ${TARGET}"; HEAD_SHA="$(git rev-parse --short "$TARGET")"
fi

ADDED="$(echo "$DIFF" | grep '^+' | grep -v '^+++' || true)"
DIFF_TOKENS="$(echo "$ADDED" | tr '[:upper:]' '[:lower:]' | grep -oE '[a-z_][a-z_]{5,}' | sort -u | tr '\n' ' ' || true)"
DIFF_FILES="$(echo "$DIFF" | grep -E '^\+\+\+ b/' | cut -c7- | grep -v '^/dev/null' | sort -u || true)"

ALL_SCORED="$(mktemp)"; RANKED="$(mktemp)"; trap 'rm -f "$ALL_SCORED" "$RANKED"' EXIT
awk -v difftokens="$DIFF_TOKENS" '
BEGIN { n=split(difftokens, a, /[ \t]+/); for (i=1;i<=n;i++) if (a[i]!="") dt[a[i]]=1 }
/^### [0-9]+\./ {
  if (num!="") bodies[cnt++] = num "\t" title "\t" body
  num=$2; sub(/\.$/,"",num)
  title=$0; sub(/^### [0-9]+\. /,"",title); sub(/ \([0-9\/-]+\)$/,"",title)
  body=""; next
}
{ body = body " " $0 }
END {
  if (num!="") bodies[cnt++] = num "\t" title "\t" body
  for (i=0;i<cnt;i++) {
    split(bodies[i], p, "\t"); t = tolower(p[3]); delete seen; nt=0
    while (match(t, /[a-z_][a-z_]{5,}/)) {
      w = substr(t, RSTART, RLENGTH); t = substr(t, RSTART+RLENGTH)
      if (!(w in seen)) { seen[w]=1; toks[i, ++nt] = w }
    }
    ntoks[i] = nt; for (j=1;j<=nt;j++) df[ toks[i,j] ]++
  }
  for (i=0;i<cnt;i++) {
    sc=0.0; for (j=1;j<=ntoks[i];j++) { w=toks[i,j]; if (w in dt) sc += log(cnt / df[w]) }
    split(bodies[i], p, "\t")
    if (sc > 0) printf "%.4f\t%s\t%s\n", sc, p[1], p[2]
  }
  printf "#TOTAL\t%d\n", cnt > "/dev/stderr"
}' "$LESSONS" 2> "$ALL_SCORED.meta" | sort -rn -k1 -k2 > "$ALL_SCORED"
head -5 "$ALL_SCORED" > "$RANKED"
HITS="$(wc -l < "$ALL_SCORED" | tr -d ' ')"
TOTAL="$(awk -F'\t' '/^#TOTAL/{print $2}' "$ALL_SCORED.meta" 2>/dev/null || echo 0)"
rm -f "$ALL_SCORED.meta"

echo "[lessons-grep] Top 5 lessons for ${LABEL} (head ${HEAD_SHA}):"; echo
# Fallback = hits cover >=80% of lessons (scaffold/docs-heavy signature). The
# brief-suggested "top < 2x bottom" rule under-fires with IDF (compressed span
# even for real-signal PRs); coverage is the cleaner empirical separator.
FALLBACK=0
[ ! -s "$RANKED" ] && FALLBACK=1
[ "$TOTAL" -gt 0 ] && [ "$HITS" -ge "$((TOTAL * 80 / 100))" ] && FALLBACK=1
if [ "$FALLBACK" = 1 ]; then
  echo "[lessons-grep] No strongly-ranked lessons for ${LABEL}."
  echo "Likely reason: PR is docs-only / scaffold-only / scope below lessons' resolution."
  echo "Fall back to manual sweep of lessons #34-42 (most recent) if PR touches production code."
else
  awk -F'\t' '{printf "  #%s (score %.2f) — %s\n", $2, $1, $3}' "$RANKED"
  echo; echo "  Candidate files in diff:"; echo "${DIFF_FILES:-  (none)}" | sed 's/^/    /'
fi
