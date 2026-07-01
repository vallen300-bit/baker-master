"""BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1 — the sink dedups + stores PER-MESSAGE.

Regression for a P0 silent drop: `triggers.email_trigger._process_email_threads`
keyed the persistent dedup + the storage `message_id` on `thread_id` (=conversationId),
so the first message on a conversation was stored and EVERY subsequent reply hit
`is_processed`=True → `continue` → was never stored / pipelined / routed. Cross-source
(gmail / graph / exchange / bluewin all funnel through this sink).

Fix: key on a stable per-message id — `metadata['message_id'] or thread_id`
(gmail=latest msg id; graph=m['id']; exchange/bluewin thread_id IS already the RFC822
Message-ID). thread_id stays as the correlation/routing context only.

AC1 + AC4b MUST FAIL on current `main` (thread_id-keyed) and PASS after the fix.
"""
from unittest import mock

import pytest

import triggers.email_trigger as et


def _thread(msg_id, conv_id, *, subject="status update", body="body text",
            sender="counterparty@aukera.lu", source="graph",
            received="2026-07-01T13:09:46+00:00"):
    """A sink-shaped thread dict. msg_id=None models exchange/bluewin (no metadata
    message_id → the sink falls back to thread_id, which for those sources IS the
    per-message RFC822 Message-ID)."""
    md = {
        "source": source,
        "thread_id": conv_id,
        "subject": subject,
        "primary_sender": "Sender",
        "primary_sender_email": sender,
        "received_date": received,
    }
    if msg_id is not None:
        md["message_id"] = msg_id
    return {"text": f"Email Thread: {subject}\n\n{body}", "metadata": md}


class _Sink:
    """Drives _process_email_threads with the sink's external deps mocked. Persists the
    'processed' set across .run() calls to model cross-cycle trigger_log persistence."""

    def __init__(self, already_processed=None):
        self.processed = set(already_processed or [])
        self.marked = []
        self.store = mock.MagicMock(name="store")
        self.store.match_contact_by_name.return_value = None   # skip interaction branch
        self.pipe_cls = mock.MagicMock(name="SentinelPipeline")
        self.pipe_cls.return_value.classify_trigger.side_effect = (
            lambda t: mock.MagicMock(priority="high")           # force pipeline.run path
        )

    def run(self, threads):
        def _is_processed(source, key):
            return key in self.processed

        def _mark(source, key):
            self.marked.append(key)
            self.processed.add(key)

        with mock.patch.object(et.trigger_state, "is_processed", side_effect=_is_processed), \
             mock.patch.object(et.trigger_state, "mark_processed", side_effect=_mark), \
             mock.patch.object(et.trigger_state, "set_watermark"), \
             mock.patch("orchestrator.pipeline.SentinelPipeline", self.pipe_cls), \
             mock.patch("memory.store_back.SentinelStoreBack._get_global_instance",
                        return_value=self.store), \
             mock.patch.object(et, "_check_reply_match"), \
             mock.patch.object(et, "_is_meeting_email", return_value=False), \
             mock.patch("orchestrator.deadline_manager.extract_deadlines"), \
             mock.patch("orchestrator.pm_signal_detector.detect_relevant_pms_text",
                        return_value=[]):
            et._process_email_threads(threads)

    @property
    def stored_ids(self):
        return [c.kwargs.get("message_id")
                for c in self.store.store_email_message.call_args_list]

    @property
    def stored_thread_ids(self):
        return [c.kwargs.get("thread_id")
                for c in self.store.store_email_message.call_args_list]

    @property
    def run_count(self):
        return self.pipe_cls.return_value.run.call_count


# ── AC1 (regression — MUST fail on main) ─────────────────────────────────────
def test_ac1_reply_on_same_conversation_both_stored_across_cycles():
    """Two messages on the SAME conversationId across two poll cycles → BOTH stored
    (2 distinct rows) + BOTH pipelined. On main (thread_id-keyed) the reply is dropped."""
    conv = "AAQk-ESG-conversation"
    sink = _Sink()
    sink.run([_thread("AAMk-msg-A", conv, subject="AB Sprint FW: Q&A / ESG")])       # cycle 1
    sink.run([_thread("AAMk-msg-B", conv, subject="AW: AB Sprint FW: Q&A / ESG")])   # cycle 2

    assert sink.stored_ids == ["AAMk-msg-A", "AAMk-msg-B"]   # both replies persisted
    assert sink.stored_thread_ids == [conv, conv]            # thread_id column = conversationId
    assert sink.marked == ["AAMk-msg-A", "AAMk-msg-B"]       # dedup marked per-message
    assert sink.run_count == 2                                # both produced a pipeline event


# ── AC2 (ALERT-DEDUP-1 property — no repeat processing) ──────────────────────
def test_ac2_no_new_store_or_pipeline_when_no_new_message():
    """Re-polling the SAME message (same per-message key) stores nothing new and does
    not re-run the pipeline — the old 'repeat every cycle' trap is not reintroduced."""
    conv = "conv-1"
    sink = _Sink()
    sink.run([_thread("msg-A", conv)])
    sink.run([_thread("msg-A", conv)])                        # identical re-poll

    assert sink.stored_ids == ["msg-A"]                       # stored exactly once
    assert sink.run_count == 1                                # pipeline ran exactly once


# ── AC3 (cross-source per-message key resolution) ────────────────────────────
@pytest.mark.parametrize("source,msg_id,thread_id,expected", [
    ("gmail", "gmail-msg-9", "gmail-thread-1", "gmail-msg-9"),   # gmail → latest message id
    ("graph", "AAMk-per-msg", "AAQk-conv", "AAMk-per-msg"),      # graph → m['id']
    ("exchange", None, "rfc-mid-exchange", "rfc-mid-exchange"),  # exchange → thread_id (=Message-ID)
    ("bluewin", None, "rfc-mid-bluewin", "rfc-mid-bluewin"),     # bluewin → thread_id (=Message-ID)
])
def test_ac3_per_source_key_resolution(source, msg_id, thread_id, expected):
    sink = _Sink()
    sink.run([_thread(msg_id, thread_id, source=source)])
    assert sink.stored_ids == [expected]
    assert sink.marked == [expected]


# ── AC4 (within-cycle pagination dup still collapses) ────────────────────────
def test_ac4_within_cycle_paginated_duplicate_collapses():
    """Same thread returned twice in ONE poll with the SAME latest message id (Gmail
    pagination) → stored once (within-cycle guard holds at the per-message key)."""
    conv = "conv-1"
    sink = _Sink()
    sink.run([_thread("msg-A", conv), _thread("msg-A", conv)])
    assert sink.stored_ids == ["msg-A"]
    assert sink.run_count == 1


def test_ac4b_graph_multi_message_same_conversation_one_cycle_all_stored():
    """Graph's per-folder delta can return TWO messages of the same conversationId as
    separate dicts in ONE poll. Both must store — the intra-cycle drop the per-message
    within-guard fixes. FAILS on main (thread-level within-cycle guard collapses them)."""
    conv = "conv-1"
    sink = _Sink()
    sink.run([_thread("msg-A", conv), _thread("msg-B", conv)])
    assert sink.stored_ids == ["msg-A", "msg-B"]
    assert sink.run_count == 2


# ── canary shape (AC6 proxy): the exact ESG reply is accepted, keyed on its msg id ──
def test_esg_reply_accepted_after_earlier_thread_message():
    """The real failure: the Aukera/ESG conversation was first seen (an earlier message
    already marked processed), then Siegfried's reply arrived on the same conversationId.
    With the fix the reply is accepted and stored under its own message id."""
    conv = "AAQkAGEz-ESGthread"
    # earlier message on this conversation already processed in a prior cycle:
    sink = _Sink(already_processed=set())
    sink.run([_thread("AAMk-earlier", conv, subject="FW: AB Sprint FW: Q&A / ESG / Debt Model",
                      sender="balazs.csepregi@brisengroup.com")])
    sink.run([_thread("AAMk-siegfried-reply", conv,
                      subject="AW: AB Sprint FW: Q&A / ESG / Debt Model",
                      sender="siegfried.brandner@brisengroup.com")])
    assert "AAMk-siegfried-reply" in sink.stored_ids          # the previously-dropped reply lands
