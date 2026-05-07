# CODE_1_PENDING — BRIEF_PLAUD_TRIGGER_FIX_1

**Dispatched:** 2026-05-06
**Tier:** B
**Repo:** `vallen300-bit/baker-master`
**Branch:** `b1/plaud-trigger-fix-1`
**Brief:** `briefs/BRIEF_PLAUD_TRIGGER_FIX_1.md` (read first — full spec, 5 patches + 1 new test file, copy-paste-ready code blocks)

## Summary

Plaud transcripts arrived as header-only shells in DB for ~3 weeks (since 2026-04-17). Root cause confirmed by AH2-T 2026-05-06 eve: `backfill_plaud()` ingests recordings before Plaud finishes transcription; `trigger_state.mark_processed` then locks the source_id so incremental re-ingestion never picks up the completed transcript. No alarm fired (silent failure).

5-patch fix:
1. `_extract_transcript_text` — warning when transaction URL absent or S3 segments empty (today: silent).
2. `backfill_plaud()` line 519+ — add `is_trans` filter mirroring incremental path at line 297-299. **PRIMARY BUG FIX.**
3. `check_new_plaud_recordings()` — stale-refresh lane: re-process `is_trans=True` recordings whose DB row has `length(full_transcript) < 200`, bypassing `is_processed` check (UPSERT via `store_meeting_transcript` ON CONFLICT).
4. After successful store, if `duration > 5min AND body < 200 chars AND is_trans=True` → `report_failure("plaud", ...)` for loud regression alarm.
5. New helper `_has_empty_db_row(source_id, threshold=200)` for stale-refresh check.
6. Unit test in `tests/test_plaud_trigger.py` — covers backfill skip on `is_trans=False`, stale-refresh trigger, empty-body alert.

## Pre-requisites

- baker-master main HEAD includes brief commit (PR #167). No env state, no blocking briefs.
- B1 branch `b1/plaud-trigger-fix-1` from main.

## Acceptance criteria

Per brief §ACs (read brief first; ACs codify each of the 5 patches + test coverage + sentinel alert wiring).

## Ship gate

Literal `pytest tests/test_plaud_trigger.py -v` GREEN — no by-inspection (Lesson #52). Plus `pytest` full-suite GREEN (no regressions).

## Note on broken recordings

4 Plaud recordings from 2026-04-17+ remain Plaud-side blocked per AH2-T diagnosis (transcription stuck — Director-side action needed). This brief is the **preventive fix** so the next time Plaud is healthy, recordings auto-recover via stale-refresh lane.

## Heartbeat

12h cadence binding (per SKILL.md `59f23c4` §B-code stall chase).

## Read first (MANDATORY)

1. `briefs/BRIEF_PLAUD_TRIGGER_FIX_1.md` — full spec
2. `~/baker-vault/_ops/agents/b1/orientation.md` — role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical
4. CLAUDE.md (this repo) — workflow + hard rules

## Confirmation phrase

`B1 oriented. Read: CODE_1_PENDING.md, MEMORY.md.`

## Caller

AH1-T (autonomous dispatch per Director instruction 2026-05-06 — task #2 from drain box).
AH1-App authored brief (Steps 1-3); AH1-T commit + dispatch lane (Step 4-5).

---

## GATE-1+3 2nd-pass UPDATE — 2026-05-07 (fold before merge)

**Source:** feature-dev:code-reviewer + code-architecture-reviewer 2nd-pass on PR #168 (HEAD `a11122f`). Both verdicts PASS-WITH-NITS-FOLD-NEEDED. 0 CRITICAL. Convergent on alarm-fatigue + multi-instance race; non-convergent watermark verification.

**I1 (BOTH gates flagged — alarm fatigue / per-source_id dedup)**
`triggers/plaud_trigger.py` empty-body sentinel fires every 15-min poll for the same broken recording until Plaud-side recovers. With 4 known-stuck recordings, this floods `report_failure("plaud", ...)` → `#cockpit` Slack. Fix: add per-`source_id` dedup before `report_failure` — fire once per recording per 24h. Implementation choice (B1 picks):
- Option A: reuse `trigger_state` with synthetic key `f"plaud_empty_alarm_{source_id}"` + check `is_processed` before firing
- Option B: in-memory dict with 24h TTL (lighter; lost on Render restart)
- Option C: `sentinel_health` table-side dedup (heaviest but auditable)

Also: gate 1 flagged that BOTH backfill path AND stale-refresh path can fire on the same `source_id` within one cycle (boot tick). Dedup must be cycle-aware OR call-site coalesced into a single helper that checks dedup once.

Regression test: trigger empty-body condition twice in same test, assert `report_failure` called exactly once.

**I2 (gate 3 flagged — multi-instance race on stale-refresh lane)**
`triggers/plaud_trigger.py` stale-refresh path bypasses `is_processed`. Render rolling deploy runs 2 instances concurrently. If both poll the same stale row, both call `fetch_plaud_detail` + `store_meeting_transcript`. PG `ON CONFLICT(id) DO UPDATE` saves dedup at storage layer, but **Qdrant has no dedup** — `store_document()` uses fresh `uuid.uuid4()` per point ID, so duplicate Voyage embedding calls + duplicate Qdrant points result. Fix: wrap stale-refresh body in `pg_try_advisory_xact_lock(hashtext(source_id))` to serialize per-source. Skip iteration if lock not acquired (other instance owns it; will retry next cycle).

Regression test: simulate two concurrent stale-refresh attempts on same source_id, assert second skips cleanly without Qdrant write.

**I3 (gate 1 flagged — watermark verification, may not need patch)**
Confirm stale-refresh lane does NOT advance the `trigger_state` watermark before all stale rows iterate. Verification-only — read current code path. If watermark management is purely in the existing incremental path's tail (post-loop), this is already correct and no patch needed. If stale-refresh advances watermark inside its loop, fix to leave watermark management to the incremental path's existing tail.

Document finding in fold ship report (no patch needed if confirmed-already-correct).

**Path forward (B1):**
1. Apply I1 + I2 on `b1/plaud-trigger-fix-1` branch (HEAD `a11122f`)
2. Verify I3 — read code, document outcome in ship report; patch only if broken
3. Add 2 regression tests (one per I1/I2 patch)
4. Live `pytest tests/test_plaud_trigger.py -v` GREEN — literal, no by-inspection
5. Re-fire focused gate chain on fold diff only (gates 1 + 3)
6. Update PR #168 ship report with new HEAD SHA + fold gate verdicts
7. AH2 /security-review (gate 2) running in parallel; AH1-T merges after fold gates PASS + AH2 PASS

**Anchor:** AH1-T autonomous fold dispatch per charter §3 (routine 2nd-pass cycle, mirrors PR #159 H1+M1+M2 fold pattern from CODE_1 prior dispatch).
