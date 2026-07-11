# B2 SHIP — WAKE_HANDLER install lane + WAKE_HOST_AFFINITY_1

Follows `B2_WAKE_HANDLER_DUPLICATE_SPAWN_HARDENING_1_SHIP_20260705.md` (PR #99, merged).
Driven off lead bus #5570 (install urgent) + #5571 (affinity scope extension).

## Part 1 — F1–F4 handler install (bus #5570) — DONE, both hosts

| Host | Result |
|------|--------|
| **Laptop** (macbook-pro-2) | `build.sh` rebuilt+re-signed; codesign valid; osadecompile of installed `main.scpt` confirms F1/F2/F3/F4; `open brisen-lab://wake/codex-arch` rc=0, no `-600/-609`, no stray `.command`. Backup: `/tmp/wake-app-backup-laptop`. |
| **Mac Mini** (dimitrys-mac-mini) | No brisen-lab checkout on Mini → staged `tools/wake-handler/` via rsync to `~/wake-handler-staging`, ran `build.sh` (gui/501 domain OK). codesign valid; osadecompile confirms F1–F4; `codex-arch` dispatch rc=0, no stray `.command`. Backup: `/tmp/wake-app-backup-mini`. |

**Net effect now:** the originally-reported incident (desk live on laptop → Mini clones) is fixed by **F2**; **F1** kills the api-key-stall respawn storm; **F3** caps to 1 spawn / 120s / host. Server endpoint `/api/slug_live` deployed with the #99 Render merge.

**Unconfirmed (flagged to lead #5575):** TCC Automation→Terminal survival of the re-sign is only provable by a live spawn/nudge — deferred to the joint verify (2026-06-22 precedent: the grant survived a re-sign). The `codex-arch` probe confirms URL-scheme dispatch + Gatekeeper accept, not the Apple-Events grant.

## Part 2 — WAKE_HOST_AFFINITY_1 (bus #5571) — MERGED + INSTALLED + VERIFIED

- **brisen-lab PR #100** MERGED (codex G3 PASS-WITH-NOTES #5579). branch `b2/wake-host-affinity-1` · commit `0b33847`. Handler-only.
- **Installed on BOTH hosts via in-place script swap** (Lesson #93 — codex note: NOT `build.sh` rm-rf, to preserve bundle identity/TCC): `osacompile → bare .scpt → cp into bundle main.scpt → codesign -f -s -`. codesign valid both hosts. Regression **ALL PASS incl. Gate E** both hosts (laptop `isDeskSpawnHost=false`, Mini `=true`).
- **Joint verify (bus #5591):** LAPTOP dormant baden-baden-desk wake ×3 → **0 spawns** + `wrong_host` logged (drop confirmed). MINI dormant wake ×1 → **exactly 1 spawn** (pid 6336) → also confirms **TCC→Terminal survived the re-sign**. Net AC **1-on-Mini / 0-on-laptop CONFIRMED**. Mini done ×1 (not ×3) to avoid booting 3 real desk agents; exactly-1 guaranteed by the `acquireSpawnLock` regression (5 concurrent→1) + F3. Test spawn killed + lock cleared after.
- **Follow-ups flagged to lead:** (1) pid 89810 on the Mini — **CORRECTED by lead (#5595): NOT a stalled duplicate.** It is the parent zsh wrapper (`/tmp/brisen-lab-wake-badenbadendesk.command`) of the **LIVE** desk seat 89837 (claude running S+ foreground; ppid chain verified). Correctly left un-reaped (I only killed my own test spawn). (2) spawned desk sessions didn't register a heartbeat-ticker within ~20s — lead parked this as a follow-up observation (desks may simply not run the worker-style ticker); lives in bus thread #5591/#5595.

## Closeout (lead #5595 — STAND DOWN)
Joint verify **ACCEPTED**. **baden-baden-desk autowake RE-ENABLED permanently** (slug removed from disabled list, deploy fired). Whole arc landed same night: F1–F4 (PR #99) + WAKE_HOST_AFFINITY_1 (PR #100), both merged + installed + verified on both hosts, 0-on-laptop / 1-on-Mini proven, TCC survived. Arc closed.

### (original PR-open detail)

- **brisen-lab PR #100** · branch `b2/wake-host-affinity-1` · commit `0b33847`. Handler-only.
- Root cause F2 misses: a wake broadcast hits BOTH hosts' listeners; a **dormant** desk → both see not-live → both spawn → 2 windows. F2 only guards *already-live*.
- Fix: desk slugs `{hag-desk, ao-desk, movie-desk, baden-baden-desk, origination-desk, hag-filer}` home to the Mac Mini; non-home host drops the desk spawn (`wrong_host` log), nudge passthrough kept; Mini is sole desk spawner. Home detection by hostname (`mac-mini`), zero-config, survives reinstalls (rule in committed source); `~/.brisen-lab/desk-spawn-host` override wins; fail-safe = detection error drops the clone.
- Verified on laptop: osacompile clean; `isDeskSlug(baden-baden-desk)=true`, `isDeskSlug(b2)=false`, `isDeskSpawnHost()=false`. Regression gate **E** added.

## Remaining sequence (gated on lead)
1. codex G3 + **lead merge** of PR #100 (or lead says hot pre-merge install).
2. B2 rebuild+install the affinity handler on **both hosts** (backups already in `/tmp`).
3. **Joint verify:** dormant `baden-baden-desk` wake → exactly 1 Terminal on Mini, 0 on laptop, 3 consecutive rounds (+ AC2 no-api-key-dialog live).
4. B2 signals lead to re-enable `baden-baden-desk` autowake permanently (Director standing order).

**B2 will not install unmerged code to the prod hosts** without a lead hot-install go.
