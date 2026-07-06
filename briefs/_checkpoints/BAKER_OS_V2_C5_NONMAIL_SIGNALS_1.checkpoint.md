---
brief_id: BAKER_OS_V2_C5_NONMAIL_SIGNALS_1
lane: post-deploy AC verdict (code merged; live AC owed)
attempt: 1
owner: b1
reply_topic: baker-os-v2/c5-nonmail-signals
updated: 2026-07-07T00:00Z
---

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
