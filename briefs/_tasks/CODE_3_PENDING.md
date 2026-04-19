# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-19 (late afternoon, post-audit-ratification)
**Status:** OPEN — retire dropbox-mirror per Director ratification

---

## Task: MAC_MINI_DROPBOX_MIRROR_RETIRE

### Context

Your audit (`briefs/_reports/B3_kbl_legacy_plist_audit_20260419.md`) recommended ESCALATE on `com.brisen.kbl.dropbox-mirror` with three options (expand / split / retire). Director ratified **RETIRE** — stated 2026-04-19: *"I do not need Dropbox mirror, by the way. I'm going to get rid of Dropbox sometime in the future."*

This is now saved as a durable project memory (`project_dropbox_exit.md`): **no new Dropbox dependencies in future Baker / KBL work.** Your audit surfaced the signal — good catch.

`com.brisen.kbl.purge-dedupe` stays KEEP per your (correct) catch that it's load-bearing for the new pipeline. No action on that plist.

### Scope

Retire `com.brisen.kbl.dropbox-mirror` on Mac Mini using the same pattern as your 2026-04-19 retirement of `com.brisen.kbl.pipeline.plist` + `com.brisen.kbl.heartbeat.plist`:

1. **`launchctl unload`** the agent:
   ```bash
   ssh macmini 'launchctl unload ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist'
   ```

2. **Rename plist** to the same retired suffix pattern you used before:
   ```bash
   ssh macmini 'mv ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror.plist.retired-2026-04-19'
   ```

3. **Verify unload:**
   ```bash
   ssh macmini 'launchctl list | grep brisen'
   ```
   Expected output: only `com.brisen.baker.heartbeat`, `com.brisen.baker.poller`, `com.brisen.kbl.purge-dedupe`. `dropbox-mirror` must be absent.

4. **Wrapper + any supporting scripts** — if the plist referenced a `.sh` wrapper in `/Users/dimitry/baker-pipeline/` or equivalent, either:
   - (a) leave it on disk (orphaned; harmless once plist is gone), OR
   - (b) rename wrapper with same `.retired-2026-04-19` suffix for consistency.

   Your call — recommend (b) for clean audit trail. Note which you picked in the report.

5. **No vault touches.** Do not touch `~/baker-vault/`. Do not touch `~/.kbl.env`. Do not touch `com.brisen.kbl.purge-dedupe.plist` — it stays.

6. **Short report** at `briefs/_reports/B3_dropbox_mirror_retire_20260419.md`:
   - The three commands above with their actual output pasted in.
   - Final `launchctl list | grep brisen` showing 3 agents remaining.
   - Which option (a / b) you picked for the wrapper + why.
   - One-line ratification that the mirror content on Dropbox is frozen as-of retirement time (Director can prune manually when he exits Dropbox; that's out of scope here).

### Hard constraints

- **Inv 9 compliant** — no agent writes to `~/baker-vault/` in this task.
- **Reversible** — renamed, not deleted. Director can `mv .retired-2026-04-19` back and `launchctl load` to resurrect if he changes his mind.
- **Atomic step order** — unload FIRST (so launchd isn't mid-cycle when the file moves), THEN rename. If you reverse this, launchd may try to restart the agent before the rename lands.

### Timeline

~10-15 min. Three commands + verification + short report.

### Reviewer

B2 — light review, mainly verify the `launchctl list` output confirms clean retirement + no vault touches.

### Dispatch back

> B3 MAC_MINI_DROPBOX_MIRROR_RETIRE shipped — report at `briefs/_reports/B3_dropbox_mirror_retire_20260419.md`, commit `<SHA>`. `dropbox-mirror` unloaded + renamed. Remaining launchd brisen agents: 3 (baker.heartbeat, baker.poller, kbl.purge-dedupe). Ready for B2 sanity-check.

### After this task

- B2 sanity-checks (~5 min).
- No further plist work unless Director surfaces new need.
- Terminal tab quit per memory-hygiene rule.

---

## Working-tree reminder

Work in `~/bm-b3`. Quit tab after this report + B2 sanity-check cycle.

---

*Posted 2026-04-19 by AI Head. Director ratification: RETIRE dropbox-mirror. Related durable signal: project_dropbox_exit.md (no new Dropbox deps).*
