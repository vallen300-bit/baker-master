# BRIEF: BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — ticket Plaud + WhatsApp signals (phase 1, Aukera pilot)

dispatched_by: lead
reply_to: lead (bus topic `baker-os-v2/c5-nonmail-signals`)
Harness-V2: task class = feature (Baker prod, feature-flagged) · Context Contract below · done rubric §Verification · gate plan: codex bus review (reasoning_effort=high — touches the ticketing spine) → lead merge → POST_DEPLOY_AC_VERDICT v1 on bus after live AC.

## Context
ClickUp C5 (86cakk5a9), Baker OS V2 rollout. The Aukera pilot tickets emails only; Plaud transcripts and WhatsApp messages already in the Baker store never board a flight. Director-scoped 2026-07-06: **phase 1 = Plaud + WhatsApp ONLY. News feeds (X/Substack/RSS) = phase 2, explicitly WAIT — do not build any part of it.** Roadmap §3 C5.

**Sequencing gate:** do NOT start until `BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1` (b4, in flight) is MERGED — same spine. Check `git log --grep=LOUNGE_WRITER` on main first; if unmerged, post a blocked note on the reply topic and wait.

## Estimated time: ~6h · Complexity: Medium-High · Prerequisites: lounge-writer-drain merged

## Current state (verified 2026-07-06)
- Spine ready: `migrations/20260629_airport_tickets.sql:3-44` — `source_channel` CHECK already includes `'whatsapp','plaud'`; `dedup_key` UNIQUE.
- Runner: `orchestrator/airport_ticketing_bridge.py` `run_tick()` (1773-2416); email fetch `fetch_email_arrivals()` (1003-1102) — keyword-ILIKE lane + Gate-2 participant lane, oldest-first.
- Dedup: `_dedup_key(source_channel, source_id, desk_slug)` (372-373) → `airport-ticket:v1:{channel}:{id}:{desk}` — extends cleanly.
- Plaud: `meeting_transcripts` table (id TEXT PK, `source='plaud'`, has `matter_slug` column, NOT auto-tagged on ingest). Ingest: `triggers/plaud_trigger.py:366-634`.
- WhatsApp: `whatsapp_messages` (id TEXT PK, sender/sender_name/chat_id/full_text/timestamp; **NO matter_slug column**). Ingest: `triggers/waha_webhook.py`.
- Registry: `kbl/project_registry_store.py` — `resolve_project_number()` (191-240), `resolve_by_participant(channel, value)` (312-331), `active_participant_values(conn, channel)` (334-374). Participants JSONB rows are `{"channel": ..., "value": ...}`.

## Engineering craft gates
- Diagnose: N/A — feature, not a bug.
- Prototype: N/A — email lane is the proven pattern; this is a parallel-lane port with pre-decided design (below).
- TDD/verification: applies — public seam = `fetch_plaud_arrivals()` / `fetch_whatsapp_arrivals()` + candidate rows in `airport_tickets`. Write the first vertical test against a live-PG test DB (`TEST_DATABASE_URL`) BEFORE implementing: insert one fake plaud transcript + one fake WA message, run the new fetchers, assert exactly one candidate each with correct dedup_key; re-run tick, assert zero new rows (idempotency).

## Pre-decided design (do not re-open; escalate on the reply topic if implementation contradicts it)
1. **Two new fetchers** in `airport_ticketing_bridge.py`, mirroring `fetch_email_arrivals()` shape:
   - `fetch_plaud_arrivals(conn, *, since, limit, keywords)` — `meeting_transcripts WHERE source='plaud'`, match = keyword ILIKE on `title`/`summary`/`full_transcript` OR `matter_slug` equals an active registry `matter_slug`. `ORDER BY meeting_date ASC LIMIT %s`.
   - `fetch_whatsapp_arrivals(conn, *, since, limit, keywords)` — `whatsapp_messages`, match = keyword ILIKE on `full_text` OR sender/chat_id in `active_participant_values(conn, channel='whatsapp')` (participant lane, mirrors Gate-2; participant match alone routes to desk-review, never fast lane — same rule as email). Accept `@lid` chat-id format (Lesson #28 — no format filtering).
2. **No schema change to `whatsapp_messages`** — matter routing via registry participants + keywords, not a new column. (Registry rows for BB-AUK-001 get WhatsApp participant values seeded as part of AC.)
3. **Dedup**: `_dedup_key("plaud", transcript_id, desk)` / `_dedup_key("whatsapp", message_id, desk)`. Mind Lesson #34: source-id column is `id` on both new tables (email uses `message_id`).
4. **Candidates only**: new rows enter `status='candidate'` and flow the existing pipeline; NEVER write `checked_in`; never touch lounge-writer claim paths (`FOR UPDATE SKIP LOCKED` untouched).
5. **Watermarks**: per-source keys in `trigger_state` (`airport_plaud_watermark`, `airport_whatsapp_watermark`), same pattern as the email lane.
6. **Feature flag**: `AIRPORT_NONMAIL_SOURCES_ENABLED` env, default OFF. `run_tick()` calls the new fetchers only when true. Rule 11c: preview-first — first live run with flag on is a logged dry-run mode (`AIRPORT_NONMAIL_DRY_RUN=true` logs would-be tickets without inserting), then real.
7. Every DB query bounded (LIMIT); every except block `conn.rollback()`.

## Key constraints
- ZERO news-feed / RSS / X / Substack code — phase 2 is Director-gated.
- Do not modify email lanes, terminal-status writer, or lounge writer.
- Do not backfill history on startup (OOM lesson): watermark starts at flag-enable time minus 7 days, configurable.
- Pilot scope: routing targets BB-AUK-001 / baden-baden-desk only in live AC; code stays generic.

## Verification (done rubric)
1. Unit/live-PG tests above green (`pytest tests/test_airport_nonmail_signals.py -v` — new file).
2. Existing spine tests still green (`pytest -k airport`).
3. Live AC (flag on, prod, after merge + deploy): one REAL Plaud transcript + one REAL WhatsApp message (aukera-matched) appear as `candidate` tickets with `source_channel` set; desk sees them; second tick inserts nothing new.
4. Dry-run mode demonstrably logs without inserting.
5. Post `POST_DEPLOY_AC_VERDICT v1` on the reply topic with row ids as evidence.

## Files modified
- `orchestrator/airport_ticketing_bridge.py` (two fetchers + flagged wiring in `run_tick()`) · `tests/test_airport_nonmail_signals.py` (new)
## Do NOT touch
- `migrations/20260629_airport_tickets.sql` (applied) · lounge-writer paths · email fetch lanes · `triggers/plaud_trigger.py` / `triggers/waha_webhook.py` (ingest is upstream, out of scope) · anything news-feed.
