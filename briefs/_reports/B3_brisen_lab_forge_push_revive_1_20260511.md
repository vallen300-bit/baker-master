# B3 Ship Report — BRISEN_LAB_FORGE_PUSH_REVIVE_1

**Brief:** `briefs/BRIEF_BRISEN_LAB_FORGE_PUSH_REVIVE_1.md`
**Branch:** `b3/brisen-lab-forge-push-revive-1`
**Base SHA:** `02501eb` (origin/main HEAD post-dispatch)
**Commit:** `74e5b4a5dcd8ffd24f6d4525f875ffc89bbf81fe`
**PR:** https://github.com/vallen300-bit/baker-master/pull/187
**Date:** 2026-05-11
**Status:** READY_FOR_REVIEW

## Files added (4)
| Path | LoC | Purpose |
|---|---|---|
| `scripts/forge_snapshot_push.sh` | 142 | Mac Mini → brisen-lab snapshot pusher (worker) |
| `scripts/launchd/com.baker.forge-snapshot-push.plist` | 28 | launchd template (StartInterval=30, `__FORGE_KEY__` placeholder) |
| `scripts/install_forge_push.sh` | 33 | Idempotent installer (unload → sed-substitute → load -w) |
| `tests/test_forge_snapshot_push.sh` | 39 | Smoke test in tmpdir against dead LAB_URL |

## Quality checkpoints
```
$ bash -n scripts/forge_snapshot_push.sh
OK
$ bash -n scripts/install_forge_push.sh
OK
$ bash -n tests/test_forge_snapshot_push.sh
OK
$ plutil -lint scripts/launchd/com.baker.forge-snapshot-push.plist
scripts/launchd/com.baker.forge-snapshot-push.plist: OK
```

## Smoke test output
```
$ bash tests/test_forge_snapshot_push.sh
[forge-push] lead: HTTP 000000 (payload sha 0fe87c84)
[forge-push] deputy: HTTP 000000 (payload sha 8c0fcdfa)
[forge-push] b1: HTTP 000000 (payload sha 0f4832fe)
[forge-push] b2: HTTP 000000 (payload sha 373028fe)
[forge-push] b3: HTTP 000000 (payload sha 4baf7bc9)
[forge-push] b4: HTTP 000000 (payload sha ab669e00)
PASS: script ran without crashing.
```
HTTP 000 expected — test points LAB_URL at `http://127.0.0.1:1` (dead). All 6 terminals processed without crashing → confirms no bash-quoting bugs in state collection.

## Live dry-run (against real brisen-lab endpoint)
```
$ FORGE_KEY=$FORGE_KEY bash scripts/forge_snapshot_push.sh ; echo "exit $?"
exit 0
```
Zero stderr, zero `[forge-push]` error lines. All 6 POSTs returned 200.

## Dashboard verification
```
$ curl -s -H "X-Terminal-Key: $BRISEN_LAB_TERMINAL_KEY" \
    https://brisen-lab.onrender.com/api/v2/terminals | \
    python3 -c "import json,sys; d=json.load(sys.stdin); \
    [print(t['slug'], t.get('daemon_last_seen')) for t in d['terminals']]"
lead 2026-05-11T20:55:00.160432+00:00
deputy 2026-05-11T20:55:00.660832+00:00
b1 2026-05-11T20:55:01.614288+00:00
b2 2026-05-11T20:55:02.508321+00:00
b3 2026-05-11T20:55:03.501985+00:00
b4 2026-05-11T20:55:04.191334+00:00
cortex None
cowork-ah1 None
```
All 6 in-scope terminals refreshed within a 4-second window. `cortex` + `cowork-ah1` remain None (out of scope per brief).

## Deviation from brief (one)
Brief's `forge_snapshot_push.sh` snippet built JSON payload by interpolating bash vars into a Python heredoc via triple-quote sentinels (`'''$subject'''`). Shipped version passes the same fields through env vars (`F_SUBJECT="$subject" python3 -c "...os.environ['F_SUBJECT']..."`). Same outputs, same fields. Safer against apostrophes / backslashes / triple-quotes in commit subjects (which can appear in `dispatch:` / `mailbox:` commit headers). Brief's stated intent — "no string-concat'd JSON (escaping bugs)" — supports the hardening. Flagged for AH1 review; happy to revert if preferred verbatim.

## Post-merge step (AH1, on Mac Mini)
```bash
cd ~/Desktop/baker-code
git pull --ff-only
FORGE_KEY="$FORGE_KEY" bash scripts/install_forge_push.sh
launchctl list | grep com.baker.forge-snapshot-push   # expect status 0
tail ~/Library/Logs/forge-snapshot-push.log
```

## Rollback
```bash
launchctl unload ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist
rm ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist
```
No DB migration, no auth change, no bus message produced.
