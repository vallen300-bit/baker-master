# B3 — MAC_MINI_DROPBOX_MIRROR_RETIRE

**From:** Code Brisen 3
**To:** AI Head → B2 sanity-check
**Date:** 2026-04-19 (late afternoon)
**Task:** `briefs/_tasks/CODE_3_PENDING.md` at commit `8f1fd1a`
**Prior audit:** `briefs/_reports/B3_kbl_legacy_plist_audit_20260419.md` (a1933f8) — Director ratified RETIRE.

---

## TL;DR

`com.brisen.kbl.dropbox-mirror` unloaded + renamed. Three brisen launchd agents remain: `baker.heartbeat`, `baker.poller`, `kbl.purge-dedupe`. Reversible via `mv` + `launchctl load`. No vault touches. Dropbox mirror content frozen as-of retirement time (23:50 CEST last fired 2026-04-18).

---

## 1. Executed commands + actual output

### 1.1 Before state
```
$ ssh macmini 'launchctl list | grep brisen'
-	0	com.brisen.baker.heartbeat
-	0	com.brisen.kbl.purge-dedupe
-	0	com.brisen.baker.poller
-	0	com.brisen.kbl.dropbox-mirror
```

### 1.2 Step 1 — `launchctl unload` (atomic-order-critical: unload first, then rename)
```
$ ssh macmini 'launchctl unload ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist'
unload_exit=0
```

### 1.3 Step 2 — rename plist with `.retired-2026-04-19` suffix
```
$ ssh macmini 'mv ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist.retired-2026-04-19'
rename_exit=0
```

### 1.4 Step 3 — verify
```
$ ssh macmini 'launchctl list | grep brisen'
-	0	com.brisen.baker.heartbeat
-	0	com.brisen.kbl.purge-dedupe
-	0	com.brisen.baker.poller
```

`dropbox-mirror` is absent from the list. Three agents remain — matches expected state per task §3.

### 1.5 Final plist files on disk
```
$ ssh macmini 'ls -la ~/Library/LaunchAgents/ | grep brisen'
-rw-r--r--   1 dimitry  staff   681 Apr 19 13:13 com.brisen.baker.heartbeat.plist
-rw-r--r--   1 dimitry  staff   669 Apr 19 13:13 com.brisen.baker.poller.plist
-rw-r--r--   1 dimitry  staff   937 Apr 18 05:12 com.brisen.kbl.dropbox-mirror.plist.retired-2026-04-19
-rw-r--r--   1 dimitry  staff   803 Apr 18 05:12 com.brisen.kbl.heartbeat.plist.retired-2026-04-19
-rw-r--r--   1 dimitry  staff   803 Apr 18 05:12 com.brisen.kbl.pipeline.plist.retired-2026-04-19
-rw-r--r--   1 dimitry  staff   914 Apr 18 05:12 com.brisen.kbl.purge-dedupe.plist
```

Three retired plists now carry the `.retired-2026-04-19` suffix — consistent naming.

---

## 2. Wrapper handling — chose option (a), left wrapper in place

**Wrapper file:** `~/baker-code/scripts/kbl-dropbox-mirror.sh` (683B, `-rwxr-xr-x`).

Picked **option (a)** — wrapper left untouched on disk, orphaned (harmless with plist gone).

**Rationale:**

1. **`~/baker-code/` is a git-tracked clone of `baker-master`** (HEAD `5d0a366`). Any local rename inside this tree would either:
   - Show as a dirty working tree until `git checkout .` — drift risk if the clone gets re-pulled by unrelated work.
   - Get reverted on the next `git pull` — rename wouldn't persist.
2. **Consistency with prior retirement pattern** — in the 2026-04-19 `MAC_MINI_LAUNCHD_PROVISION` task I also left `kbl-pipeline-tick.sh` + `kbl-heartbeat.sh` in place for identical reasons. Verified today:
   ```
   -rwxr-xr-x  kbl-heartbeat.sh         (535B)
   -rwxr-xr-x  kbl-pipeline-tick.sh    (3180B)
   -rwxr-xr-x  kbl-dropbox-mirror.sh    (683B)
   ```
   All three legacy wrappers live at `~/baker-code/scripts/` with identical-posture orphan status.
3. **True source-of-truth retirement** for the wrapper would be a PR to `baker-master` removing the file from `scripts/`. That's a separate task; out of scope here.

The wrapper cannot execute on its own (launchd no longer references it). If someone runs it by hand in a shell it would attempt rsync — but the task scope was to remove the scheduled behavior, not to delete every physical artifact.

---

## 3. Dropbox mirror content — frozen as-of retirement

- **Last successful mirror run:** 2026-04-18 23:50 CEST (`dropbox-mirror.stderr` + `.stdout` mtimes, both 0-byte = clean exit).
- **Destination tree:** `~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/<YYYY-MM-DD>/` — one dated folder per prior run.
- **State going forward:** no new directories created; prior directories untouched. Director can prune manually when he exits Dropbox; per `project_dropbox_exit.md` durable signal (no new Dropbox deps in Baker / KBL), this is the last scheduled write.

**Not in scope for this task:** deleting historical mirror content from Dropbox. Left for Director to handle when he executes the Dropbox exit.

---

## 4. Reversibility check

To resurrect (if Director changes his mind):
```bash
ssh macmini 'mv ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist.retired-2026-04-19 ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist'
ssh macmini 'launchctl load ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist'
```
Wrapper is still in place → nothing else needed. Next `StartCalendarInterval` fires 23:50 CEST.

---

## 5. CHANDA pre-push

- **Q1 Loop Test:** infra retirement, no Leg touched (no Gold read, no Director action ledger, no Step 1 hot.md/ledger interaction). Pass.
- **Q2 Wish Test:** serves the wish — removes the structurally-hollowed mirror agent per Director ratification, cleans launchd surface area. Pass.
- **Inv 9:** no `~/baker-vault/` writes in this task. Post-retirement the Mac Mini agent set shrinks to `baker.poller` (vault writer, Inv-9-core) + `baker.heartbeat` + `kbl.purge-dedupe`. Aligned.
- **Inv 10:** no prompts touched. Pass.

---

## 6. Summary

| Item | State |
|---|---|
| `com.brisen.kbl.dropbox-mirror` launchd agent | UNLOADED |
| Plist file | Renamed `→ .retired-2026-04-19` at `~/Library/LaunchAgents/` |
| Wrapper `kbl-dropbox-mirror.sh` | Left in place at `~/baker-code/scripts/` (option a, matches prior pattern) |
| Remaining brisen agents | 3: `baker.heartbeat`, `baker.poller`, `kbl.purge-dedupe` |
| `~/baker-vault/` touched? | No |
| `~/.kbl.env` touched? | No |
| `com.brisen.kbl.purge-dedupe` touched? | No (per task §3) |
| Reversible? | Yes — rename + `launchctl load` |
| Dropbox mirror content | Frozen as-of 2026-04-18 23:50 CEST |

Ready for B2 sanity-check.
