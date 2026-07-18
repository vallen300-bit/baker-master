#!/usr/bin/env bash
# Regression test for fleet_terminals.sh — identity-env scrub at seat-create
# (leaked-key arc, lead #12597 re-scope / #12697; follow-up #12784).
#
# Guards: when `fleet_terminals.sh up` creates a tmux seat, the launcher's
# identity env-vars (BAKER_ROLE, BRISEN_LAB_TERMINAL_KEY, GIT_AUTHOR_EMAIL,
# GIT_COMMITTER_EMAIL) MUST NOT leak into the seat. Without the scrub, the new
# tmux server/session inherits them verbatim from the launching shell.
#
# Method: stub `tmux` on PATH so it (a) captures its full argv per subcommand,
# and (b) at `new-session` records the identity env-vars it actually SEES — that
# is what a freshly-started server would inherit. jq is real; only tmux is
# stubbed. Never touches tmux/network.
#
# Two cases exercise BOTH server states (codex PASS-WITH-NOTE #12758 follow-up):
#   A. server-present (`tmux info` succeeds) → the global `-g -u` scrub fires.
#   B. no-server     (`tmux info` fails)     → the first new-session STARTS the
#      server from our process env; the `-g -u` branch is skipped, so the
#      process-level unset is the ONLY thing standing between the launcher's
#      identity and the seat. Asserting the empty inherited env here proves the
#      fresh-server path directly.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/fleet_terminals.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq required for this test" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# --- tmux stub: log argv; on new-session dump the identity env it inherited.
#     `info` exit code is controlled by STUB_INFO_EXIT so a single stub covers
#     both the server-present and no-server cases. ---
mkdir -p "$TMP/bin"
cat > "$TMP/bin/tmux" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${TMUX_ARGV_FILE:?}"
case "${1:-}" in
  has-session) exit 1 ;;                         # seat is down → will be created
  info)        exit "${STUB_INFO_EXIT:-0}" ;;    # 0 = server present, 1 = no server
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

fail() { echo "FAIL: $1" >&2; exit 1; }

VARS=(BAKER_ROLE BRISEN_LAB_TERMINAL_KEY GIT_AUTHOR_EMAIL GIT_COMMITTER_EMAIL)

# run_case <label> <info_exit> <expect_global_scrub:yes|no>
run_case() {
  local label="$1" info_exit="$2" expect_global="$3"
  export TMUX_ARGV_FILE="$TMP/argv-$label.txt"
  export NEWSESSION_ENV_FILE="$TMP/newsession-$label.txt"
  : > "$TMUX_ARGV_FILE"; : > "$NEWSESSION_ENV_FILE"

  # `up` under a DIRTY launcher environment (simulates a leaked identity).
  PATH="$TMP/bin:$PATH" \
  STUB_INFO_EXIT="$info_exit" \
  COCKPIT_MANIFEST="$MANIFEST" \
  COCKPIT_STATE_DIR="$STATE_DIR" \
  BAKER_ROLE="lead" \
  BRISEN_LAB_TERMINAL_KEY="LEAKED-SECRET-KEY" \
  GIT_AUTHOR_EMAIL="launcher@leak.example" \
  GIT_COMMITTER_EMAIL="launcher@leak.example" \
  bash "$SCRIPT" up >/dev/null 2>&1 || fail "[$label] fleet_terminals.sh up exited non-zero"

  local ARGV ENVSEEN; ARGV="$(cat "$TMUX_ARGV_FILE")"; ENVSEEN="$(cat "$NEWSESSION_ENV_FILE")"

  # 1. new-session must have actually fired (sanity).
  grep -q 'new-session' <<<"$ARGV" || fail "[$label] new-session never invoked. argv: $ARGV"

  # 2. THE leak test: the env new-session inherited must be scrubbed empty
  #    (holds in BOTH cases — process-level unset always runs).
  local v
  for v in "${VARS[@]}"; do
    grep -q "^${v}=\[\]$" <<<"$ENVSEEN" \
      || fail "[$label] new-session inherited a non-empty $v — leak not scrubbed. Saw: $(grep "^${v}=" <<<"$ENVSEEN")"
  done
  grep -q 'LEAKED-SECRET-KEY' <<<"$ENVSEEN" && fail "[$label] leaked key reached new-session env"

  # 3. global scrub (-g -u): present only when a server already exists.
  for v in "${VARS[@]}"; do
    if [ "$expect_global" = yes ]; then
      grep -qE "set-environment -g -u $v" <<<"$ARGV" \
        || fail "[$label] missing global scrub 'set-environment -g -u $v'. argv: $ARGV"
    else
      grep -qE "set-environment -g -u $v" <<<"$ARGV" \
        && fail "[$label] unexpected global scrub for $v with no running server. argv: $ARGV"
    fi
  done

  # 4. per-session scrub (-t <slug> -u): present in BOTH cases.
  for v in "${VARS[@]}"; do
    grep -qE "set-environment -t lead -u $v" <<<"$ARGV" \
      || fail "[$label] missing per-session scrub 'set-environment -t lead -u $v'. argv: $ARGV"
  done

  echo "  ok [$label]: env scrubbed empty; global=${expect_global}; per-session present"
}

run_case server-present 0 yes
run_case no-server       1 no

echo "PASS: fleet_terminals.sh scrubs identity env at seat-create (fresh-server + already-running paths)"
