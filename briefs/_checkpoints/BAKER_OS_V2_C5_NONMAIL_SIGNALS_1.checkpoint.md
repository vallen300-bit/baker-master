---
brief_id: BAKER_OS_V2_C5_NONMAIL_SIGNALS_1
lane: post-deploy AC verdict — DONE (VERDICT PASS posted #6025). Only DEFERRED LOOKBACK-revert follow-up remains.
attempt: 1
owner: b1
reply_topic: baker-os-v2/c5-nonmail-signals
updated: 2026-07-07T09:34Z
---

# UPDATE 2026-07-07T09:34Z — AC COMPLETE, VERDICT PASS. C5 lane closed except 1 deferred follow-up.

POST_DEPLOY_AC_VERDICT v1 = PASS, posted lead #6025. Ship report: briefs/_reports/B1_BAKER_OS_V2_C5_NONMAIL_SIGNALS_1_POSTDEPLOY_AC_20260707.md.
All 5 ACs PASS (dry-run 0-insert, flag-on tickets both channels, >=1 each, idempotent no-dup, escalation=designed lifecycle). DB: plaud 1/1 keys, whatsapp 7/7 keys, all status=sent baden-baden-desk. Watermarks: plaud @2026-06-22T14:09, whatsapp @2026-06-07T20:43.

## ONLY remaining C5 follow-up (deferred — NOT urgent, do when wa drain ~complete)
- Revert AIRPORT_NONMAIL_LOOKBACK_HOURS 720->168 via tools.render_env_guard, ONLY AFTER whatsapp watermark passes now-168h (else max(wm,floor) strands un-drained 06-07..06-30 candidates). This CORRECTS my earlier #5990/#6017 "revert after AC" note. Purpose: defense vs future cursor-reset re-flood. Env stays SOURCES_ENABLED=true, DRY_RUN=false meanwhile.
- Observability watch (not action): stuck_arrivals rose 1->9 (email-lane counter; nonmail tickets awaiting non-responsive baden-baden-desk). baden-baden autowake Mini/wrong-host = pre-existing lead-tracked, not C5.

## NEXT ARC (fresh seat per lead #6018 — do NOT start at 64% context)
BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1 (#5914, brief on main @7646753: briefs/_tasks/BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1.md). Read-only AO data preflight, Aukera precedent. AC-first discipline.

## Render creds for successor
op item ugerv6jmgbigpaa5cqhd7xe6x4 vault "Baker API Keys" field credential = RENDER_API_KEY. service srv-d6dgsbctgctc73f55730. owner tea-d6dgif24d50c73apjilg. Logs API: GET /v1/logs?ownerId=..&resource=srv..&text=..&startTime=..&endTime=.. . Env writes: python3 -m tools.render_env_guard <svc> <KEY> <val> (merge-mode, NEVER raw array PUT). Env change needs an explicit deploy trigger (POST /deploys {clearCache:do_not_clear}) to take effect; scheduler re-registers on boot, first airport tick = boot +600s.

---
# (prior 09:26 update below — superseded by the PASS above)

# UPDATE 2026-07-07T09:26Z — live AC in progress (do NOT restart env work)

## Live AC state (Render srv-d6dgsbctgctc73f55730)
- Env LIVE (persist across deploys): AIRPORT_NONMAIL_SOURCES_ENABLED=true, AIRPORT_NONMAIL_DRY_RUN=false, AIRPORT_NONMAIL_LOOKBACK_HOURS=720. Render key: op item ugerv6jmgbigpaa5cqhd7xe6x4 vault "Baker API Keys" field credential. Owner tea-d6dgif24d50c73apjilg.
- DRY-RUN LEG PASS: tick 09:02:25Z logged 21 would-ticket (1 plaud + 20 wa, all :baden-baden-desk), 0 rows inserted. Stats line confirms plaud_skipped=1 whatsapp_skipped=20 nonmail_dry_run=True.
- LIVE LEG PARTIAL: first live tick ~09:19:37Z issued 1 plaud + 2 whatsapp (DB status=sent) then INTERRUPTED mid-wa-loop by UNRELATED new_commit deploy dep-d96c7gn4 (commit 76a55e4d harness-v2, not C5). Per-ticket commits saved the 3. Remaining ~18 wa un-issued, re-fetchable.
- Watermarks: plaud advanced to 2026-06-22T14:09 (drained, sole candidate). whatsapp watermark row ABSENT (end-of-lane advance never reached) -> next tick re-fetches all 20, 2 dedup idempotent, next ~5 issue (cap=5/lane/tick).
- Posted lead: #5990 (status), #6017 (RE #6013 interim answers). Acked #6013. lead #6013 = 2 wa escalated (#6008/#6010), baden-baden-desk non-responsive; do NOT re-route/delete; answer 2 Qs in verdict.

## Next concrete step
1. Confirm next clean tick (~09:30:45Z = 09:20:45 register +600s): assert plaud 0-new (idempotent, no 2nd plaud row), whatsapp issues next batch w/ NO duplicate rows for the 2 already-issued dedup_keys, whatsapp_issued>0 in stats. Query: SELECT source_channel,status,count(*) FROM airport_tickets WHERE source_channel IN('plaud','whatsapp') GROUP BY 1,2; + check dup dedup_key.
2. Optionally let 1-2 more ticks drain wa toward 20 (not required for AC — >=1 each already proven).
3. Revert LOOKBACK to 168 via merge-guard post-AC (defense vs future cursor-reset re-flood) + redeploy.
4. Post POST_DEPLOY_AC_VERDICT v1 to lead on baker-os-v2/c5-nonmail-signals with row ids + the 2 #6013 answers.
5. THEN Wave-2 BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1 (#5914, brief @7646753).

## Prod recon (unchanged from below — still valid)

# Checkpoint — C5 post-deploy AC (context-refresh handoff at ~50%)

## What's done
- C5 CODE merged: baker-master PR #473 on main @04606ab (codex PASS no findings #5900). Fetchers + build funcs + `_run_nonmail_lane` + flag wiring live on main.
- Tests green (9 unit local; 4 live-PG CI). Existing airport suite 68 pass, no regression.
- Ship + merge acked. C1 (companion) fully closed (PR #104 merged; deploy folded into C4 per #5910/#5912) — NOT part of this lane.

## Remaining (the live AC verdict)
Run POST_DEPLOY_AC_VERDICT v1 on topic `baker-os-v2/c5-nonmail-signals`: flag on, one real Plaud + one real WA aukera-matched candidate appear as `candidate` tickets with source_channel set, desk sees them, second tick inserts nothing. Dry-run preview first (Rule 11c).

## Prod recon already done (do NOT re-derive — verified via baker_raw_query 2026-07-07T00:00Z)
- **Bridge master gate ON**: email lane actively ticketing (50 airport_tickets: email checked_in=15/sent=8/candidate=5/closed=20/rejected=2). So `AIRPORT_TICKETING_BRIDGE_ENABLED` is already true in prod — run_tick reaches the nonmail lanes once their flag flips.
- **WhatsApp lane READY**: 5 aukera/annaberg/lilienmatt keyword-matches in whatsapp_messages last 7d, PLUS BB-AUK-001 registry already has whatsapp participants seeded (Balazs 36303005919@c.us + 436769705100@c.us, Edita 41799439246@c.us, Conrad 41794033419@c.us, Patrick Zuechner 491754393858@c.us, Merz, Pohanis, Brandner, Director 41799605092@c.us). **No registry WA-participant seed needed** — the AC's seed step is already satisfied.
- **Plaud lane needs a WIDER lookback**: aukera Plaud transcripts exist (6 all-time, all keyword-based; plaud_matter_aukera=0) but the NEWEST is 2026-06-22 14:09Z — OUTSIDE the default 7d floor. To surface a real Plaud candidate set `AIRPORT_NONMAIL_LOOKBACK_HOURS` high enough to reach 06-22 (~= 15+ days; env caps at 720h/30d, so use 720). Without it the AC shows a WhatsApp candidate only — note that explicitly if Plaud reach is declined.
- Watermark table = `trigger_watermarks` (cols: source,last_seen,updated_at,cursor_data). My per-source keys `airport_ticketing:plaud` / `:whatsapp` write there via the trigger_state wrappers.

## Next concrete step (fresh seat)
1. Confirm the Render deploy of main (>= 04606ab) is LIVE (find baker-master service id + Render API key — check `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/reference_render_api_ops.md`; query /deploys). The email lane running does NOT prove my new code deployed.
2. Set Render env (MERGE MODE only — `tools.render_env_guard.safe_env_put` / Render MCP, NEVER raw array PUT; python-backend rule): `AIRPORT_NONMAIL_SOURCES_ENABLED=true`, `AIRPORT_NONMAIL_DRY_RUN=true`, `AIRPORT_NONMAIL_LOOKBACK_HOURS=720`. Deploy/restart.
3. Observe a scheduler tick (or trigger run_tick) — confirm dry-run LOGS would-be plaud+whatsapp tickets, inserts nothing (assert airport_tickets has 0 plaud/whatsapp rows).
4. Flip `AIRPORT_NONMAIL_DRY_RUN=false`. Observe next tick — assert ≥1 `candidate` row each for source_channel plaud + whatsapp (baden-baden-desk), dedup_key = `airport-ticket:v1:{channel}:{id}:baden-baden-desk`.
5. Wait one more tick — assert zero NEW plaud/whatsapp rows (idempotency).
6. Post POST_DEPLOY_AC_VERDICT v1 to lead on `baker-os-v2/c5-nonmail-signals` with the row ids as evidence. If Plaud reach was declined, say so (WhatsApp-only verdict).
7. THEN pick up the queued Wave-2 dispatch BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1 (brief on main @7646753, #5914) — AC FIRST.

## Claim
Claim this arc by bumping `attempt:` in this file (commit) — NOT a bus ack. If attempt already bumped by another session, stand down. At attempt>=3 escalate to lead with last error.
