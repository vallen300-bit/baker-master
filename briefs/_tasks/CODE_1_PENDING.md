# CODE_1_PENDING — BRIEF_PLAUD_TRIGGER_FIX_1 — **COMPLETE**

**Status:** COMPLETE 2026-05-07
**PR:** https://github.com/vallen300-bit/baker-master/pull/168 (OPEN — awaiting 5-gate review)
**Branch:** `b1/plaud-trigger-fix-1` @ `4cf2651`
**Ship report:** `briefs/_reports/B1_plaud_trigger_fix_1_20260507.md`

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
