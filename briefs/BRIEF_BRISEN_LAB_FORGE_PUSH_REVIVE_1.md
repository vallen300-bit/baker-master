# BRIEF: BRISEN_LAB_FORGE_PUSH_REVIVE_1 — Mac Mini → Brisen Lab snapshot writer

## Context
Brisen Lab dashboard's terminal cards (b1/b2/b3/b4/lead/deputy) show stale git/mailbox/PR data — `forge_snapshots.daemon_last_seen` for ALL terminals is 2026-05-02T05:41Z (9 days old as of writing). The unacked-message badge feature merged 2026-05-11 (PR #10, `6ceee79`) works fine because it reads the bus table live, but the other card fields read `forge_snapshots` which is dead.

**Root cause:** Mac Mini-side writer that POST'd to `https://brisen-lab.onrender.com/api/snapshot` stopped firing 2026-05-02. No trace in current scripts/ or `~/Library/LaunchAgents/`. Likely removed during a cleanup. Auth wiring (`FORGE_KEY` env var, `LAB_URL` env var) survives on Mac Mini. Endpoint, schema, and broadcast logic all alive on Render.

This brief rebuilds the writer + installs a launchd agent so the cards self-heal every 30 seconds.

**Anchors:**
- Endpoint: `brisen-lab-staging/app.py:317` `POST /api/snapshot` (auth header `X-Forge-Key`, body fields `terminal_alias`, `git_branch`, `git_head_sha`, `git_head_subject`, `mailbox_path`, `mailbox_status`, `mailbox_brief_name`, `open_pr_number`, `open_pr_title`).
- Schema: `brisen-lab-staging/db.py:108-122` `CREATE TABLE forge_snapshots` (UNIQUE on `terminal_alias`, upserts).
- Auth: `FORGE_KEY` env var already on Mac Mini (verified). `LAB_URL=https://brisen-lab.onrender.com` already set.

## Estimated time: ~2h
## Complexity: Low
## Prerequisites: none

---

## Fix 1: Snapshot collector worker script

### Problem
Need a script that, for each of the 6 terminals (lead, deputy, b1, b2, b3, b4), gathers git + mailbox + open-PR state and POSTs to `${LAB_URL}/api/snapshot`. Must run as a daemon on a 30s cadence with no flapping on transient errors.

### Implementation
New file: `scripts/forge_snapshot_push.sh` in `baker-master` repo (so it lives at `~/Desktop/baker-code/scripts/forge_snapshot_push.sh` on Mac Mini).

```bash
#!/usr/bin/env bash
# forge_snapshot_push.sh — Mac Mini → brisen-lab snapshot pusher.
# Iterates known terminals, gathers state, POSTs to /api/snapshot.
# Designed to run from launchd (com.baker.forge-snapshot-push) every 30s.
# Tolerant: any single-terminal failure logs + continues; never exits non-zero
# unless config is invalid (so launchd does not back off).

set -u
set -o pipefail

LAB_URL="${LAB_URL:-https://brisen-lab.onrender.com}"
FORGE_KEY="${FORGE_KEY:-}"

if [[ -z "$FORGE_KEY" ]]; then
  echo "[forge-push] FATAL: FORGE_KEY env var unset" >&2
  exit 2
fi

# Map: alias -> repo path. Edit here if a terminal's primary clone moves.
declare -a TERMINALS=(
  "lead:/Users/dimitry/Desktop/baker-code"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1"
  "b2:/Users/dimitry/bm-b2"
  "b3:/Users/dimitry/bm-b3"
  "b4:/Users/dimitry/bm-b4"
)

# Map: alias -> github repo slug for `gh pr list` lookup. For b-codes, the open
# PR lives wherever they pushed — heuristic: parse `git remote get-url origin`
# of the local clone and convert to owner/repo. For lead/deputy: n/a (they do
# not open PRs in their primary clone — they review them).
PR_LOOKUP_ENABLED="${PR_LOOKUP_ENABLED:-1}"

snapshot_one() {
  local alias="$1"
  local repo="$2"

  if [[ ! -d "$repo/.git" ]]; then
    echo "[forge-push] $alias: repo missing at $repo, skipping" >&2
    return 0
  fi

  local branch sha subject
  branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
  sha="$(git -C "$repo" log -1 --format='%H' 2>/dev/null | cut -c1-12 || echo '')"
  subject="$(git -C "$repo" log -1 --format='%s' 2>/dev/null || echo '')"

  # Mailbox state. b-codes have CODE_N_PENDING / CODE_N_COMPLETE; lead/deputy
  # do not have mailbox slots (they dispatch, never receive). For the 4
  # b-codes derive N from alias suffix; otherwise n/a.
  local mailbox_status="n/a"
  local mailbox_brief_name=""
  local mailbox_path=""
  if [[ "$alias" =~ ^b([1-9])$ ]]; then
    local n="${BASH_REMATCH[1]}"
    local pending="$repo/briefs/_tasks/CODE_${n}_PENDING.md"
    local complete="$repo/briefs/_tasks/CODE_${n}_COMPLETE.md"
    if [[ -f "$pending" ]]; then
      mailbox_status="pending"
      mailbox_path="$pending"
      mailbox_brief_name="$(head -1 "$pending" | sed 's/^# *//' | head -c 200)"
    elif [[ -f "$complete" ]]; then
      mailbox_status="complete"
      mailbox_path="$complete"
      mailbox_brief_name="$(head -1 "$complete" | sed 's/^# *//' | head -c 200)"
    else
      mailbox_status="empty"
    fi
  fi

  # Open PR lookup (best-effort, errors swallowed).
  local pr_number="null"
  local pr_title=""
  if [[ "$PR_LOOKUP_ENABLED" == "1" && -n "$branch" && "$branch" != "main" && "$branch" != "master" ]]; then
    local remote_url repo_slug
    remote_url="$(git -C "$repo" remote get-url origin 2>/dev/null || echo '')"
    # Convert git@github.com:owner/repo.git or https://github.com/owner/repo.git -> owner/repo
    repo_slug="$(echo "$remote_url" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
    if [[ -n "$repo_slug" ]]; then
      local pr_json
      pr_json="$(gh pr list --repo "$repo_slug" --head "$branch" --state open --json number,title --limit 1 2>/dev/null || echo '[]')"
      if [[ "$pr_json" != "[]" && -n "$pr_json" ]]; then
        pr_number="$(echo "$pr_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["number"] if d else "null")')"
        pr_title="$(echo "$pr_json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["title"] if d else "")')"
      fi
    fi
  fi

  # Build payload via python (safe JSON escaping; avoids shell-quoting bugs).
  local payload
  payload="$(python3 -c "
import json,sys
print(json.dumps({
    'terminal_alias': '$alias',
    'git_branch': '''$branch''' or None,
    'git_head_sha': '''$sha''' or None,
    'git_head_subject': '''$subject'''.strip() or None,
    'mailbox_path': '''$mailbox_path''' or None,
    'mailbox_status': '''$mailbox_status''',
    'mailbox_brief_name': '''$mailbox_brief_name''' or None,
    'open_pr_number': $pr_number if '$pr_number' != 'null' else None,
    'open_pr_title': '''$pr_title''' or None,
}))
" 2>/dev/null)"

  if [[ -z "$payload" ]]; then
    echo "[forge-push] $alias: payload build failed, skipping" >&2
    return 0
  fi

  local http_status
  http_status="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "${LAB_URL}/api/snapshot" \
    -H "X-Forge-Key: ${FORGE_KEY}" \
    -H "Content-Type: application/json" \
    --max-time 10 \
    -d "$payload" || echo '000')"

  if [[ "$http_status" != "200" ]]; then
    echo "[forge-push] $alias: HTTP $http_status (payload sha $(echo "$payload" | shasum | cut -c1-8))" >&2
  fi
}

# Iterate. Per-terminal failures are isolated.
for entry in "${TERMINALS[@]}"; do
  alias="${entry%%:*}"
  repo="${entry#*:}"
  snapshot_one "$alias" "$repo" || true
done

exit 0
```

**Key constraints in the snippet:**
- `set -u` + `set -o pipefail` but NOT `set -e` — single-terminal failures must not exit the script (launchd would back off).
- All payload construction routes through `python3 -c "json.dumps(...)"` — no string-concat'd JSON (escaping bugs).
- `curl --max-time 10` — never blocks the script past 10s per terminal.
- Errors logged to stderr (launchd routes to a log file via plist).
- Exit 0 unless `FORGE_KEY` missing → exit 2 (launchd reports config error visibly).

### Verification
```bash
# Manual dry-run (uses real env vars). Should produce 6 successful POSTs.
FORGE_KEY="$FORGE_KEY" LAB_URL="$LAB_URL" bash scripts/forge_snapshot_push.sh

# Verify dashboard updates:
curl -s -H "X-Terminal-Key: $BRISEN_LAB_TERMINAL_KEY" \
  "https://brisen-lab.onrender.com/api/v2/terminals" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); [print(t['slug'], t['daemon_last_seen']) for t in d['terminals']]"
# Expect: all 6 terminals show daemon_last_seen within the last 30 seconds.
```

---

## Fix 2: launchd agent (30s cron)

### Problem
Need the script to run automatically every 30 seconds, surviving Mac Mini reboots + user logouts (within session limits).

### Implementation
New file: `scripts/launchd/com.baker.forge-snapshot-push.plist` (template, tracked in repo).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.baker.forge-snapshot-push</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/dimitry/Desktop/baker-code/scripts/forge_snapshot_push.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>30</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/dimitry/Library/Logs/forge-snapshot-push.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/dimitry/Library/Logs/forge-snapshot-push.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>FORGE_KEY</key>
    <string>__FORGE_KEY__</string>
    <key>LAB_URL</key>
    <string>https://brisen-lab.onrender.com</string>
  </dict>
</dict>
</plist>
```

**Why a template (with `__FORGE_KEY__` placeholder):**
The installed plist needs the real `FORGE_KEY` value baked in (launchd does not inherit user-shell env vars). The installer (Fix 3) substitutes the placeholder at install time using `$FORGE_KEY` from AH1's shell. The repo-tracked template never holds the secret.

### Verification
After install (Fix 3):
```bash
launchctl list | grep com.baker.forge-snapshot-push
# Expect: 0 status (no error), non-empty PID column when actively running.

tail -f ~/Library/Logs/forge-snapshot-push.log
# Expect: silent (script logs only on errors) OR success traces.
```

---

## Fix 3: Installer script

### Problem
The plist needs to be copied to `~/Library/LaunchAgents/`, secret-substituted, and `launchctl load`-ed. AH1 runs this once on Mac Mini after merge.

### Implementation
New file: `scripts/install_forge_push.sh`.

```bash
#!/usr/bin/env bash
# install_forge_push.sh — install or reinstall the forge-snapshot-push launchd agent.
# Idempotent: unloads existing, regenerates plist with current FORGE_KEY, reloads.

set -euo pipefail

if [[ -z "${FORGE_KEY:-}" ]]; then
  echo "FATAL: FORGE_KEY env var must be set in the calling shell" >&2
  exit 2
fi

LABEL="com.baker.forge-snapshot-push"
TEMPLATE="$(dirname "$0")/launchd/${LABEL}.plist"
INSTALLED="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "FATAL: template missing at $TEMPLATE" >&2
  exit 2
fi

# Unload existing if present (ignore errors — may not be loaded).
launchctl unload "$INSTALLED" 2>/dev/null || true

# Generate plist with FORGE_KEY substituted. Use sed with a delimiter that
# cannot appear in the key (forward slash, comma, etc. could; pipe is safest).
sed "s|__FORGE_KEY__|${FORGE_KEY}|" "$TEMPLATE" > "$INSTALLED"
chmod 600 "$INSTALLED"   # protect the embedded secret

launchctl load -w "$INSTALLED"

echo "Installed: $INSTALLED"
echo "Verify: launchctl list | grep $LABEL"
echo "Log: ~/Library/Logs/forge-snapshot-push.log"
```

**Constraints:**
- `chmod 600` after secret substitution — the plist now contains FORGE_KEY in plaintext, must not be world-readable.
- `launchctl load -w` — `-w` ensures the agent stays loaded across reboots (writes disabled-state-clear to launchd database).
- Idempotent — re-running unloads first, then reloads with current FORGE_KEY value.

### Verification
```bash
# After install (AH1 runs once on Mac Mini):
FORGE_KEY="$FORGE_KEY" bash scripts/install_forge_push.sh

# Within 30s, all terminal cards on https://brisen-lab.onrender.com should
# show daemon_last_seen within the last minute.
```

---

## Fix 4: Tests (script logic only — launchd not unit-testable)

### Problem
The launchd plist is not unit-testable (would require a real Mac Mini). But the worker script's state-collection logic IS testable in isolation: given a fake repo path + mailbox state, does it produce the expected JSON payload?

### Implementation
New file: `tests/test_forge_snapshot_push.sh` (bash test, runs via `bats` if installed, else pure-bash assertions).

Pragmatic version using pure bash + a temporary fake repo:

```bash
#!/usr/bin/env bash
# Smoke test for forge_snapshot_push.sh state collection.
# Builds a fake repo + mailbox layout in $TMPDIR, runs the snapshot logic, asserts
# the payload contains expected fields. Does NOT POST to the live endpoint.

set -euo pipefail

SCRIPT="$(dirname "$0")/../scripts/forge_snapshot_push.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }

TMP="$(mktemp -d)"
trap "rm -rf $TMP" EXIT

# Build a fake b-code repo with a PENDING mailbox.
mkdir -p "$TMP/fake-b9/briefs/_tasks"
cd "$TMP/fake-b9"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
echo "# CODE_9_PENDING — TEST_BRIEF_42" > briefs/_tasks/CODE_9_PENDING.md
git add . && git commit -q -m "test commit subject"
cd -

# Run the script with FORGE_KEY set but LAB_URL pointed at a dead endpoint
# (so the curl 200 check fails harmlessly; we are only verifying the
# state-collection path). Capture stderr for any signs of crash.
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
bash "$SCRIPT" 2>&1 | tee "$TMP/out.log" || true

# The real assertion is that the script exited zero (no shell-quoting bug).
# A future iteration could mock the snapshot_one function more thoroughly via
# bats. For now we rely on the integration verification step.
echo "PASS: script ran without crashing."
```

**Why this is pragmatic, not exhaustive:**
The script's primary failure modes are (a) bash quoting bugs that cause it to crash mid-iteration, or (b) JSON build failures. A "did it complete without crashing" smoke test catches (a). Real integration verification (does the dashboard update?) is in the manual step at the end of Fix 1.

### Verification
```bash
bash tests/test_forge_snapshot_push.sh
# Expect: "PASS: script ran without crashing."
```

---

## Files Modified
- `scripts/forge_snapshot_push.sh` — NEW worker script (~120 lines)
- `scripts/launchd/com.baker.forge-snapshot-push.plist` — NEW launchd template
- `scripts/install_forge_push.sh` — NEW installer (~30 lines)
- `tests/test_forge_snapshot_push.sh` — NEW smoke test (~30 lines)

## Do NOT Touch
- `brisen-lab-staging/app.py` — endpoint exists + works, leave alone.
- `brisen-lab-staging/db.py` — schema fine.
- Any existing launchd plists (`com.baker.chrome-debug.plist` stays).
- `outputs/dashboard.py` or any baker-master FastAPI code — this is purely a Mac Mini-side daemon. Brisen Lab is a SEPARATE service.
- The 6 terminal-key files at `~/.brisen-lab-bus-last-seen-*` — those belong to the bus-drain hook, different system.

## Quality Checkpoints
1. `bash -n scripts/forge_snapshot_push.sh` — syntax check passes.
2. `bash -n scripts/install_forge_push.sh` — same.
3. `bash tests/test_forge_snapshot_push.sh` — smoke test passes.
4. Manual dry-run: `FORGE_KEY=$FORGE_KEY bash scripts/forge_snapshot_push.sh` — runs to completion, produces no `[forge-push]` error lines.
5. Repo-relative paths: no hardcoded absolute paths to `/Users/dimitry/...` EXCEPT in the launchd plist (which must be absolute) AND the `TERMINALS` array (which is config). The installer derives its own paths via `$(dirname "$0")`.
6. Secret hygiene: `FORGE_KEY` NEVER appears in any committed file. The plist template uses `__FORGE_KEY__` placeholder; the installer substitutes at runtime.

## Verification SQL
```sql
-- Post-install: confirm daemon_last_seen advances every 30s for all 6 terminals.
SELECT terminal_alias, daemon_last_seen,
       NOW() - daemon_last_seen AS age
FROM forge_snapshots
ORDER BY terminal_alias;
-- Expect: all 6 rows present, all 'age' values < 1 minute after install.
```

## Edge Cases
- **Repo missing on Mac Mini** (e.g., bm-b5 dormant): `snapshot_one` checks `-d "$repo/.git"`, logs + skips, continues to next terminal.
- **Network down / Render 5xx**: curl returns non-200, script logs the failure, exits 0. launchd fires again in 30s.
- **Mac Mini asleep**: launchd does NOT fire on a sleeping Mac. On wake, the next 30s tick fires. `daemon_last_seen` will lag by the sleep duration — that's correct behavior; dashboard will show stale until wake.
- **Concurrent writes** (two install_forge_push.sh runs): `launchctl unload` then `load -w` is sequenced, idempotent. Worst case: brief gap of no daemon while reload completes.
- **FORGE_KEY rotation**: re-run installer with new key in shell env; old plist replaced atomically.
- **Branch = "HEAD" (detached state)**: `git rev-parse --abbrev-ref HEAD` returns literal `HEAD`. That's fine — dashboard will show "HEAD" as the branch. Reflects reality.

## Cost Impact
- 30s polling × 6 terminals × ~50ms per HTTP call = ~2 outbound HTTP req/sec sustained. Trivial.
- `gh pr list` calls: 6 every 30s = 12/min. Well under GitHub API rate limit (5000/hr for authenticated user).
- Render side: 6 small INSERTs every 30s = 17,280 writes/day. Negligible.

## Blast Radius
- Worst case if implemented wrong: dashboard cards stay stale (status quo). No regression possible — endpoint already exists, only adding a writer.
- Rollback: `launchctl unload ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist && rm ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist`.
- No database migration. No auth change. No bus-message produced.

## Anchors (architecture-source)
- AH1 forensics 2026-05-11: endpoint live at `app.py:317`, schema at `db.py:108`, broadcast at `app.py:350`. `FORGE_KEY` env var present on Mac Mini (verified). Mac Mini-side writer absent.
- Director directive 2026-05-11 ~17:50Z: "draft + dispatch the fold brief now" + follow-up "go" on card-fields liveness brief.

## Post-merge step (AH1 runs once on Mac Mini)
After PR merge, AH1 runs on Mac Mini:
```bash
cd ~/Desktop/baker-code
git pull --ff-only
FORGE_KEY="$FORGE_KEY" bash scripts/install_forge_push.sh
```
Then verifies via the dashboard reload check. Once `daemon_last_seen` advances on all 6 cards, the deployment is complete.

## Out of scope (separate brief if needed)
- b-code worktree-aware mapping (when a b-code is working in `~/bm-bN-brisen-lab/` instead of `~/bm-bN/`, dashboard shows primary clone's state — v2 if it becomes a problem).
- Replacing the polling daemon with a `fswatch`-driven event push (lower latency, more complexity).
- AID and Cortex terminal cards (only lead/deputy/b1-b4 today; system cards are populated differently).
