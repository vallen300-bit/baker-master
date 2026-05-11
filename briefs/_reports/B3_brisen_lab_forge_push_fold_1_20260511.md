# B3 Ship Report — BRISEN_LAB_FORGE_PUSH_FOLD_1

**Brief:** `briefs/BRIEF_BRISEN_LAB_FORGE_PUSH_FOLD_1.md`
**Branch:** `b3/brisen-lab-forge-push-fold-1`
**Base SHA:** `92120a9` (origin/main HEAD post-dispatch)
**Commit:** `ff72df894c6d48d1d81512920eaea11c01cb9107`
**PR:** https://github.com/vallen300-bit/baker-master/pull/188
**Date:** 2026-05-11
**Status:** READY_FOR_REVIEW
**Folds on:** PR #187 (`0189390`, BRISEN_LAB_FORGE_PUSH_REVIVE_1)

## Files modified (4)
| Path | Δ | Purpose |
|---|---|---|
| `scripts/forge_snapshot_push.sh` | +6 / -0 | `TERMINALS_OVERRIDE` env var (default behavior unchanged when unset) |
| `scripts/install_forge_push.sh` | +37 / -14 | Deploy step → `~/Library/Application Support/baker/`; `sed` → `python3 str.replace`; substitute `__WORKER_PATH__` |
| `scripts/launchd/com.baker.forge-snapshot-push.plist` | +1 / -1 | Worker path → `__WORKER_PATH__` placeholder |
| `tests/test_forge_snapshot_push.sh` | +44 / -21 | Rewrite to use `TERMINALS_OVERRIDE` + assert override-only processing |

## Quality checkpoints (all green)
```
$ bash -n scripts/forge_snapshot_push.sh
OK
$ bash -n scripts/install_forge_push.sh
OK
$ bash -n tests/test_forge_snapshot_push.sh
OK
$ plutil -lint scripts/launchd/com.baker.forge-snapshot-push.plist
scripts/launchd/com.baker.forge-snapshot-push.plist: OK
$ grep -c 'sed' scripts/install_forge_push.sh
0
$ grep -c '__WORKER_PATH__' scripts/launchd/com.baker.forge-snapshot-push.plist
1
```

## Smoke test output
```
$ bash tests/test_forge_snapshot_push.sh
[forge-push] b9: HTTP 000000 (payload sha e94b9328)
PASS: script processed fake fixture only, exited zero, attempted POST to dead endpoint.
```
Coverage now real: exactly one `b9` stderr line (the fake fixture), zero production-alias lines (override actually overrode), exit 0.

## Adversarial substitution test (out-of-band, not in test suite)
```
$ python3 -c "
import os
forge_key = 'abc|def/ghi\\\\jkl\"mno\$pqr|XYZ'
worker_deploy = '/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh'
with open('scripts/launchd/com.baker.forge-snapshot-push.plist') as f:
    body = f.read()
body = body.replace('__FORGE_KEY__', forge_key)
body = body.replace('__WORKER_PATH__', worker_deploy)
assert '__FORGE_KEY__' not in body
assert '__WORKER_PATH__' not in body
assert forge_key in body
assert worker_deploy in body
print('Python substitution survives pipe + slash + backslash + quote + dollar in FORGE_KEY')
"
Python substitution survives pipe + slash + backslash + quote + dollar in FORGE_KEY
```
Old `sed "s|...|...|"` would have broken on the literal `|` in this key.

## Default-behavior preservation
Read `scripts/forge_snapshot_push.sh:20-27`: 6-terminal array unchanged. Override block at lines 29-33 is purely additive (`if [[ -n "${TERMINALS_OVERRIDE:-}" ]]; then TERMINALS=(...); fi`). Live dry-run on production behavior not re-run because (a) no semantic change to the default path, (b) AH1's framing: daemon is healthy in prod via hot-fix; this PR is repo-side consistency, not a prod gate.

## Framing note (per lead, 2026-05-11)
Daemon is NOT broken in prod right now — Mac Mini hot-fix live (PID 4062, all 6 cards refreshing every 30s, `lead` git fields empty but `mailbox=n/a` so no functional gap). What this PR fixes is the REPO-side installer (still pointed at `~/Desktop`). Reconvergence ensures next reinstall doesn't regress. No prod emergency — consistency cleanup with small future-proof benefit.

## Post-merge step (AH1, on Mac Mini)
```bash
cd ~/Desktop/baker-code
git pull --ff-only
FORGE_KEY="$FORGE_KEY" bash scripts/install_forge_push.sh
ls -la ~/Library/Application\ Support/baker/forge_snapshot_push.sh
launchctl list | grep com.baker.forge-snapshot-push
tail -5 ~/Library/Logs/forge-snapshot-push.err.log
```

## Rollback
```bash
launchctl unload ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist
rm ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist
rm -rf ~/Library/Application\ Support/baker/
```
Hot-fixed daemon stays installed if revert: only the next `install_forge_push.sh` run would regenerate from the reverted code.
