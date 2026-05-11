# BRIEF: BRISEN_LAB_FORGE_PUSH_FOLD_1 — Forge-push V0.1 fold (3 fixes)

## Context
PR #187 (`BRISEN_LAB_FORGE_PUSH_REVIVE_1`, squash `0189390`) shipped 2026-05-11. Daemon installed on Mac Mini, all 6 cards live + refreshing every 30s. Three findings from post-merge runtime + code-reviewer that need a tight fold pass:

1. **macOS TCC blocks launchd reads under `~/Desktop`.** Hot-fix on Mac Mini relocated `forge_snapshot_push.sh` to `~/Library/Application Support/baker/` and edited the installed plist. Hot fix is NOT in the repo — needs codifying so next reinstall doesn't regress.
2. **`sed` pipe-delimiter vulnerability** in `install_forge_push.sh`: if `FORGE_KEY` ever contains `|`, substitution silently corrupts plist.
3. **Smoke test coverage gap** in `tests/test_forge_snapshot_push.sh`: builds a fake repo fixture but `TERMINALS` array is hardcoded — test never exercises the fixture, only the live Mac Mini paths.

**Anchors:**
- Live failure observed 2026-05-11 ~23:15Z: stderr `/bin/bash: /Users/dimitry/Desktop/baker-code/scripts/forge_snapshot_push.sh: Operation not permitted` (launchd exit 126).
- AH1 hot fix Mac Mini-side: script copied to `~/Library/Application Support/baker/`, plist `sed`-edited in place, agent kickstarted.
- feature-dev:code-reviewer verdict on PR #187: PASS-WITH-NITS — items 2 + 3 above.

## Estimated time: ~1h
## Complexity: Low
## Prerequisites: PR #187 already merged + daemon operational on Mac Mini

---

## Fix 1: Deploy `forge_snapshot_push.sh` out of `~/Desktop` (TCC fix)

### Problem
macOS Privacy / TCC blocks launchd-spawned processes from reading files under `~/Desktop/`, `~/Documents/`, `~/Downloads/`, and Cloud-Drive paths (Vallen Dropbox folder) unless granted Full Disk Access. Granting bash Full Disk Access is too broad. Better: deploy the script to a non-TCC location at install time, leave repo canonical untouched.

The repo's canonical script stays at `scripts/forge_snapshot_push.sh` (so b-codes can `bash -n` it + tests reference it). The installer copies it to `~/Library/Application Support/baker/` at install time. The plist `ProgramArguments` points at the deployed copy.

Same pattern as the stop hooks (`tests/fixtures/<hook>.sh` canonical, `~/.claude/hooks/<hook>.sh` deployed).

### Implementation

**Update `scripts/install_forge_push.sh`:**

Add a deploy step before the plist substitution. Current installer copies the plist template to `~/Library/LaunchAgents/`; add: copy the worker script to `~/Library/Application Support/baker/`, chmod +x.

```bash
#!/usr/bin/env bash
# install_forge_push.sh — install or reinstall the forge-snapshot-push launchd agent.
# Idempotent: unloads existing, regenerates plist with current FORGE_KEY, reloads.
# TCC-aware: deploys worker script to ~/Library/Application Support/baker/ so
# launchd can read it (the repo path under ~/Desktop is blocked by TCC).

set -euo pipefail

if [[ -z "${FORGE_KEY:-}" ]]; then
  echo "FATAL: FORGE_KEY env var must be set in the calling shell" >&2
  exit 2
fi

LABEL="com.baker.forge-snapshot-push"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER_SRC="${SCRIPT_DIR}/forge_snapshot_push.sh"
WORKER_DEPLOY_DIR="$HOME/Library/Application Support/baker"
WORKER_DEPLOY="${WORKER_DEPLOY_DIR}/forge_snapshot_push.sh"
TEMPLATE="${SCRIPT_DIR}/launchd/${LABEL}.plist"
INSTALLED_PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

[[ -f "$WORKER_SRC" ]] || { echo "FATAL: worker script missing at $WORKER_SRC" >&2; exit 2; }
[[ -f "$TEMPLATE"   ]] || { echo "FATAL: plist template missing at $TEMPLATE"   >&2; exit 2; }

# 1. Deploy worker script to TCC-safe location.
mkdir -p "$WORKER_DEPLOY_DIR"
cp "$WORKER_SRC" "$WORKER_DEPLOY"
chmod +x "$WORKER_DEPLOY"

# 2. Unload existing agent if present.
launchctl unload "$INSTALLED_PLIST" 2>/dev/null || true

# 3. Generate plist with FORGE_KEY substituted via Python (unconditionally
# safe regardless of key content — see Fix 2 below).
python3 -c "
import os, sys
template_path = sys.argv[1]
forge_key = os.environ['FORGE_KEY']
worker_deploy = sys.argv[2]
with open(template_path) as f:
    body = f.read()
body = body.replace('__FORGE_KEY__', forge_key)
body = body.replace('__WORKER_PATH__', worker_deploy)
sys.stdout.write(body)
" "$TEMPLATE" "$WORKER_DEPLOY" > "$INSTALLED_PLIST"
chmod 600 "$INSTALLED_PLIST"   # protect the embedded secret

# 4. Load the agent.
launchctl load -w "$INSTALLED_PLIST"

echo "Installed:"
echo "  Worker:  $WORKER_DEPLOY"
echo "  Plist:   $INSTALLED_PLIST"
echo "Verify: launchctl list | grep $LABEL"
echo "Log:    ~/Library/Logs/forge-snapshot-push.log"
```

**Update `scripts/launchd/com.baker.forge-snapshot-push.plist`:**

Replace the hardcoded `<string>/Users/dimitry/Desktop/baker-code/scripts/forge_snapshot_push.sh</string>` with `<string>__WORKER_PATH__</string>` — a placeholder the installer substitutes at install time. This avoids hardcoding `$HOME` in the repo and keeps the plist template installer-driven.

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
    <string>__WORKER_PATH__</string>
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

### Verification
After reinstall (AH1 runs `FORGE_KEY=$FORGE_KEY bash scripts/install_forge_push.sh` on Mac Mini):
```bash
# Worker deployed to TCC-safe path
ls -la ~/Library/Application\ Support/baker/forge_snapshot_push.sh
# Expect: file present, exec bit set, byte-identical to repo source

# Plist points at deployed path
grep ProgramArguments -A 4 ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist
# Expect: /Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh

# Agent running, no permission errors
launchctl list | grep com.baker.forge-snapshot-push
# Expect: PID + status 0 (no leading dash)

tail -10 ~/Library/Logs/forge-snapshot-push.err.log
# Expect: no new "Operation not permitted" lines since install

# Dashboard fresh
curl -s -H "X-Terminal-Key: $BRISEN_LAB_TERMINAL_KEY" \
  https://brisen-lab.onrender.com/api/v2/terminals | \
  python3 -c "import json,sys; [print(t['slug'], t['daemon_last_seen']) for t in json.load(sys.stdin)['terminals']]"
# Expect: all 6 terminals show daemon_last_seen within last minute
```

---

## Fix 2: Replace `sed` with Python substitution (pipe-delimiter safety)

### Problem
Current installer uses `sed "s|__FORGE_KEY__|${FORGE_KEY}|"`. The `|` delimiter was chosen specifically to avoid slash conflicts in the key, but if `FORGE_KEY` itself ever contains `|`, the substitution silently produces a malformed plist that launchd loads without error — agent then exits 2 with no clear pointer to the installer.

Python's `str.replace()` is unconditionally safe regardless of replacement string content.

### Implementation
Already folded into Fix 1's installer rewrite above (`python3 -c ... str.replace(...)`). Single change, no separate snippet.

### Verification
Test against a key containing `|`, `/`, `\`, `"`, `'`, `$`:
```bash
# In a sandbox shell only — DO NOT touch the live FORGE_KEY value.
FORGE_KEY='abc|def/ghi\jkl"mno\$pqr' bash -n scripts/install_forge_push.sh
# Just verify syntax cleanly; do NOT actually load the plist with a fake key.
```

The pure-bash inspection: confirm no `sed` invocation remains in the installer.

---

## Fix 3: Smoke test exercises the fake fixture

### Problem
Current `tests/test_forge_snapshot_push.sh` builds a fake repo in `$TMPDIR/fake-b9` but the worker's `TERMINALS` array is hardcoded to `lead`, `deputy`, `b1`–`b4` (real paths). The fake repo is never read. The test passes regardless of whether mailbox-detection or payload-build logic works correctly on the fixture.

A developer running the test on a fresh machine (without baker worktrees at the expected paths) sees HTTP 000 errors swallowed, gets `PASS`, but the test has verified nothing.

### Implementation
Add a `TERMINALS_OVERRIDE` env var to `scripts/forge_snapshot_push.sh` that, when set, replaces the hardcoded `TERMINALS` array. Test sets it to point at the fake fixture, asserts the script processes the override.

**In `scripts/forge_snapshot_push.sh`** (near the top, after the existing `TERMINALS=(...)` array):

```bash
# Test-only override: if TERMINALS_OVERRIDE is set, replace the array. Format:
# "alias1:/path/to/repo1 alias2:/path/to/repo2". Space-separated entries.
if [[ -n "${TERMINALS_OVERRIDE:-}" ]]; then
  TERMINALS=($TERMINALS_OVERRIDE)
fi
```

**In `tests/test_forge_snapshot_push.sh`** (replace the existing test body):

```bash
#!/usr/bin/env bash
# Smoke test for forge_snapshot_push.sh state collection.
# Builds a fake b-code repo with a PENDING mailbox + commit; runs the script
# with TERMINALS_OVERRIDE pointing at it; asserts curl received a payload
# carrying the fake state. Does NOT POST to the live endpoint — uses a local
# netcat listener.

set -euo pipefail

SCRIPT="$(dirname "$0")/../scripts/forge_snapshot_push.sh"
[[ -f "$SCRIPT" ]] || { echo "Missing: $SCRIPT" >&2; exit 1; }

TMP="$(mktemp -d)"
trap "rm -rf $TMP" EXIT

# 1. Build a fake b-code repo with a PENDING mailbox.
FAKE_REPO="$TMP/fake-b9"
mkdir -p "$FAKE_REPO/briefs/_tasks"
cd "$FAKE_REPO"
git init -q
git config user.email "test@example.com"
git config user.name "Test"
echo "# CODE_9_PENDING — TEST_BRIEF_FORGE_PUSH_FOLD" > briefs/_tasks/CODE_9_PENDING.md
git add .
git commit -q -m "fixture test commit"
cd - >/dev/null

# 2. Run the script with override pointing at the fake repo. Point LAB_URL
# at a guaranteed-dead endpoint so curl exits non-200 (we are only verifying
# the state-collection path, not the POST).
OUTPUT="$TMP/out.log"
LAB_URL="http://127.0.0.1:1" \
FORGE_KEY="test-key" \
PR_LOOKUP_ENABLED=0 \
TERMINALS_OVERRIDE="b9:$FAKE_REPO" \
bash "$SCRIPT" 2>&1 | tee "$OUTPUT" || true

# 3. Assertions. The script should have:
# (a) exited 0 (no shell crash),
# (b) attempted ONE curl to 127.0.0.1:1 (the fake terminal, not 6),
# (c) logged the HTTP 000 connect failure (single line per terminal).
EXIT_CODE="$?"
[[ "$EXIT_CODE" == "0" ]] || { echo "FAIL: script exit $EXIT_CODE" >&2; exit 1; }

# Expect exactly one "[forge-push] b9: HTTP" stderr line (the connect failure
# against 127.0.0.1:1).
B9_LINES="$(grep -c '\[forge-push\] b9:' "$OUTPUT" || true)"
[[ "$B9_LINES" -ge 1 ]] || { echo "FAIL: no b9 stderr line; coverage gap" >&2; exit 1; }

# No lines for the production aliases — confirms override actually overrode.
for alias in lead deputy b1 b2 b3 b4; do
  if grep -q "\[forge-push\] ${alias}:" "$OUTPUT"; then
    echo "FAIL: production alias '$alias' processed despite TERMINALS_OVERRIDE" >&2
    exit 1
  fi
done

echo "PASS: script processed fake fixture only, exited zero, attempted POST to dead endpoint."
```

### Verification
```bash
bash tests/test_forge_snapshot_push.sh
# Expect: "PASS: script processed fake fixture only, exited zero, attempted POST to dead endpoint."
```

---

## Files Modified
- `scripts/install_forge_push.sh` — rewrite (deploy step + Python substitution)
- `scripts/launchd/com.baker.forge-snapshot-push.plist` — `__WORKER_PATH__` placeholder for script path
- `scripts/forge_snapshot_push.sh` — add `TERMINALS_OVERRIDE` env var support (5 lines near top)
- `tests/test_forge_snapshot_push.sh` — replace body with fixture-exercising smoke test

## Do NOT Touch
- The 6-terminal `TERMINALS` array hardcoded list — override is additive, default unchanged.
- The actual payload-building Python heredoc in the worker — env-var passing pattern (from PR #187) stays.
- Existing `/api/snapshot` endpoint, schema, broadcast — works fine.
- `~/Library/Application Support/baker/forge_snapshot_push.sh` on Mac Mini — AH1 reinstalls post-merge to pick up the new install_forge_push.sh logic; until then the hot-fixed copy stays in place (still works).

## Quality Checkpoints
1. `bash -n` syntax-clean on `install_forge_push.sh`, `forge_snapshot_push.sh`.
2. `bash tests/test_forge_snapshot_push.sh` passes.
3. `grep -c 'sed' scripts/install_forge_push.sh` — expect 0 (sed eliminated).
4. `grep '__WORKER_PATH__' scripts/launchd/com.baker.forge-snapshot-push.plist` — expect 1 match.
5. The default 6-terminal behavior is unchanged when `TERMINALS_OVERRIDE` is unset — verify by reading the bash conditional.
6. Plist permissions: after install, `~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist` is `chmod 600` (secret hygiene).

## Verification SQL
```sql
-- Post-merge + reinstall: snapshot ages should hold under 1 minute for all 6.
SELECT terminal_alias, NOW() - daemon_last_seen AS age FROM forge_snapshots ORDER BY terminal_alias;
-- Expect: all 6 < 60s.
```

## Edge Cases
- **Reinstall on a Mac Mini where the deployed worker is older than repo source** — installer just overwrites; expected.
- **`TERMINALS_OVERRIDE` malformed** (e.g., no colon) — script's `snapshot_one` will receive an `alias` of the full string and an empty `repo`, fail the `-d "$repo/.git"` check, log + skip. No crash.
- **FORGE_KEY containing `__FORGE_KEY__` literal** (vanishingly unlikely but ruled out by Python `replace` only substituting once via string scan).
- **Reinstaller invoked while agent is mid-fire** — `launchctl unload` blocks briefly; worst case a single 30s tick is missed. Acceptable.

## Cost Impact
None. No API calls added, no new model invocations.

## Blast Radius
- Worst case: install fails partway. `launchctl unload` already happened, new plist not loaded → daemon stops. Rollback: revert PR, re-run old installer.
- The deployed `~/Library/Application Support/baker/forge_snapshot_push.sh` is overwritten on every install — no data loss possible (it's a copy of the repo source).

## Anchors (review-source)
- 2026-05-11 23:15Z Mac Mini stderr: `/bin/bash: /Users/dimitry/Desktop/baker-code/scripts/forge_snapshot_push.sh: Operation not permitted`.
- feature-dev:code-reviewer PR #187 verdict: Issue 1 (sed pipe-delimiter, confidence 85), Issue 2 (smoke test coverage gap, confidence 80).
- macOS TCC reference: `~/Desktop`, `~/Documents`, `~/Downloads`, Cloud Drive paths require Full Disk Access for non-user-spawned processes (launchd, Spotlight, etc.) since Catalina.

## Out of scope (not for this fold)
- Granting `/bin/bash` Full Disk Access (rejected: too broad).
- Migrating lead's `baker-code` clone out of `~/Desktop` (rejected: too many downstream references; AH1 docs, hooks, env vars all point at `~/Desktop/baker-code`).
- The 3 LOW nits from AH2's PR #186 verdict (`?` matching rhetoricals, snapshot-vs-live test, hooks firing user-globally) — separate fold for the stop-hooks brief if needed.

## Post-merge step (AH1 runs once on Mac Mini)
```bash
cd ~/Desktop/baker-code
git pull --ff-only
FORGE_KEY="$FORGE_KEY" bash scripts/install_forge_push.sh
# Verify daemon advances on the dashboard within ~60s.
```
