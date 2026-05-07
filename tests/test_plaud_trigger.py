"""Tests for triggers/plaud_trigger.py — covers BRIEF_PLAUD_TRIGGER_FIX_1.

5 surgical patches under test:
1. backfill_plaud is_trans filter (PRIMARY BUG FIX)
2. Stale-refresh lane in check_new_plaud_recordings()
3. _has_empty_db_row helper
4. Post-store empty-body sentinel
5. _extract_transcript_text diagnostic warnings
"""
import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_lock_store_mock(lock_acquired: bool = True) -> MagicMock:
    """Build a SentinelStoreBack mock that grants the advisory lock + returns a usable conn."""
    store = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    # First fetchone is for the pg_try_advisory_lock probe.
    cur.fetchone.return_value = (lock_acquired,)
    conn.cursor.return_value = cur
    store._get_conn.return_value = conn
    store._put_conn.return_value = None
    return store


# ---------------------------------------------------------------------------
# Fix 1 — backfill_plaud must skip is_trans=False
# ---------------------------------------------------------------------------

def test_backfill_skips_un_transcribed():
    """Fix 1: backfill_plaud must skip recordings with is_trans=False."""
    from triggers import plaud_trigger
    from triggers.plaud_trigger import backfill_plaud

    mixed = [
        {"id": "a", "is_trans": True,  "duration": 60000, "start_time": 1_700_000_000_000, "filename": "good"},
        {"id": "b", "is_trans": False, "duration": 60000, "start_time": 1_700_000_001_000, "filename": "bad"},
    ]

    formatted_stub = {
        "text": "Meeting: good\n" + ("x" * 500),
        "metadata": {
            "transcript_id": "a", "meeting_title": "good", "date": "",
            "duration": "1min", "organizer": "", "participants": "",
        },
        "raw_id": "a",
    }

    with patch.object(plaud_trigger.config.plaud, "api_token", "tok"), \
         patch("triggers.plaud_trigger.fetch_plaud_recordings", return_value=mixed), \
         patch("triggers.plaud_trigger.fetch_plaud_detail", return_value={"id": "a"}) as fetch_detail, \
         patch("triggers.plaud_trigger.format_plaud_transcript", return_value=formatted_stub), \
         patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=_make_lock_store_mock(lock_acquired=True)), \
         patch.object(plaud_trigger.trigger_state, "is_processed", return_value=False), \
         patch.object(plaud_trigger.trigger_state, "mark_processed"):
        backfill_plaud()

    fetched_ids = [c.args[0] for c in fetch_detail.call_args_list]
    assert "a" in fetched_ids
    assert "b" not in fetched_ids, "backfill must skip is_trans=False recordings"


# ---------------------------------------------------------------------------
# Fix 2 + 3 — stale-refresh lane + _has_empty_db_row helper
# ---------------------------------------------------------------------------

def test_stale_refresh_re_ingests_empty_db_row():
    """Fix 2 + 3: incremental path re-fetches source_id when DB body < 200 chars (stale shell)."""
    from datetime import datetime, timezone
    from triggers import plaud_trigger
    from triggers.plaud_trigger import check_new_plaud_recordings

    rec = {
        "id": "stale1", "is_trans": True, "duration": 600_000,
        "start_time": 1_800_000_000_000, "filename": "stale",
    }

    formatted_stub = {
        "text": "Meeting: stale\n" + ("y" * 1000),
        "metadata": {
            "transcript_id": "stale1", "meeting_title": "stale", "date": "",
            "duration": "10min", "organizer": "", "participants": "",
        },
        "raw_id": "stale1",
    }

    old_watermark = datetime.fromtimestamp(0, tz=timezone.utc)

    pipeline_mock = MagicMock()

    with patch.object(plaud_trigger.config.plaud, "api_token", "tok"), \
         patch("triggers.sentinel_health.should_skip_poll", return_value=False), \
         patch("triggers.sentinel_health.report_success"), \
         patch("triggers.sentinel_health.report_failure"), \
         patch("triggers.plaud_trigger.fetch_plaud_recordings", return_value=[rec]), \
         patch("triggers.plaud_trigger.fetch_plaud_detail", return_value={"id": "stale1"}) as fetch_detail, \
         patch("triggers.plaud_trigger.format_plaud_transcript", return_value=formatted_stub), \
         patch("triggers.plaud_trigger._has_empty_db_row", return_value=True) as empty_probe, \
         patch.object(plaud_trigger.trigger_state, "get_watermark", return_value=old_watermark), \
         patch.object(plaud_trigger.trigger_state, "is_processed", return_value=True), \
         patch.object(plaud_trigger.trigger_state, "mark_processed"), \
         patch.object(plaud_trigger.trigger_state, "set_watermark"), \
         patch("orchestrator.pipeline.SentinelPipeline", return_value=pipeline_mock), \
         patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=_make_lock_store_mock(lock_acquired=True)) as get_store:
        # store.store_meeting_transcript must be observable
        store_mock = get_store.return_value
        store_mock.store_meeting_transcript = MagicMock()
        store_mock.match_contact_by_name = MagicMock(return_value=None)

        check_new_plaud_recordings()

    # The stale-refresh lane must have probed _has_empty_db_row and re-fetched detail.
    assert empty_probe.called, "stale-refresh must call _has_empty_db_row when is_processed=True"
    fetched_ids = [c.args[0] for c in fetch_detail.call_args_list]
    assert "stale1" in fetched_ids, "fetch_plaud_detail must be called for stale source_id"
    # Full body must be stored (upsert path).
    assert store_mock.store_meeting_transcript.called, "store_meeting_transcript must be called on stale-refresh"
    call_kwargs = store_mock.store_meeting_transcript.call_args.kwargs
    assert call_kwargs.get("transcript_id") == "plaud_stale1"
    assert len(call_kwargs.get("full_transcript") or "") > 200


def test_has_empty_db_row_lt_threshold():
    """Fix 3: helper returns True for short body, False for long body, False for missing row."""
    from triggers.plaud_trigger import _has_empty_db_row

    def _store_with_fetchone(value):
        store = MagicMock()
        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = value
        conn.cursor.return_value = cur
        store._get_conn.return_value = conn
        return store

    # Case 1: short body (50 chars) — True
    short_store = _store_with_fetchone((50,))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=short_store):
        assert _has_empty_db_row("plaud_x", threshold=200) is True

    # Case 2: long body (500 chars) — False
    long_store = _store_with_fetchone((500,))
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=long_store):
        assert _has_empty_db_row("plaud_x", threshold=200) is False

    # Case 3: no row — False
    none_store = _store_with_fetchone(None)
    with patch("memory.store_back.SentinelStoreBack._get_global_instance", return_value=none_store):
        assert _has_empty_db_row("plaud_x", threshold=200) is False


# ---------------------------------------------------------------------------
# Fix 4 — post-store empty-body sentinel
# ---------------------------------------------------------------------------

def test_empty_body_sentinel_fires():
    """Fix 4: report_failure called when duration>5min + body<200 + is_trans=True (incremental path)."""
    from datetime import datetime, timezone
    from triggers import plaud_trigger
    from triggers.plaud_trigger import check_new_plaud_recordings

    # Recording with 10-min duration, is_trans=True, but extracted body will be empty.
    rec = {
        "id": "empty1", "is_trans": True, "duration": 600_000,
        "start_time": 1_800_000_001_000, "filename": "empty",
    }

    # formatted.text < 200 chars (header-only shell mimics broken-backfill output).
    formatted_stub = {
        "text": "Meeting: empty\nDate: 2026-05-07 00:00 UTC\nDuration: 10min\n",  # ~60 chars
        "metadata": {
            "transcript_id": "empty1", "meeting_title": "empty", "date": "",
            "duration": "10min", "organizer": "", "participants": "",
        },
        "raw_id": "empty1",
    }

    old_watermark = datetime.fromtimestamp(0, tz=timezone.utc)
    pipeline_mock = MagicMock()

    with patch.object(plaud_trigger.config.plaud, "api_token", "tok"), \
         patch("triggers.sentinel_health.should_skip_poll", return_value=False), \
         patch("triggers.sentinel_health.report_success"), \
         patch("triggers.sentinel_health.report_failure") as report_failure, \
         patch("triggers.plaud_trigger.fetch_plaud_recordings", return_value=[rec]), \
         patch("triggers.plaud_trigger.fetch_plaud_detail", return_value={"id": "empty1"}), \
         patch("triggers.plaud_trigger.format_plaud_transcript", return_value=formatted_stub), \
         patch.object(plaud_trigger.trigger_state, "get_watermark", return_value=old_watermark), \
         patch.object(plaud_trigger.trigger_state, "is_processed", return_value=False), \
         patch.object(plaud_trigger.trigger_state, "mark_processed"), \
         patch.object(plaud_trigger.trigger_state, "set_watermark"), \
         patch("orchestrator.pipeline.SentinelPipeline", return_value=pipeline_mock), \
         patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=_make_lock_store_mock(lock_acquired=True)):
        check_new_plaud_recordings()

    plaud_failures = [c for c in report_failure.call_args_list if c.args and c.args[0] == "plaud"]
    assert len(plaud_failures) == 1, f"expected exactly 1 plaud sentinel failure, got {len(plaud_failures)}"
    assert "empty-body-after-transcription" in plaud_failures[0].args[1]
    assert "plaud_empty1" in plaud_failures[0].args[1]


# ---------------------------------------------------------------------------
# Fix 5 — _extract_transcript_text diagnostic warnings
# ---------------------------------------------------------------------------

def test_extract_transcript_text_logs_warnings(caplog):
    """Fix 5: warnings logged for missing transaction URL + empty S3 segments."""
    from triggers.plaud_trigger import _extract_transcript_text

    # Case 1: detail without transaction URL → WARNING.
    with caplog.at_level(logging.WARNING, logger="sentinel.trigger.plaud"):
        caplog.clear()
        result = _extract_transcript_text({"id": "no-url-file", "content_list": []})
        assert result == ""
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no transaction URL" in r.getMessage() for r in warn_records), \
            "missing-URL path must emit WARNING"
        assert any("no-url-file" in r.getMessage() for r in warn_records), \
            "WARNING must include file_id"

    # Case 2: detail with URL but empty S3 segments → WARNING.
    detail_with_url = {
        "id": "empty-s3-file",
        "content_list": [{
            "data_type": "transaction", "task_status": 1,
            "data_link": "https://example.com/path/seg.json.gz?X-Amz-Signature=abc&X-Amz-Credential=def",
        }],
    }
    with caplog.at_level(logging.WARNING, logger="sentinel.trigger.plaud"):
        caplog.clear()
        with patch("triggers.plaud_trigger._fetch_s3_content", return_value=None):
            result = _extract_transcript_text(detail_with_url)
        assert result == ""
        warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("empty/invalid S3 segments" in r.getMessage() for r in warn_records), \
            "empty-segments path must emit WARNING"
        # url-tail must NOT include query-string signing material.
        for r in warn_records:
            msg = r.getMessage()
            assert "X-Amz-Signature" not in msg, "url-tail leaked signing material"
            assert "X-Amz-Credential" not in msg, "url-tail leaked signing material"


# ---------------------------------------------------------------------------
# I1 — empty-body sentinel per-source_id-per-day dedup (alarm fatigue fix)
# ---------------------------------------------------------------------------

def test_empty_body_sentinel_dedup_per_source_id():
    """I1: empty-body sentinel fires exactly once per source_id per UTC day, even when
    same broken recording is observed across multiple poll cycles."""
    from datetime import datetime, timezone
    from triggers import plaud_trigger
    from triggers.plaud_trigger import check_new_plaud_recordings

    rec = {
        "id": "stuck1", "is_trans": True, "duration": 600_000,
        "start_time": 1_800_000_010_000, "filename": "stuck",
    }
    formatted_stub = {
        # ~30 chars — sub-200 threshold mimics broken-backfill shell.
        "text": "Meeting: stuck\nDate: 2026-05-07\n",
        "metadata": {
            "transcript_id": "stuck1", "meeting_title": "stuck", "date": "",
            "duration": "10min", "organizer": "", "participants": "",
        },
        "raw_id": "stuck1",
    }

    # Stateful is_processed/mark_processed emulating real trigger_log dedup.
    state = {"meeting": set(), "plaud_alarm": set()}

    def is_processed_se(kind, sid):
        return sid in state.get(kind, set())

    def mark_processed_se(kind, sid):
        state.setdefault(kind, set()).add(sid)

    pipeline_mock = MagicMock()
    old_watermark = datetime.fromtimestamp(0, tz=timezone.utc)

    with patch.object(plaud_trigger.config.plaud, "api_token", "tok"), \
         patch("triggers.sentinel_health.should_skip_poll", return_value=False), \
         patch("triggers.sentinel_health.report_success"), \
         patch("triggers.sentinel_health.report_failure") as report_failure, \
         patch("triggers.plaud_trigger.fetch_plaud_recordings", return_value=[rec]), \
         patch("triggers.plaud_trigger.fetch_plaud_detail", return_value={"id": "stuck1"}), \
         patch("triggers.plaud_trigger.format_plaud_transcript", return_value=formatted_stub), \
         patch("triggers.plaud_trigger._has_empty_db_row", return_value=True), \
         patch.object(plaud_trigger.trigger_state, "get_watermark", return_value=old_watermark), \
         patch.object(plaud_trigger.trigger_state, "is_processed", side_effect=is_processed_se), \
         patch.object(plaud_trigger.trigger_state, "mark_processed", side_effect=mark_processed_se), \
         patch.object(plaud_trigger.trigger_state, "set_watermark"), \
         patch("orchestrator.pipeline.SentinelPipeline", return_value=pipeline_mock), \
         patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=_make_lock_store_mock(lock_acquired=True)):
        # Two consecutive polls — same broken recording observed twice.
        check_new_plaud_recordings()
        check_new_plaud_recordings()

    plaud_failures = [c for c in report_failure.call_args_list if c.args and c.args[0] == "plaud"]
    assert len(plaud_failures) == 1, \
        f"I1 dedup: expected exactly 1 plaud sentinel failure, got {len(plaud_failures)}"
    assert "empty-body-after-transcription" in plaud_failures[0].args[1]
    assert "plaud_stuck1" in plaud_failures[0].args[1]


# ---------------------------------------------------------------------------
# I2 — stale-refresh advisory lock (multi-instance race fix)
# ---------------------------------------------------------------------------

def test_stale_refresh_advisory_lock_skips_when_held():
    """I2: when pg_try_advisory_xact_lock fails (peer instance owns it), stale-refresh
    skips the iteration cleanly — no fetch_plaud_detail, no store, no Qdrant write."""
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from triggers import plaud_trigger
    from triggers.plaud_trigger import check_new_plaud_recordings

    rec = {
        "id": "lockheld1", "is_trans": True, "duration": 600_000,
        "start_time": 1_800_000_020_000, "filename": "lockheld",
    }

    @contextmanager
    def fake_lock_unacquired(source_id):
        # Peer instance owns the lock — we never acquire.
        yield False

    pipeline_mock = MagicMock()
    old_watermark = datetime.fromtimestamp(0, tz=timezone.utc)

    with patch.object(plaud_trigger.config.plaud, "api_token", "tok"), \
         patch("triggers.sentinel_health.should_skip_poll", return_value=False), \
         patch("triggers.sentinel_health.report_success"), \
         patch("triggers.sentinel_health.report_failure"), \
         patch("triggers.plaud_trigger.fetch_plaud_recordings", return_value=[rec]), \
         patch("triggers.plaud_trigger.fetch_plaud_detail") as fetch_detail, \
         patch("triggers.plaud_trigger.format_plaud_transcript") as fmt, \
         patch("triggers.plaud_trigger._has_empty_db_row", return_value=True), \
         patch("triggers.plaud_trigger._stale_refresh_advisory_lock", side_effect=fake_lock_unacquired), \
         patch.object(plaud_trigger.trigger_state, "get_watermark", return_value=old_watermark), \
         patch.object(plaud_trigger.trigger_state, "is_processed", return_value=True), \
         patch.object(plaud_trigger.trigger_state, "mark_processed"), \
         patch.object(plaud_trigger.trigger_state, "set_watermark"), \
         patch("orchestrator.pipeline.SentinelPipeline", return_value=pipeline_mock), \
         patch("memory.store_back.SentinelStoreBack._get_global_instance",
               return_value=_make_lock_store_mock(lock_acquired=True)) as get_store:
        store_mock = get_store.return_value
        store_mock.store_meeting_transcript = MagicMock()
        check_new_plaud_recordings()

        assert not fetch_detail.called, \
            "fetch_plaud_detail must not be called when stale-refresh lock not acquired"
        assert not fmt.called, \
            "format_plaud_transcript must not be called when stale-refresh lock not acquired"
        assert not store_mock.store_meeting_transcript.called, \
            "store_meeting_transcript must not be called when stale-refresh lock not acquired"
