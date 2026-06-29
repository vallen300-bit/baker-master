---
status: PENDING
brief_id: INGESTION_COMPLETENESS_P0_MEASURE_1
to: b3
from: lead
dispatched_by: lead
dispatched_at: 2026-06-29
branch: ingestion-completeness-p0-measure-1
reply_target: lead (bus)
effort: medium
task_class: read-only measurement harness extension (no fix / no migration / no deploy)
gate_plan: G1 py_compile + pytest mocked-core green -> codex G3 (effort medium) -> cowork-ah1 /security-review -> lead merge -> RUN read-only -> baseline report to lead bus. NO deploy.
design_source: cowork-ah1 verdict bus #4617/#4618/#4619 (live-code grounded); folded by lead.
---

# INGESTION_COMPLETENESS_P0_MEASURE_1 — baseline completeness + lag across all 4 ingest sources

## Context
Director goal: every email, attachment, WhatsApp, and Plaud transcript reliably ingested by a sentinel into Baker's store, so the store is THE complete read surface. This is the **measure-first** step — baseline what is actually ingested vs source-of-truth, before building anything. Numbers gate whether P1 (attachments) even exists (PINNED A-LEAD-0625d shows attachments already ~99.8% backfilled, PR #430).

### Surface contract: N/A — read-only CLI/harness extension + one bus baseline report; no endpoint, no UI, no clickable surface.

## Harness V2
- **Context Contract**: Stakeholder = AH1/Director deciding the ingestion-completeness program sequence. Producer = extended `scripts/verify_backfill.py` emitting a per-source baseline (completeness% / lag / gap). Out of contract: any fix, backfill, migration, env flip, or deploy.
- **Task class**: read-only measurement harness extension + live-prod READ run.
- **Done rubric / done-state class**: (1) Build-done = adapters + lag metric land, `py_compile` clean, mocked-core pytest green. (2) Arc-done = harness RUN read-only against prod, single baseline report posted to lead bus with explicit numbers per source.
- **Gate plan**: G1 builder self-check → codex G3 (effort medium) → cowork-ah1 /security-review → lead merge → lead/builder RUN read-only → baseline to bus. NO deploy.

## Problem
`scripts/verify_backfill.py` measures completeness for EMAIL only (`SOURCES=("bluewin","graph")`, line 43) via IMAP/Graph counts + integrity spot-checks. It has NO coverage for WhatsApp or Plaud, and NO lag/recency metric — so "store is complete + fresh" is currently unmeasurable for 3 of the 4 surfaces.

## Current State (grounded — verified this session)
- Core is ~75-80% source-parametric + already unit-tested: `compare_counts` / `build_verdict` / `run_verification`. REUSE it; do not rewrite.
- Email: `email_messages` + `email_attachments`; IMAP EXAMINE + Graph totalItemCount truth-collectors exist.
- Plaud: `meeting_transcripts` HAS a `source` column (`memory/store_back.py:1488`); upstream truth = `fetch_plaud_recordings -> data_file_total` (`triggers/plaud_trigger.py:71-81`). True full-history API → ≥98% all-time achievable. CHEAP — do FIRST.
- WhatsApp: `whatsapp_messages` has **NO source column**; WAHA exposes **no aggregate count** (`triggers/waha_client.py:184-209`) → upstream truth must SUM every chat. WAHA NoWeb stores in memory and silently drops old/low-freq chats (39d scar, `WAHA_WHATSAPP_INGESTION_FAILURE_REPORT_8APR2026.md`); only all-time path is the manual iPhone export. **Target = ≥98% forward-from-enrollment + monitored, NOT all-time.** Live fallback stays permanent — do NOT scope automated all-time WA capture.

## Implementation (read-only; reuse the parametric core)
1. **Plaud adapter** (first, ~½ day): truth-collector = `data_file_total` from `fetch_plaud_recordings`; store-count = `SELECT count(*) FROM meeting_transcripts WHERE source='plaud'`. Wire into the existing compare/sample/verdict core. Spot-check N random recordings present + body non-empty.
2. **WhatsApp adapter** (~½ day): truth-collector = sum of per-chat message counts from WAHA (no aggregate endpoint — iterate chats); store-count = `SELECT count(*) FROM whatsapp_messages` (no source filter — column absent). Report as **forward-from-enrollment** completeness, label all-time as out-of-scope (source-limited). FLAG (do not migrate) a candidate `source` column on `whatsapp_messages` for waha-vs-iphone-export parity.
3. **Lag metric** (additive, all 4 sources): per source, `max(received/ingested timestamp)` in store vs now → recency lag; report against each source's poll interval so the Nirodha clause "lag < poll interval" is measurable.
4. Output: ONE consolidated baseline report → lead bus: per-source `{completeness%, lag, gap_count, sample_result}`.

## Key Constraints
- **READ-ONLY everywhere.** IMAP EXAMINE, Graph GET, WAHA GET, DB `SET default_transaction_read_only=on`. No INSERT/UPDATE, no migration, no env var, no deploy.
- Every DB query has a LIMIT; every external call wrapped try/except; never hot-path a full-history fetch.
- Reuse the parametric core; email path stays unchanged.
- Do NOT add the `whatsapp_messages.source` column — flag it only.

## Files Modified
- `scripts/verify_backfill.py` — add Plaud + WhatsApp source adapters + a per-source lag metric (extend `SOURCES`); reuse the parametric core.
- `tests/test_verify_backfill.py` (or sibling) — mocked-core tests for the two new adapters + lag logic (no live deps).

## Do NOT Touch
- The email (bluewin/graph) truth-collectors + their tests — unchanged.
- Any ingestion trigger / store writer — this is measurement only.
- `whatsapp_messages` schema — flag the source-column decision, do not migrate.

## Acceptance criteria
- AC1: `py_compile` clean; mocked-core pytest green (new adapters + lag).
- AC2: Plaud adapter reports completeness% + lag + gap with explicit numbers.
- AC3: WhatsApp adapter reports forward-from-enrollment completeness + lag, all-time labelled out-of-scope.
- AC4: Lag metric present for all 4 sources, compared to poll interval.
- AC5: One baseline report posted to lead bus; read-only confirmed (no writes in `baker_actions`).

## Context-economy (HARD — no auto-compaction)
- Read ONLY: `scripts/verify_backfill.py`, `triggers/plaud_trigger.py` (count fn), `triggers/waha_client.py` (chat iter), `memory/store_back.py:1488` (Plaud source). Do not read email truth-collectors beyond the parametric seam.
- Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP.
