#!/usr/bin/env bash
# BAKER_WA_DIRECTOR_FILTER_1 — fail if any send_whatsapp() call that could
# resolve to chat_id=DIRECTOR_WHATSAPP (i.e., uses the default chat_id) is
# missing a kind= keyword.
#
# Heuristic (line-level, no AST):
#   1. Find `send_whatsapp(` calls, excluding the `_send_whatsapp` private
#      method on orchestrator/agent.py via an explicit non-word-char prefix
#      (ERE; portable across BSD + GNU grep — no `-P`).
#   2. Drop the canonical definition (`def send_whatsapp`) and import lines.
#   3. Drop lines where the function name appears INSIDE a string literal or
#      a backticked docstring reference (any of `, ', " appears anywhere
#      before `send_whatsapp(` on the same line — Python source).
#   4. Drop lines with `chat_id=` (caller targets a non-Director number) or
#      `kind=` (caller passes the allowlist kind).
#
# False positives that survive: a real call written like
#   `logger.info("done"); send_whatsapp("text")`
# would be dropped. Rule is "one logical statement per line" — the codebase
# already follows this; flag any new violation in review, don't loosen here.
#
# Anchor: Director directive 2026-05-15 — "Baker NEVER WhatsApps me about its
# own internal infrastructure." Phase A (PR #206) killed the watchdog; this
# guard makes the rule structural across all future callers.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Step 1 + 2: grep all callers, exclude tests + canonical sender + imports.
RAW="$(grep -rnE '(^|[^A-Za-z0-9_])send_whatsapp\(' \
    --include='*.py' \
    --exclude-dir=tests \
    --exclude-dir=.venv \
    --exclude-dir='.venv*' \
    --exclude-dir=__pycache__ \
    "$REPO_ROOT" \
  | grep -v 'def send_whatsapp' \
  | grep -v 'import send_whatsapp' \
  | grep -v 'from outputs.whatsapp_sender' \
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
