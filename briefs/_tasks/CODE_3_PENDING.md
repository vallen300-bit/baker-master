# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (fresh terminal tab)
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — infra audit, quick

---

## Task: MAC_MINI_LEGACY_PLIST_AUDIT

### Context

During AI Head refresh I ran `ssh macmini 'launchctl list | grep brisen'` and got:

```
-  0  com.brisen.baker.heartbeat
-  0  com.brisen.kbl.purge-dedupe
-  0  com.brisen.baker.poller
-  0  com.brisen.kbl.dropbox-mirror
```

The `baker.*` plists are your `MAC_MINI_LAUNCHD_PROVISION` work — correct. The two `kbl.*` plists (`purge-dedupe`, `dropbox-mirror`) are **KBL-A legacy** and were NOT in the retired set of your earlier surgical cleanup (which retired `pipeline` + `heartbeat` only, renamed to `.retired-2026-04-19`).

Director needs a ratification: **keep or retire.** Pre-shadow-mode go-live this must be clear — a stale agent writing to the vault or the dedupe table while Steps 1-6 churn is a silent-corruption risk.

### Scope

**Deliverable:** one report at `briefs/_reports/B3_kbl_legacy_plist_audit_20260419.md` answering these questions per plist:

For **both** `com.brisen.kbl.purge-dedupe.plist` and `com.brisen.kbl.dropbox-mirror.plist`:

1. **What does it run?** Paste the plist `ProgramArguments` + wrapper script path. Read the wrapper script + any Python it invokes (`head -100` is enough).
2. **What does it touch?** Vault path? DB tables? Dropbox paths? Any file writes?
3. **Does it conflict with Cortex T3?**
   - Does it write to `signal_queue`, `kbl_cost_ledger`, `kbl_cross_link_queue`, `mac_mini_heartbeat`, `kbl_log`, or `kbl_alert_dedupe`? (Any write = conflict, per Inv 9 — Mac Mini poller is the only vault-writing agent in the new architecture.)
   - Does it write to `~/baker-vault/`? (Same — only Step 7 via poller.)
   - Is it still serving a purpose the new pipeline doesn't cover? (Dedupe may be a dedicated maintenance task the pipeline intentionally doesn't handle.)
4. **Your recommendation per plist:** KEEP (with one-line rationale), RETIRE (rename `.retired-2026-04-19b` in the same pattern as before + `launchctl unload`), or ESCALATE (you need Director design input before acting).

No changes to any plist until Director ratifies. **Audit report only.** Same pre-flight caution you applied correctly in `MAC_MINI_LAUNCHD_PROVISION`.

### Hard constraints

- **Read-only.** Do not unload, rename, or stop these agents in this task. Report only.
- **Do not edit `~/.kbl.env`.** Read only if needed to trace env deps.
- **Do not touch `~/baker-vault/`.** Ever.
- **`ssh macmini` is fine for reads.** Mac Mini is on tailnet (confirmed during AI Head refresh).

### Timeline

~20-30 min. Two plists. Read → trace → recommend.

### Reviewer

B2 — light review, mainly sanity-check the conflict analysis against Inv 9 + Section 2 legs.

### Dispatch back

> B3 MAC_MINI_LEGACY_PLIST_AUDIT shipped — report at `briefs/_reports/B3_kbl_legacy_plist_audit_20260419.md`, commit `<SHA>`. Recommendation: purge-dedupe=<KEEP|RETIRE|ESCALATE>, dropbox-mirror=<KEEP|RETIRE|ESCALATE>. Ready for B2 sanity-check.

### After this task

- B2 sanity-checks the audit (~5 min).
- AI Head takes recommendations to Director for ratification.
- If RETIRE on either: B3 follow-up task to rename + unload in the same pattern as the prior retirement.
- Terminal tab quit per memory-hygiene rule after this report + any follow-up.

---

## Working-tree reminder

Work in `~/bm-b3` (not `/tmp/`). Quit Terminal tab after this report lands — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Triggered by ambiguity in prior AI Head's "KBL-A legacy retired" claim — only pipeline + heartbeat plists actually renamed; purge-dedupe + dropbox-mirror remain loaded.*
