#!/usr/bin/env bash
# Verify on-disk migration files match migrations/applied_migrations.lock.
#
# Exit codes:
#   0 — all sha256s match (or mismatch was bypassed)
#   1 — drift detected, no bypass
#   2 — usage error or missing lock file
#
# Bypass paths (used by the .githooks/pre-commit wrapper):
#   --commit-msg-file <path>            scan <path> for "Migration-edit-authorized:" trailer
#   BAKER_MIGRATION_EDIT_AUTHORIZED=1   environment override (covers `git commit -m` flow)
#
# Standalone use (e.g. start.sh pre-flight) MUST NOT pass either, so a runtime
# divergence is always loud.
set -euo pipefail

LOCK="migrations/applied_migrations.lock"
COMMIT_MSG_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --commit-msg-file)
      if [ $# -lt 2 ]; then
        echo "[check_applied_migrations] --commit-msg-file requires a path" >&2
        exit 2
      fi
      COMMIT_MSG_FILE="$2"
      shift 2
      ;;
    -h|--help)
      sed -n '2,15p' "$0"
      exit 0
      ;;
    *)
      echo "[check_applied_migrations] unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [ ! -f "$LOCK" ]; then
  echo "[check_applied_migrations] missing $LOCK — run scripts/refresh_applied_migrations_lock.py" >&2
  exit 2
fi

# Pick a sha256 utility. macOS has `shasum`, Linux containers usually have `sha256sum`.
if command -v sha256sum >/dev/null 2>&1; then
  _sha() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  _sha() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "[check_applied_migrations] neither sha256sum nor shasum available" >&2
  exit 2
fi

mismatch=0
problems=()
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    ''|\#*) continue ;;
  esac
  expected=$(printf '%s\n' "$line" | awk '{print $1}')
  filename=$(printf '%s\n' "$line" | awk '{print $2}')
  if [ -z "$expected" ] || [ -z "$filename" ]; then
    continue
  fi
  path="migrations/$filename"
  if [ ! -f "$path" ]; then
    problems+=("missing file: $path (lock expects sha=$expected)")
    mismatch=1
    continue
  fi
  actual=$(_sha "$path" 2>/dev/null) || actual=""
  if [ -z "$actual" ]; then
    problems+=("hash tool failed on $path (sha256sum/shasum returned empty)")
    mismatch=1
    continue
  fi
  if [ "$actual" != "$expected" ]; then
    problems+=("sha256 drift: $path expected=$expected actual=$actual")
    mismatch=1
  fi
done < "$LOCK"

if [ "$mismatch" -eq 0 ]; then
  exit 0
fi

for p in "${problems[@]}"; do
  echo "[check_applied_migrations] $p" >&2
done

if [ -n "$COMMIT_MSG_FILE" ] && [ -f "$COMMIT_MSG_FILE" ]; then
  if grep -qE '^Migration-edit-authorized:' "$COMMIT_MSG_FILE"; then
    echo "[check_applied_migrations] bypass: 'Migration-edit-authorized:' trailer present in $COMMIT_MSG_FILE" >&2
    exit 0
  fi
fi

if [ "${BAKER_MIGRATION_EDIT_AUTHORIZED:-0}" = "1" ]; then
  echo "[check_applied_migrations] bypass: BAKER_MIGRATION_EDIT_AUTHORIZED=1" >&2
  exit 0
fi

echo "" >&2
echo "[check_applied_migrations] migration drift NOT bypassed." >&2
echo "  Authorized fix paths:" >&2
echo "    1) Add a 'Migration-edit-authorized: <reason>' trailer to your commit message." >&2
echo "    2) BAKER_MIGRATION_EDIT_AUTHORIZED=1 git commit ...   (covers \`-m\` flow)" >&2
echo "    3) Revert the migration file to match the lock." >&2
echo "  After the migration is re-applied to prod, refresh the lock with:" >&2
echo "    DATABASE_URL=\$PROD_URL python3 scripts/refresh_applied_migrations_lock.py" >&2
exit 1
