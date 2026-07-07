# B1 — BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 · POST_DEPLOY_AC_VERDICT v1

**Date:** 2026-07-07
**Lane:** post-deploy AC verdict (code merged PR #473 @04606ab; live activation + AC owed)
**Reply topic:** `baker-os-v2/c5-nonmail-signals` → lead
**Bus:** #5990 (status), #6017 (RE #6013 interim), #6025 (verdict). Acked #6013, #6018.

## VERDICT: PASS

Non-mail lanes (Plaud + WhatsApp) are live and ticketing matter-matched signals as
candidate desk-review tickets. All AC assertions confirmed by DB + Render log evidence.

## Activation (Render srv-d6dgsbctgctc73f55730, via merge-mode env guard — persists across deploys)
- `AIRPORT_NONMAIL_SOURCES_ENABLED=true`
- `AIRPORT_NONMAIL_DRY_RUN=false` (was `true` for the preview leg)
- `AIRPORT_NONMAIL_LOOKBACK_HOURS=720` (30d one-time backfill floor; chosen to reach newest aukera Plaud transcript 2026-06-22)
- C5 code live @527d5ec74 (≥ merge 04606ab). Two unrelated mid-AC deploys: 76a55e4d (harness-v2 sync), 7fd0d1a (CODE_2 mailbox) — neither touches the airport bridge.

## AC evidence

| AC | Result | Evidence |
|----|--------|----------|
| Dry-run preview logs would-be tickets, inserts 0 | PASS | tick 09:02:25Z: `plaud_skipped=1, whatsapp_skipped=20, nonmail_dry_run=True`; 21 `AIRPORT_NONMAIL_DRY_RUN would ticket` log lines; DB 0 rows |
| Flag-on creates candidate tickets w/ source_channel + desk | PASS | `airport_tickets` plaud id465, whatsapp id466/467/469-473; all `status=sent`, `proposed_desk_slug=baden-baden-desk`, `dedup_key=airport-ticket:v1:{channel}:{id}:baden-baden-desk` |
| ≥1 candidate row each channel | PASS | plaud 1 + whatsapp 7 |
| Second tick inserts nothing new / idempotent, no dup | PASS | clean tick 09:31:17Z: `plaud_issued=0` (watermark held @2026-06-22T14:09), `whatsapp_issued=5, failed=0`; DB `rows==distinct_keys` (plaud 1/1, whatsapp 7/7) → zero duplicate insert despite full re-fetch |
| Escalation-after-max-nudges = designed lifecycle | PASS (not defect) | 2 wa (466/467) → desk-review spine → baden-baden-desk non-responsive → max-nudge → escalated lead #6008/#6010; durable in lounge |

Contiguous-prefix watermarks advanced correctly: plaud @2026-06-22T14:09 (drained, sole candidate), whatsapp @2026-06-07T20:43 (partial drain, anchors forward progress).

## Timeline
- 09:02:25Z — dry-run tick (preview leg PASS).
- 09:19:52Z — first live tick: issued plaud id465 + wa id466/467, then interrupted mid-loop by unrelated deploy 76a55e4d (per-ticket commits saved the 3).
- 09:31:17Z — clean tick (post lead main-push-freeze): plaud idempotent (0), whatsapp drain +5 (id469-473+).

## Deviation from checkpoint estimate
- WhatsApp candidates = 20, not the checkpoint's ~5 — because 720h = 30-day backfill vs the 7d estimate. One-time; watermark advances then incremental. Drain proceeds ~5/tick (per-lane cap) over ~3 more ticks toward 20.

## Follow-ups (for the fresh seat — NOT this seat; stopped at ~64% per lead #6018)
1. **LOOKBACK 720→168 revert is DEFERRED** — corrects the earlier #5990/#6017 note. Reverting now sets the floor to ~now-7d (~06-30); with the whatsapp watermark only at 06-07, `max(wm, floor)` would jump to 06-30 and **strand the un-drained 06-07→06-30 candidates**. Revert only AFTER the whatsapp watermark passes now-168h (drain ≈ complete). Purpose of the revert: defense against a future cursor-reset re-flood.
2. **stuck_arrivals rose 1→9** — email-lane observability counter; likely the nonmail tickets awaiting the non-responsive desk. Watch; not a C5 concern.
3. **baden-baden-desk autowake** (Mini/wrong-host class) non-responsive — pre-existing, lead-tracked; the escalation path is working as designed around it.

## Next arc
BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1 (#5914, brief @7646753) — fresh seat per lead #6018 (do not begin new arc at 64%).
