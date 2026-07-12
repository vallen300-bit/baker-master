# CHECKPOINT — ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1 (b3)

**Written:** 2026-07-12 ~14:42Z. Successor: claim = the attempt-bump commit below, NOT a bus ack.
**Attempt:** 1 (roll ordered by lead #9374 at ~36% context; build DONE + merged, arc now = collect 2 external verdicts → post 3/3 closure).

## BRIEF
ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1 — propagation half of directive #6727 (split #9161). Deputy owns the canonical clause; b3 wired the loader to inject it fleet-wide. Dispatched by lead (#9164), ship/verdicts → lead.

## DONE (all merged)
- baker-master **PR #528** MERGED (merge commit 71d9c062): `.claude/hooks/session-start-role.sh` appends `route-cues-to-superior.md` for every Director-facing/bus seat (b-codes get clause only; full laconic register still `deputy|deputy-codex|aihead2`; `bm-researcher` cwd-fallback case added) + new `.claude/role-context/deputy-codex.md` stub.
- baker-vault **PR #166** MERGED: canonical `_ops/hooks/route-cues-inject.sh` (clause-only injector for symlink-camp seats). Deputy clause **PR #165** MERGED (clause live on vault main).
- `bm-researcher` swapped from interim copy → untracked symlink `.claude/hooks/route-cues-inject.sh -> ~/baker-vault/_ops/hooks/route-cues-inject.sh` + SessionStart wire in its `settings.json` (timeout 10). Verified live inject.
- Gates: G1 self-verify PASS; codex G3 PASS-WITH-NOTE on #528+#166 (lesson #70 hook-in-vault fix applied). end-cue grammar already accepts `🟢 GO? <superior> <verb object>` — no hook/test change.
- Ship report: `briefs/_reports/B3_ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1_2026-07-12.md` (untracked in bm-b3 working tree).

## CLOSURE TALLY (1 of 3 collected + fleet verify)
- **b-code = PASS.** All 4 clones (bm-b1..b4) live-inject the clause on fresh session-start (per-clone sweep #9308). b2's earlier GO-to-Director slip = a session that started before its clone had the clause (SessionStart doesn't retro-inject); self-corrects next fresh session.
- **deputy-codex = behavior PASS (#9268/#9270), injection re-probe PENDING.** Its FAIL was a stale clone: bm-aihead2 was on `dc/arrivals-v8-live-port`, not main. Lead ordered deputy to restore bm-aihead2 to main + re-probe (#9281). Await the re-probe verdict.
- **researcher = PENDING.** Probe asked #9236, chased #9263. Await one-line PASS/FAIL from its next fresh session.

## NEXT CONCRETE STEP (successor)
1. Drain b3 bus; ACK. Collect (a) deputy-codex re-probe verdict, (b) researcher #9236 verdict.
2. When both PASS → post the 3/3 closure verdict to lead (topic `verdict/route-cues-to-superior-propagation-1`). Incident closes on propagation-landed (done) + probes 3/3.
3. THEN (fresh, per lead #9374 — do NOT start it before closure): take researcher **tranche-3 item #13 (benchmark split)** via deputy.

## KEY REFS
Bus: dispatch #9164, deputy clause #9185/#165, codex G3 #9199, lead merges #9235, stale-clone ruling #9281, b-code sweep #9308, roll order #9374. Loader is ONE shared file across baker-master clones; researcher/desks are separate repos (symlink-camp) — rest of fleet deferred to b1 BUS_FLEET_COMMS_AUDIT_1.
