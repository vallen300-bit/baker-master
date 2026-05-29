#!/usr/bin/env bash
# codex-psql.sh — codex queries Baker Neon DB as read-only role, credential-safe.
# Fetches CODEX_NEON_READONLY URL from 1Password internally. Role enforces
# read-only at the DB level (USAGE on schema + SELECT on all tables; no
# INSERT / UPDATE / DELETE / CREATE / DROP grants).
#
# Usage: bash ~/bm-aihead1/scripts/codex-psql.sh "<sql>" [psql-flags]
# Example: bash ~/bm-aihead1/scripts/codex-psql.sh "\d capability_sets"
#          bash ~/bm-aihead1/scripts/codex-psql.sh "SELECT count(*) FROM signal_queue;"
#
# Director-ratified 2026-05-29 codex install Phase 2 §Surface 1.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 \"<sql>\" [extra psql flags]" >&2
  exit 1
fi

SQL="$1"
shift

# Locate psql binary — libpq is keg-only on Homebrew, lives under /opt/homebrew/opt/libpq/bin/
PSQL=""
for P in \
    "/opt/homebrew/opt/libpq/bin/psql" \
    "/usr/local/opt/libpq/bin/psql" \
    "/opt/homebrew/bin/psql" \
    "/usr/local/bin/psql" \
    "$(command -v psql 2>/dev/null || true)"; do
  if [[ -x "$P" ]]; then
    PSQL="$P"
    break
  fi
done

if [[ -z "$PSQL" ]]; then
  echo "ERROR: psql binary not found. Install via 'brew install libpq'." >&2
  exit 2
fi

DBURL="${CODEX_NEON_READONLY_URL:-}"
if [[ -z "$DBURL" ]] && command -v op >/dev/null 2>&1; then
  DBURL="$(op read 'op://Baker API Keys/CODEX_NEON_READONLY/credential' 2>/dev/null || true)"
fi

if [[ -z "$DBURL" ]]; then
  echo "ERROR: CODEX_NEON_READONLY_URL not in env and 1P unreachable." >&2
  echo "       Relaunch via 'cdx' (it pre-fetches) or run 'op signin'." >&2
  exit 3
fi

# Guard at script level too: refuse SQL that contains obvious write keywords.
# Belt-and-suspenders with the DB-level revoke — same defence twice.
SQL_UC="$(printf '%s' "$SQL" | tr '[:lower:]' '[:upper:]')"
for KEYWORD in INSERT UPDATE DELETE DROP TRUNCATE CREATE GRANT REVOKE ALTER COPY; do
  if [[ "$SQL_UC" == *"$KEYWORD"* ]]; then
    echo "ERROR: '$KEYWORD' detected in SQL — codex is read-only; rerun as SELECT or ask AH1 to execute." >&2
    exit 4
  fi
done

exec "$PSQL" "$DBURL" -c "$SQL" "$@"
