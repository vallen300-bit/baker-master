# BRIEF: PLAUD_TRIGGER_FIX_1 — backfill_plaud is_trans filter + stale-refresh + sentinel

## Context

Plaud transcripts arrived as header-only shells in DB for ~3 weeks (since 2026-04-17), silently. Root cause confirmed by AH2-T 2026-05-06 eve: `backfill_plaud()` ingests recordings before Plaud finishes transcription; `trigger_state.mark_processed` then locks the source_id, so incremental re-ingestion never picks up the completed transcript. No alarm fired because `_extract_transcript_text` returns `""` silently when transaction URL absent or S3 segments empty, and `store_meeting_transcript` accepts zero-length bodies without complaint.

Director noted the symptom 2026-05-06 eve ("Baden-Baden Desk said 'no Plaud transcripts' when transcripts existed"). 4 user recordings currently shells (Apr 17 onward; 165-min Apr 27 file included). Baker-side fix is preventive — Director-side action on web.plaud.ai (credits / device pairing / language) needed separately to recover the 4 already-broken recordings.

## Estimated time: ~2-3h
## Complexity: Low-Medium
## Prerequisites: none

---

## Fix 1: Backfill `is_trans` filter (PRIMARY BUG)

### Problem
`backfill_plaud()` fetches every recording in the listing regardless of transcription state. Header-only shells get stored, source_id marked processed, never re-fetched.

### Current State
`triggers/plaud_trigger.py:519-528` — backfill loop has no `is_trans` check (incremental path at line 297-299 has it).

### Implementation
After line 522 (`if not file_id: continue`), add:

```python
            # Mirror incremental-path filter (line 297-299): skip un-transcribed recordings.
            # Without this, header-only shells get stored + source_id locked, breaking re-ingest
            # after Plaud completes transcription.
            if not rec.get("is_trans"):
                continue
```

### Verification
Unit test: mock fetch_plaud_recordings returning mix of `is_trans=True` and `is_trans=False`; assert only is_trans=True records reach store_meeting_transcript.

---

## Fix 2: Stale-refresh lane in `check_new_plaud_recordings()`

### Problem
Existing `is_processed` short-circuit at line 322-324 prevents re-fetch of source_ids that were prematurely marked processed by the broken backfill. Once Plaud finishes transcription, no path retrieves the body.

### Current State
`triggers/plaud_trigger.py:315-324` — incremental loop skips any source_id where `trigger_state.is_processed("meeting", source_id)` is True.

### Implementation
Replace lines 322-324 with:

```python
            # Skip if already processed AND DB body is non-empty.
            # Stale-refresh: if Plaud previously returned is_trans=False (broken backfill
            # pre-fix landed shells), allow re-ingest once Plaud reports is_trans=True.
            # store_meeting_transcript ON CONFLICT (id) DO UPDATE handles upsert cleanly.
            if trigger_state.is_processed("meeting", source_id):
                if not _has_empty_db_row(source_id, threshold=200):
                    continue
                logger.info(f"Plaud trigger: stale-refresh re-ingesting {source_id} (DB body < 200 chars, is_trans now True)")
```

### Verification
Test: seed `meeting_transcripts` with 100-char body for `plaud_<id>` + `trigger_state.is_processed=True`. Run `check_new_plaud_recordings` with listing returning is_trans=True for that id. Assert `store_meeting_transcript` called with full body.

---

## Fix 3: New helper `_has_empty_db_row`

### Problem
Stale-refresh lane needs a cheap check for "stored body length < threshold". No helper exists today.

### Implementation
Add near `_recording_id` (line 188+):

```python
def _has_empty_db_row(source_id: str, threshold: int = 200) -> bool:
    """Returns True if meeting_transcripts has a row for source_id with full_transcript shorter than threshold.

    Used by stale-refresh path: a row from the broken-backfill era has length(full_transcript)
    well below 200 chars (header-only shell). A real transcript is typically >> 200 chars even
    for short recordings.
    """
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT length(full_transcript) FROM meeting_transcripts WHERE id = %s LIMIT 1",
            (source_id,),
        )
        row = cur.fetchone()
        cur.close()
        return bool(row) and (row[0] or 0) < threshold
    except Exception as e:
        conn.rollback()
        logger.debug(f"_has_empty_db_row probe failed for {source_id} (non-fatal): {e}")
        return False
    finally:
        store._put_conn(conn)
```

Constraints: LIMIT 1 ✓, conn.rollback() in except ✓, singleton via `_get_global_instance()` ✓.

---

## Fix 4: Post-store empty-body sentinel

### Problem
`_extract_transcript_text` returns `""` silently on missing transaction URL or empty S3 segments. `store_meeting_transcript` accepts zero-length bodies. No alarm. Silent for 3 weeks.

### Implementation
After successful `store_meeting_transcript` call (both incremental ~line 360 and backfill ~line 549), add:

```python
            # Loud sentinel: if duration > 5min AND body < 200 chars AND is_trans=True,
            # something went wrong upstream (S3 fetch, parsing). report_failure raises
            # the existing sentinel-health alarm; surfaces in #cockpit Slack.
            try:
                _dur_ms = rec.get("duration") or 0
                _body = formatted.get("text") or ""
                if _dur_ms > 300_000 and len(_body) < 200 and rec.get("is_trans"):
                    report_failure("plaud", f"empty-body-after-transcription: {source_id} dur={_dur_ms}ms body={len(_body)}chars")
            except Exception as _se:
                logger.debug(f"empty-body sentinel check failed (non-fatal): {_se}")
```

### Verification
Test: mock recording with `is_trans=True`, duration=600000ms, but mocked `_extract_transcript_text` returns `""`. Assert `report_failure` called once with topic="plaud" and message containing "empty-body-after-transcription".

---

## Fix 5: `_extract_transcript_text` diagnostic warnings

### Problem
Function returns `""` silently when transaction URL missing or S3 segments empty. Two distinct failure modes; neither logs.

### Current State
`triggers/plaud_trigger.py:124-144` — both early returns are bare `return ""`.

### Implementation
Replace lines 129-135 with:

```python
    url = _get_content_url(detail, "transaction")
    if not url:
        logger.warning(f"_extract_transcript_text: no transaction URL in detail (file_id={detail.get('id', '?')})")
        return ""

    segments = _fetch_s3_content(url, is_json=True)
    if not segments or not isinstance(segments, list):
        logger.warning(f"_extract_transcript_text: empty/invalid S3 segments for {detail.get('id', '?')} (url-tail={url[-40:]})")
        return ""
```

Constraint: do NOT log full URL or token (PII / credential exposure); url-tail safely identifies the failing object without leaking auth.

### Verification
Test: call `_extract_transcript_text` with detail missing transaction URL; assert WARNING logged. Same with detail returning empty segments.

---

## Fix 6: New test file `tests/test_plaud_trigger.py`

Create `tests/test_plaud_trigger.py` with 5 tests covering Fixes 1-5:

```python
"""Tests for triggers/plaud_trigger.py — covers BRIEF_PLAUD_TRIGGER_FIX_1."""
from unittest.mock import MagicMock, patch
import pytest


def test_backfill_skips_un_transcribed():
    """Fix 1: backfill_plaud must skip recordings with is_trans=False."""
    from triggers.plaud_trigger import backfill_plaud
    mixed = [
        {"id": "a", "is_trans": True,  "duration": 60000, "start_time": 1000, "filename": "good"},
        {"id": "b", "is_trans": False, "duration": 60000, "start_time": 2000, "filename": "bad"},
    ]
    with patch("triggers.plaud_trigger.fetch_plaud_recordings", return_value=mixed), \
         patch("triggers.plaud_trigger.fetch_plaud_detail") as fetch_detail, \
         patch("memory.store_back.SentinelStoreBack._get_global_instance") as get_store:
        store = MagicMock()
        get_store.return_value = store
        backfill_plaud()
    fetched_ids = [c.args[0] for c in fetch_detail.call_args_list]
    assert "a" in fetched_ids
    assert "b" not in fetched_ids, "backfill must skip is_trans=False"


def test_stale_refresh_re_ingests_empty_db_row():
    """Fix 2 + 3: incremental path re-fetches source_id when DB body < 200 chars."""
    # ... (mock trigger_state.is_processed=True, _has_empty_db_row=True;
    #      assert fetch_plaud_detail called for source_id)


def test_has_empty_db_row_lt_threshold():
    """Fix 3: helper returns True for short body, False for long body, False for missing row."""
    # ... (3 assertions via mocked cursor.fetchone)


def test_empty_body_sentinel_fires():
    """Fix 4: report_failure called when duration>5min + body<200 + is_trans=True."""
    # ... (mock report_failure; assert called once with topic='plaud')


def test_extract_transcript_text_logs_warnings():
    """Fix 5: warnings logged for missing transaction URL + empty S3 segments."""
    # ... (caplog WARNING assertions)
```

Code Brisen fills test bodies during implementation; signatures + assertions are locked above.

---

## Files Modified
- `triggers/plaud_trigger.py` — Fixes 1-5 (5 surgical edits, ~30 LOC net add)
- `tests/test_plaud_trigger.py` — NEW (5 tests covering Fixes 1-5)

## Do NOT Touch
- `memory/store_back.py:1229+` — `store_meeting_transcript` ON CONFLICT (id) DO UPDATE already correct; stale-refresh upsert path is preserved as-is
- `format_plaud_transcript` (line 206) — filter is upstream of formatting; this function unchanged
- `triggers/sentinel_health.py` — `report_failure("plaud", ...)` reuses existing infrastructure; no new sentinel definitions needed
- 4 broken recordings recovery — Director-side action on web.plaud.ai (credits/pairing/language); preventive ship is the scope of THIS brief

## Quality Checkpoints
1. `pytest tests/test_plaud_trigger.py -v` GREEN with literal output (NOT "by inspection")
2. Existing pytest suite GREEN (no regression)
3. `grep -n "is_trans" triggers/plaud_trigger.py` shows 2 occurrences (line 297-299 unchanged + new line in backfill)
4. Stale-refresh test verifies `store_meeting_transcript` called with full body for re-ingested source_id
5. Empty-body sentinel test verifies `report_failure` invoked exactly once per zero-body recording
6. No PLAUD_TOKEN, S3 URLs, or response bodies appear in any log (review new `logger.warning` calls)

## Verification SQL
```sql
-- After deploy, before backfill rerun: confirm shells exist (baseline).
SELECT id, length(full_transcript) AS body_len, ingested_at
FROM meeting_transcripts
WHERE source = 'plaud' AND length(full_transcript) < 200
ORDER BY ingested_at DESC LIMIT 20;

-- After Director-side Plaud recovery + backfill rerun: confirm bodies > 200 chars.
SELECT id, length(full_transcript) AS body_len, ingested_at
FROM meeting_transcripts
WHERE source = 'plaud' AND id IN (<4 broken source_ids>)
LIMIT 10;
```

## Gates (per AH2-T design + SKILL.md §Code-reviewer 2nd-pass Protocol)
- `feature-dev:code-reviewer` — logic + edge cases on stale-refresh upsert path
- `/security-review` — Plaud token handling (env PLAUD_TOKEN, 1P "Plaud API Token" / "Baker API Keys"); verify no token leak in new warning logs
- `picker-architect` review per 5-gate
- 2nd-pass `feature-dev:code-reviewer` per SKILL.md (PR touches external API auth surface)

## Ship Target
- PR with all gates passing
- Ship report at `briefs/_reports/<bN>_plaud_transcript_fix_<date>.md` (replace `<bN>` with assigned B-code slug)
- Backfill rerun gated on Director confirming Plaud-side recordings now `is_trans=True`. If still stuck Plaud-side, ship as preventive-only and document broken-recordings status in ship report.

## Caller / Provenance
- AH2-T diagnosis 2026-05-06 eve (root cause + 5-patch design locked)
- AH2-T re-emit 2026-05-06 ~19:50Z post-API-termination (paste-block relayed via Director)
- AH1-App authored brief 2026-05-06 ~21:15Z via `/write-brief` skill (Step 1 EXPLORE verified all line numbers + signatures; Step 2 PLAN ratified by Director "yes" 2026-05-06 ~21:14Z)
- Reference: AH2-T session handover at `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-bm-aihead2/memory/session_handover_2026_05_06_eve_aihead_b_plaud_diag_and_ben_gold_brief.md`

## PL ship-report
End your chat ship report with the fenced PL paste-block per `_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".
