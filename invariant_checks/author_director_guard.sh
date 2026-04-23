#!/usr/bin/env bash
# CHANDA invariant #4 — author:director files untouched by agents.
#
# Runs as pre-commit hook. Scans staged diff for any file that either
# (a) currently has `author: director` YAML frontmatter in the staged
#     version, OR
# (b) had it in HEAD (pre-commit version) — catches frontmatter-toggle
#     bypass attempts.
#
# Agents may mutate these files ONLY when the commit message contains
# a `Director-signed:` marker with a quote of Director's plain-English
# instruction (ratified 2026-04-23). No marker → reject the commit.
#
# Exit 0 = allow; Exit 1 = reject.

set -euo pipefail

# --- 1. Collect staged files (added, modified, renamed) -------------------
CHANGED_FILES=$(git diff --cached --name-only --diff-filter=AMR 2>/dev/null || true)
if [ -z "$CHANGED_FILES" ]; then
  exit 0
fi

# --- 2. Filter to candidates — .md files only (frontmatter is YAML-in-MD) --
MD_FILES=$(echo "$CHANGED_FILES" | grep -E '\.md$' || true)
if [ -z "$MD_FILES" ]; then
  exit 0
fi

# --- 3. For each .md file: is it Director-authored (pre or post)? ---------
PROTECTED_HITS=""
for f in $MD_FILES; do
  # (a) staged version — does it declare author: director in frontmatter?
  STAGED_HIT=$(git show ":$f" 2>/dev/null | \
    awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}' || true)

  # (b) pre-version (HEAD) — did it previously declare author: director?
  #     (Catches frontmatter-toggle bypass: delete `author: director`,
  #     then edit, then re-add — this catches the middle step.)
  PRE_HIT=""
  if git cat-file -e "HEAD:$f" 2>/dev/null; then
    PRE_HIT=$(git show "HEAD:$f" 2>/dev/null | \
      awk '/^---[[:space:]]*$/{ctr++; next} ctr==1 && /^author:[[:space:]]*director[[:space:]]*$/{print "HIT"; exit}' || true)
  fi

  if [ -n "$STAGED_HIT" ] || [ -n "$PRE_HIT" ]; then
    PROTECTED_HITS="${PROTECTED_HITS}${f}\n"
  fi
done

if [ -z "$PROTECTED_HITS" ]; then
  exit 0
fi

# --- 4. Protected file(s) being touched. Commit message must carry marker. -
# Commit message source for pre-commit: $1 if called by git's pre-commit
# via COMMIT_EDITMSG (older style), else read current commit message file.
COMMIT_MSG_FILE="${1:-.git/COMMIT_EDITMSG}"
if [ ! -f "$COMMIT_MSG_FILE" ]; then
  echo "CHANDA #4: cannot read commit message file ($COMMIT_MSG_FILE)."
  echo "This script must run as a pre-commit hook receiving the message path."
  exit 1
fi

MARKER=$(grep -E '^Director-signed:[[:space:]]*"' "$COMMIT_MSG_FILE" 2>/dev/null || true)
if [ -n "$MARKER" ]; then
  # Director-signed marker present + non-empty quote. Allow.
  exit 0
fi

# --- 5. No marker: reject with plain-English explanation -----------------
echo ""
echo "=============================================================="
echo "CHANDA invariant #4 — author:director files untouched by agents"
echo "=============================================================="
echo ""
echo "This commit mutates Director-authored file(s):"
echo -e "$PROTECTED_HITS"
echo "Agents may only commit changes to 'author: director' files when"
echo "the commit message carries a 'Director-signed:' marker with a"
echo "quoted plain-English instruction from Director."
echo ""
echo "Example acceptable commit message:"
echo "    wiki(hot.md): update Monday focus"
echo ""
echo "    Director-signed: \"rewrite hot.md — this week focus is M0 quintet\""
echo ""
echo "Per 2026-04-23 ratification: intent-based, not identity-based."
echo "=============================================================="
exit 1
