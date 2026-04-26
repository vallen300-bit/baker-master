# BRIEF: PLAUD_SENTINEL_1 — Plaud voice recorder as sentinel #9

**Type:** Sentinel integration (out-of-milestone Tier B; parallel to M1/M2 work)
**Source spec:** `baker-vault/_ops/ideas/2026-04-26-plaud-sentinel-integration.md` (RA-drafted, 2026-04-26)
**Director authorization:** *"ok, pls give a task to AI Head to integrate Plaud now"* (Director, late afternoon Sunday 2026-04-26)
**Estimated time:** ~6–10h (1–2 sessions per RA estimate)
**Complexity:** Medium (API integration + new table + scheduler + Qdrant collection — all established patterns)
**Prerequisites:** `BAKER_PLAUD_API_TOKEN` provisioned in 1Password (Director gate; B-code must NOT start until confirmed).

---

## Context

Fireflies catches video meetings; Plaud closes the in-person voice gap (informal meetings, phone calls, drive-time voice notes, walks-and-talks). Mirrors the Todoist + Fireflies sentinel pattern (polling + table + Qdrant + Scan retrieval).

Sister artifact `baker-vault/_ops/shadow-org/sentinels.md` lists Plaud as #9, status: planned. This brief moves it to live.

---

## Director-resolved §4 questions (defaults adopted)

| Q | Default | Director ratification |
|---|---|---|
| Q1 Product/tier | Pro tier with API access | **Adopted** (per dispatch message: "Pro tier with API access"). If only personal tier provisioned, brief downgrades to "manual export pipeline" — surface as blocker, do NOT silently scope down. |
| Q2 Capture scope | Ingest ALL recordings | **Adopted** ("ingest ALL recordings"). Filter at retrieval if Director wants narrower scope later. |
| Q3 Storage destination | New `plaud_notes` table | **Adopted** ("new plaud_notes table"). Different signal class from meetings; clean schema; per-source retention. |

---

## Problem

In-person voice captures are currently lost to Baker. Cortex M3 cycles cannot reason about phone calls or walks-and-talks because the data never lands.

## Solution

Build sentinel #9 mirroring Todoist + Fireflies pattern:

### Data plane
- **Table** `plaud_notes` — new (NOT folded into `meeting_transcripts`):
  - `plaud_id TEXT PRIMARY KEY`
  - `title TEXT`
  - `transcript TEXT` (full content, no truncation per Phase 2 storage rule)
  - `summary TEXT`
  - `recorded_at TIMESTAMPTZ NOT NULL`
  - `duration_sec INT`
  - `tags TEXT[] DEFAULT '{}'`
  - `audio_url TEXT` (Plaud cloud reference; we do NOT mirror audio bytes)
  - `ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`

- **Migration discipline (CRITICAL — feedback_migration_bootstrap_drift):**
  - Migration file `migrations/NNN_add_plaud_notes.sql` for greenfield.
  - `_ensure_plaud_notes_base()` bootstrap in `memory/store_back.py` — MUST match migration column types EXACTLY. Grep `store_back.py` for any pre-existing `plaud` reference and verify type alignment before merging.
  - Tests verify `ADD COLUMN IF NOT EXISTS` semantics don't silently no-op against type drift.

- **Qdrant collection:** `baker-plaud`, Voyage AI `voyage-3`, 1024 dims (mirror Fireflies `baker-fireflies` config).

- **Indexes:** `recorded_at DESC`, `tags GIN`.

### Control plane
- **Polling:** APScheduler job `plaud_poll`, every 30 min (mirror `todoist_poll` cadence).
- **Watermark:** `plaud_poll` row in `trigger_watermarks` (`last_poll_at`, `last_seen_id`).
- **Auth:** `BAKER_PLAUD_API_TOKEN` fetched at runtime via `op` CLI per `reference_1password_secrets` memory. **Token MUST be provisioned in 1Password before B-code dispatch** (Director gate).
- **Backoff:** exponential on 429/5xx; mirror Todoist pattern. Log to `email_429_backoff`-style watermark.

### Retrieval plane
- **Specialist route** `plaud_search` — new in Scan classifier. Triggers on phrases like "voice note", "phone call", "walk-and-talk", "in-person meeting".
- **Capability mapping:** plaud signal class → fast path retrieval. Decomposer routes mixed queries.
- **Fallback bucket:** if classifier unsure, include top-3 plaud_notes alongside meeting_transcripts in default Scan retrieval.

### Files to create

**Migrations / schema:**
- `migrations/NNN_add_plaud_notes.sql` (next sequential N)
- `memory/store_back.py` — add `_ensure_plaud_notes_base()` matching migration types exactly

**Sentinel core:**
- `triggers/plaud_client.py` — Plaud API HTTP client (1Password token fetch, list-recordings + get-transcript endpoints, exponential backoff)
- `triggers/plaud_poll.py` — poll job logic (watermark read, fetch new, transcript ingest, Qdrant upsert, watermark write)
- `triggers/embedded_scheduler.py` — register `_plaud_poll_job` (every 30 min, behind `PLAUD_SENTINEL_ENABLED` env flag default `false`)

**Retrieval:**
- `orchestrator/capability_runner.py` — add plaud retrieval bucket
- `outputs/dashboard.py` — Scan classifier route `plaud_search`
- (optional) `kbl/resolvers/plaud_resolver.py` — if Plaud-specific entity resolution needed; defer to V2 if not.

**Tests:**
- `tests/test_plaud_client.py` — HTTP client (mock `responses`, 401/429/410 paths)
- `tests/test_plaud_poll.py` — poll loop (watermark advance, dedup on `plaud_id`, Qdrant upsert)
- `tests/test_plaud_storage.py` — `_ensure_plaud_notes_base()` idempotency, type alignment with migration
- `tests/test_plaud_scan_route.py` — Scan classifier routes "voice note" → plaud_search

### Files NOT to touch

- `meeting_transcripts` table or migrations (Q3 ratified separate table).
- Fireflies sentinel code (`triggers/fireflies_*.py`) — independent sentinel.
- `kbl/anthropic_client.py` / `orchestrator/gemini_client.py` — no LLM in poll path. Summary text comes from Plaud's own AI.
- `baker-vault/` directly (CHANDA #9).
- Audio byte storage anywhere — `audio_url` stays as Plaud cloud reference.

### Risks

- **Migration-vs-bootstrap drift (LONGTERM.md):** `_ensure_plaud_notes_base()` in `store_back.py` MUST match migration column types exactly. Grep `store_back.py` for pre-existing plaud DDL before adding the bootstrap; add type-alignment test.
- **Plaud API stability:** No public deprecation policy. B-code commits API endpoint version + access timestamp in commit message. Fallback on 401/403/410: write to `actions_log.md`, surface in next briefing, do NOT crash scheduler.
- **Plaud Pro tier not provisioned:** if token exists but API returns 403 "tier insufficient", brief degrades to manual export pipeline. Surface as blocker, NOT silent downgrade.
- **Audio file leak:** explicit non-storage of audio bytes. Test asserts `audio_url` is recorded but no `.mp3`/`.m4a`/`.wav` blob ever lands in `plaud_notes` rows or filesystem.
- **Scan retrieval contamination:** plaud_notes contain personal/casual content (phone calls, voice notes). Verify retrieval respects matter-scope; do not surface random voice notes in Hagenauer Scan responses.
- **Rate limits unknown:** start at 30-min cadence; tighten only after observing actual API behaviour for 1 week.

---

## Code Brief Standards (mandatory)

- **API version:** Plaud API — B-code MUST verify endpoints active at start of build, paste curl probe output in commit message. No public docs URL pinned (Plaud has no formal deprecation policy per spec §3).
- **Deprecation check date:** B-code logs probe timestamp in commit body.
- **Fallback:** `PLAUD_SENTINEL_ENABLED=false` (default) keeps scheduler dormant. Director flips after first dry-run with at least 1 successful poll. 401/403/410 path: log + watermark + Slack alert; never crash scheduler.
- **DDL drift check:** explicit per migration-vs-bootstrap rule above. Grep `store_back.py` for existing plaud columns before merge. Test asserts `_ensure_plaud_notes_base()` is idempotent and matches migration.
- **Literal pytest output mandatory:** ship report MUST include literal `pytest tests/test_plaud_*.py -v` stdout. ≥20 tests expected. NO "passes by inspection" — explicit `feedback_no_ship_by_inspection` rule.

## Verification criteria

1. `pytest tests/test_plaud_*.py -v` ≥20 tests pass (4 test files).
2. Migration applies cleanly on a fresh Neon branch; `_ensure_plaud_notes_base()` matches column types — type-alignment test passes.
3. Live dry-run on Render with `PLAUD_SENTINEL_ENABLED=true` produces ≥1 row in `plaud_notes` + ≥1 vector in `baker-plaud` Qdrant collection within 30 min of flag flip.
4. Scan query "voice note from this week" returns ≥1 plaud_notes hit (manual smoke test).
5. PR description documents:
   - Plaud API endpoints + version probed (with timestamp)
   - 1Password entry name + provisioning confirmed
   - Migration-vs-bootstrap drift check executed (literal grep output)
6. Sentinels artifact `_ops/shadow-org/sentinels.md` updated post-merge: Plaud §3 → §2 (live). **AI Head A handles this update** (NOT B-code — vault writes outside CHANDA #9 carve-out flow through AI Head SSH-mirror or direct vault commit).

## Out of scope

- Real-time webhook ingestion — V2.
- Audio file mirror — never (Plaud cloud is source of truth for audio).
- Speaker diarization beyond Plaud-native.
- Plaud ↔ Fireflies dedup — V2 (let both ingest; dedupe at retrieval if needed).
- Multi-account Plaud — single Director account only for V1.
- Audio playback in Cockpit — V2.

---

## Branch + PR

- Branch: `plaud-sentinel-1`
- PR title: `PLAUD_SENTINEL_1: voice recorder sentinel — table + Qdrant + 30-min poll (V1, flag-gated)`
- Reviewer: AI Head B (cross-team) per autonomy charter §4
- **B1 situational review trigger CONFIRMED**: secret/auth handling (Plaud token) + new external API + new cross-capability state writes (3 trigger classes hit). B1 reviews BEFORE merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`.

## §6C orchestration note

- Parallel-safe with B2 (WIKI_LINT_1 in flight) — zero file overlap.
- B3 recommended dispatch target: idle post-PR-#62 merge, mailbox COMPLETE, no follow-up pending.
- B1 does situational review only (not implementation). Builds and reviews split across B-codes per charter.

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
