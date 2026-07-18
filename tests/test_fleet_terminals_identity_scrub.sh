#!/usr/bin/env bash
# Regression test for fleet_terminals.sh — identity-env scrub at seat-create
# (leaked-key arc, lead #12597 re-scope / #12697).
#
# Guards: when `fleet_terminals.sh up` creates a tmux seat, the launcher's
# identity env-vars (BAKER_ROLE, BRISEN_LAB_TERMINAL_KEY, GIT_AUTHOR_EMAIL,
# GIT_COMMITTER_EMAIL) MUST NOT leak into the seat. Without the scrub, the new
# tmux server/session inherits them verbatim from the launching shell.
#
# Method: stub `tmux` on PATH so it (a) captures its full argv per subcommand,
# and (b) at `new-session` records the identity env-vars it actually SEES — that
# is what a freshly-started server would inherit. Assert the seen values are
# empty (process-level scrub worked) AND that `set-environment -u` was issued
# for each var at both global (-g) and per-session (-t) scope. jq is real; only
# tmux is stubbed. Never touches tmux/network.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/fleet_terminals.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq required for this test" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- tmux stub: log argv; on new-session dump the identity env it inherited ---
mkdir -p "$TMP/bin"
cat > "$TMP/bin/tmux" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${TMUX_ARGV_FILE:?}"
case "${1:-}" in
  has-session) exit 1 ;;                         # seat is down → will be created
  info)        exit 0 ;;                         # pretend a server already runs → -g branch fires
  new-session)
    {
      printf 'BAKER_ROLE=[%s]\n'              "${BAKER_ROLE-}"
      printf 'BRISEN_LAB_TERMINAL_KEY=[%s]\n' "${BRISEN_LAB_TERMINAL_KEY-}"
      printf 'GIT_AUTHOR_EMAIL=[%s]\n'        "${GIT_AUTHOR_EMAIL-}"
      printf 'GIT_COMMITTER_EMAIL=[%s]\n'     "${GIT_COMMITTER_EMAIL-}"
    } >> "${NEWSESSION_ENV_FILE:?}"
    exit 0 ;;
  *) exit 0 ;;
esac
STUB
chmod +x "$TMP/bin/tmux"

# --- minimal manifest with one migrated seat ---
MANIFEST="$TMP/launch_manifest.json"
cat > "$MANIFEST" <<'JSON'
{"entries":[{"slug":"lead","alias":"lead-alias","launch":"/bin/zsh -lic lead-alias","profile":"Lead","port":7801}]}
JSON

# --- ledger marking that seat migrated ---
STATE_DIR="$TMP/state"
mkdir -p "$STATE_DIR"
printf '%s' '{"lead":{"state":"migrated"}}' > "$STATE_DIR/migration_ledger.json"

export TMUX_ARGV_FILE="$TMP/tmux-argv.txt"
export NEWSESSION_ENV_FILE="$TMP/newsession-env.txt"
: > "$TMUX_ARGV_FILE"; : > "$NEWSESSION_ENV_FILE"

fail() { echo "FAIL: $1" >&2; exit 1; }

# Run `up` with a DIRTY launcher environment (simulates a leaked identity).
PATH="$TMP/bin:$PATH" \
COCKPIT_MANIFEST="$MANIFEST" \
COCKPIT_STATE_DIR="$STATE_DIR" \
BAKER_ROLE="lead" \
BRISEN_LAB_TERMINAL_KEY="LEAKED-SECRET-KEY" \
GIT_AUTHOR_EMAIL="launcher@leak.example" \
GIT_COMMITTER_EMAIL="launcher@leak.example" \
bash "$SCRIPT" up >/dev/null 2>&1 || fail "fleet_terminals.sh up exited non-zero"

ARGV="$(cat "$TMUX_ARGV_FILE")"
ENVSEEN="$(cat "$NEWSESSION_ENV_FILE")"

# 1. new-session must have actually fired (sanity).
grep -q 'new-session' <<<"$ARGV" || fail "new-session never invoked. argv: $ARGV"

# 2. THE leak test: the env new-session inherited must be scrubbed empty.
for pair in 'BAKER_ROLE' 'BRISEN_LAB_TERMINAL_KEY' 'GIT_AUTHOR_EMAIL' 'GIT_COMMITTER_EMAIL'; do
  grep -q "^${pair}=\[\]$" <<<"$ENVSEEN" \
    || fail "new-session inherited a non-empty $pair — leak not scrubbed. Saw: $(grep "^${pair}=" <<<"$ENVSEEN")"
done
# Belt: the literal leaked secret must never appear anywhere new-session saw.
grep -q 'LEAKED-SECRET-KEY' <<<"$ENVSEEN" && fail "leaked key reached new-session env"

# 3. global scrub (-g -u) issued for each var (already-running-server path).
for v in BAKER_ROLE BRISEN_LAB_TERMINAL_KEY GIT_AUTHOR_EMAIL GIT_COMMITTER_EMAIL; do
  grep -qE "set-environment -g -u $v" <<<"$ARGV" \
    || fail "missing global scrub 'set-environment -g -u $v'. argv: $ARGV"
done

# 4. per-session scrub (-t <slug> -u) issued for each var.
for v in BAKER_ROLE BRISEN_LAB_TERMINAL_KEY GIT_AUTHOR_EMAIL GIT_COMMITTER_EMAIL; do
  grep -qE "set-environment -t lead -u $v" <<<"$ARGV" \
    || fail "missing per-session scrub 'set-environment -t lead -u $v'. argv: $ARGV"
done

echo "PASS: fleet_terminals.sh scrubs identity env at seat-create (process + global + per-session)"
