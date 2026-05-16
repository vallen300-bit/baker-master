#!/usr/bin/env bash
# BAKER_WA_DIRECTOR_FILTER_1 — fail if any send_whatsapp() OR
# send_director_alert() call that could resolve to chat_id=DIRECTOR_WHATSAPP
# (i.e., uses the default / Director-bound chat_id) is missing a kind= keyword.
#
# Heuristic (line-level, no AST):
#   1. Find `send_whatsapp(` or `send_director_alert(` calls, excluding the
#      `_send_whatsapp` private method on orchestrator/agent.py via an explicit
#      non-word-char prefix (ERE; portable across BSD + GNU grep — no `-P`).
#   2. Drop the canonical definitions (`def send_whatsapp` / `def
#      send_director_alert`) and import lines.
#   3. Drop lines where the function name appears INSIDE a string literal or
#      a backticked docstring reference (any of `, ', " appears anywhere
#      before the call on the same line — Python source).
#   4. Drop lines with `chat_id=` (caller targets a non-Director number;
#      only meaningful for `send_whatsapp` — `send_director_alert` has no
#      `chat_id=` parameter) or `kind=` (caller passes the allowlist kind).
#
# Excludes Cowork worktree clones under `.claude/` (AH1 / AH2 / B-code clones
# can leave a `.claude/worktrees/...` checkout inside the repo root that
# would otherwise double-count the same source lines as new violations).
#
# False positives that survive: a real call written like
#   `logger.info("done"); send_whatsapp("text")`
# would be dropped. Rule is "one logical statement per line" — the codebase
# already follows this; flag any new violation in review, don't loosen here.
#
# Anchor: Director directive 2026-05-15 — "Baker NEVER WhatsApps me about its
# own internal infrastructure." Phase A (PR #206) killed the watchdog; this
# guard makes the rule structural across all future callers. Second-symbol
# (send_director_alert) added 2026-05-16 after AH1 REQUEST_CHANGES on PR #208
# surfaced an untagged caller at kbl/logging.py:169.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Step 1 + 2: grep all callers, exclude tests + canonical senders + imports.
RAW="$(grep -rnE '(^|[^A-Za-z0-9_])(send_whatsapp|send_director_alert)\(' \
    --include='*.py' \
    --exclude-dir=tests \
    --exclude-dir=.venv \
    --exclude-dir='.venv*' \
    --exclude-dir=__pycache__ \
    --exclude-dir='.claude' \
    "$REPO_ROOT" \
  | grep -v 'def send_whatsapp' \
  | grep -v 'def send_director_alert' \
  | grep -v 'import send_whatsapp' \
  | grep -v 'import send_director_alert' \
  | grep -v 'from outputs.whatsapp_sender' \
  | grep -v 'from kbl.whatsapp' \
  || true)"

# Steps 3 + 4: drop string/docstring/backticked references + tagged calls.
# Pipe RAW through a python filter via env var (avoids heredoc quoting hell).
SUSPECT="$(WA_CHECK_RAW="$RAW" python3 "$REPO_ROOT/scripts/_check_wa_kinds_filter.py")"

if [ -n "$SUSPECT" ]; then
    echo "ERROR: Director-defaulting send_whatsapp() calls missing kind=:" >&2
    echo "$SUSPECT" >&2
    echo "" >&2
    echo "Add an explicit kind=\"<allowlisted-value>\" or chat_id=\"<non-Director>\"." >&2
    echo "Allowlist: counterparty / legal_threat / deadline / vip_signal / financial / director_inbound" >&2
    echo "Reference: outputs/whatsapp_sender.py DIRECTOR_WA_ALLOWED_KINDS" >&2
    exit 1
fi
echo "OK: all send_whatsapp() callers tag kind= or non-Director chat_id."
