"""BACKFILL_VERIFY_1: unit tests for the verification harness pure logic.

No network, no DB — counts/sample/verdict logic only (live collectors are
exercised at RUN time against the real mailboxes/store).

INGESTION_COMPLETENESS_P0_MEASURE_1 adds baseline-mode tests at the bottom
(compute_lag / evaluate_presence_checks / build_baseline_report / run_baseline),
likewise mocked-core only."""
from datetime import datetime, timedelta, timezone
import hashlib

import pytest

import scripts.verify_backfill as vb
from scripts.verify_backfill import (
    build_baseline_report,
    build_verdict,
    compare_counts,
    compute_lag,
    deterministic_order_key,
    evaluate_attachment_checks,
    evaluate_message_checks,
    evaluate_presence_checks,
    pick_imap_allowlist,
    run_baseline,
    run_verification,
    source_ok,
)


# ---------------------------------------------------------------- counts

def test_compare_counts_pass_at_tolerance():
    res = compare_counts({"INBOX": 100, "Sent": 100}, store_count=196)
    assert res["mailbox_total"] == 200
    assert res["ratio"] == 0.98
    assert res["ok"] is True


def test_compare_counts_fail_below_tolerance():
    res = compare_counts({"INBOX": 200}, store_count=195)
    assert res["ok"] is False
    assert res["ratio"] == 0.975


def test_compare_counts_zero_mailbox_is_fail():
    # Empty mailbox = nothing verified — must not read as PASS.
    res = compare_counts({}, store_count=0)
    assert res["ok"] is False
    assert res["mailbox_total"] == 0


def test_compare_counts_keeps_explicit_folder_numbers():
    folders = {"INBOX": 7, "Archive": 3}
    res = compare_counts(folders, store_count=10)
    assert res["folders"] == folders  # AC1: per-folder numbers preserved verbatim


def test_compare_counts_store_exceeding_mailbox_passes():
    # Store can hold more than the mailbox (forward poller rows) — still a pass.
    res = compare_counts({"INBOX": 50}, store_count=60)
    assert res["ok"] is True


# ------------------------------------------------------- folder allowlists

def test_allowlist_restricts_tolerance_to_named_folders():
    # Lead bus #2756: Drafts/Spam noise must not false-FAIL the backfill lanes.
    folders = {"INBOX": 100, "Sent": 50, "Drafts": 30, "Spam": 400}
    res = compare_counts(folders, store_count=148, allowlist=["INBOX", "Sent"])
    assert res["mailbox_total"] == 150          # allowlisted only
    assert res["counted_folders"] == {"INBOX": 100, "Sent": 50}
    assert res["folders"] == folders            # all-folder numbers kept as info
    assert res["ok"] is True                    # 148/150 >= 0.98


def test_allowlist_match_is_space_and_case_insensitive():
    # Graph default 'SentItems' must match displayName 'Sent Items'.
    res = compare_counts({"Inbox": 10, "Sent Items": 5}, store_count=15,
                         allowlist=["inbox", "SentItems"])
    assert res["counted_folders"] == {"Inbox": 10, "Sent Items": 5}
    assert res["ok"] is True


def test_allowlist_missing_folder_fails_loud():
    res = compare_counts({"INBOX": 100}, store_count=100,
                         allowlist=["INBOX", "Sent"])
    assert res["ok"] is False
    assert res["allowlist_missing"] == ["Sent"]


def test_pick_imap_allowlist_prefers_special_use_flag():
    counts = {"INBOX": 1, "Gesendet": 1, "Sent": 1}
    flags = {"Gesendet": "\\HasNoChildren \\Sent"}
    assert pick_imap_allowlist(counts, flags) == ["INBOX", "Gesendet"]


def test_pick_imap_allowlist_name_fallback():
    counts = {"INBOX": 1, "Sent Items": 1, "Drafts": 1}
    assert pick_imap_allowlist(counts, {}) == ["INBOX", "Sent Items"]


def test_pick_imap_allowlist_inbox_only_when_no_sent_detectable():
    assert pick_imap_allowlist({"INBOX": 1, "Misc": 1}, {}) == ["INBOX"]


# ---------------------------------------------------------------- sampling

def test_deterministic_order_key_is_stable_and_seed_sensitive():
    a1 = deterministic_order_key("msg-1", "seed-a")
    a2 = deterministic_order_key("msg-1", "seed-a")
    b = deterministic_order_key("msg-1", "seed-b")
    assert a1 == a2          # same (id, seed) -> same key: sample reproducible
    assert a1 != b           # different seed -> different sample order
    assert a1 == hashlib.md5(b"msg-1seed-a").hexdigest()  # matches SQL md5(id||seed)


# ---------------------------------------------------------------- messages

def test_message_checks_pass():
    rows = [{"message_id": f"m{i}", "body_len": 100, "searchable": True}
            for i in range(10)]
    res = evaluate_message_checks(rows)
    assert res["ok"] is True
    assert res["passed"] == [f"m{i}" for i in range(10)]
    assert res["failures"] == []


def test_message_checks_empty_body_fails_loud():
    rows = [{"message_id": "m1", "body_len": 0, "searchable": True}]
    res = evaluate_message_checks(rows)
    assert res["ok"] is False
    assert res["failures"] == ["m1: empty body"]


def test_message_checks_unsearchable_fails_loud():
    rows = [{"message_id": "m1", "body_len": 50, "searchable": False}]
    res = evaluate_message_checks(rows)
    assert res["ok"] is False
    assert "NOT found via email search path" in res["failures"][0]


def test_message_checks_skipped_search_is_note_not_fail():
    rows = [{"message_id": "m1", "body_len": 50, "searchable": None,
             "skip_reason": "no subject/sender token to search on"}]
    res = evaluate_message_checks(rows)
    assert res["ok"] is True
    assert len(res["notes"]) == 1


def test_message_checks_zero_rows_is_fail():
    # No sampled messages = nothing verified — must not read as PASS.
    assert evaluate_message_checks([])["ok"] is False


# ---------------------------------------------------------------- attachments

def _att_row(payload: bytes, **over):
    row = {
        "att_id": 1, "message_id": "m1",
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload), "data": payload, "storage": "db",
    }
    row.update(over)
    return row


def test_attachment_checks_pass_on_matching_hash_and_size():
    res = evaluate_attachment_checks([_att_row(b"hello world")])
    assert res["ok"] is True
    assert len(res["passed"]) == 1


def test_attachment_checks_hash_mismatch_fails_loud():
    res = evaluate_attachment_checks(
        [_att_row(b"hello world", content_sha256="0" * 64)])
    assert res["ok"] is False
    assert "sha256 mismatch" in res["failures"][0]


def test_attachment_checks_size_mismatch_fails_loud():
    res = evaluate_attachment_checks([_att_row(b"hello world", size_bytes=999)])
    assert res["ok"] is False
    assert "size mismatch" in res["failures"][0]


def test_attachment_checks_null_data_on_db_storage_fails():
    res = evaluate_attachment_checks([_att_row(b"x", data=None)])
    assert res["ok"] is False
    assert "data is NULL" in res["failures"][0]


def test_attachment_checks_metadata_only_without_data_passes():
    res = evaluate_attachment_checks(
        [_att_row(b"x", data=None, storage="metadata_only")])
    assert res["ok"] is True
    assert "metadata_only" in res["passed"][0]


def test_attachment_checks_metadata_only_with_data_fails():
    res = evaluate_attachment_checks(
        [_att_row(b"x", storage="metadata_only")])
    assert res["ok"] is False
    assert "carries data bytes" in res["failures"][0]


def test_attachment_checks_zero_rows_is_fail():
    assert evaluate_attachment_checks([])["ok"] is False


# ---------------------------------------------------------------- verdict

def _passing_results():
    return {
        "bluewin": {
            "counts": compare_counts({"INBOX": 100}, 99),
            "messages": evaluate_message_checks(
                [{"message_id": "m1", "body_len": 10, "searchable": True}]),
            "attachments": evaluate_attachment_checks([_att_row(b"data")]),
        },
        "graph": {
            "counts": compare_counts({"Inbox": 50, "Sent Items": 10}, 60),
            "messages": evaluate_message_checks(
                [{"message_id": "g1", "body_len": 10, "searchable": True}]),
            "attachments": evaluate_attachment_checks([_att_row(b"gdata", att_id=2)]),
        },
    }


REQUIRED_V1_LINES = (
    "POST_DEPLOY_AC_VERDICT v1",
    "brief: BACKFILL_VERIFY_1",
    "task_class: ",
    "commit: abc1234",
    "deploy: ",
    "surface_checked: ",
    "ac_result: ",
    "evidence: ",
    "done_state: ",
    "writeback: ",
    "next_action: ",
)


def test_verdict_has_exact_v1_shape():
    out = build_verdict(_passing_results(), commit="abc1234")
    block = out.split("POST_DEPLOY_AC_VERDICT v1", 1)
    assert len(block) == 2, "verdict block missing"
    for marker in REQUIRED_V1_LINES:
        assert marker in out, f"missing v1 line: {marker}"
    # v1 field order preserved (skill-locked shape)
    verdict = "POST_DEPLOY_AC_VERDICT v1" + block[1]
    fields = [l.split(":")[0] for l in verdict.splitlines()[1:]]
    assert fields == ["brief", "task_class", "commit", "deploy", "surface_checked",
                      "ac_result", "evidence", "done_state", "writeback", "next_action"]


def test_verdict_pass_when_all_ok():
    out = build_verdict(_passing_results(), commit="abc1234")
    assert "ac_result: PASS" in out
    assert "done_state: DONE" in out
    assert "next_action: none" in out


def test_verdict_fail_and_not_done_on_any_failure():
    results = _passing_results()
    results["bluewin"]["counts"] = compare_counts({"INBOX": 100}, 50)
    out = build_verdict(results, commit="abc1234")
    assert "ac_result: FAIL" in out
    assert "done_state: NOT_DONE" in out
    assert "next_action: none" not in out


def test_verdict_lists_explicit_numbers_and_ids():
    out = build_verdict(_passing_results(), commit="abc1234")
    assert "mailbox folder 'INBOX': 100" in out          # AC1 explicit numbers
    assert "mailbox_total=100 store_count=99" in out
    assert "PASS m1" in out                              # AC2 named message ids
    assert "sha=" in out                                 # AC2 named attachment hashes


def test_verdict_prints_allowlist_and_info_only_tags():
    results = _passing_results()
    results["bluewin"]["counts"] = compare_counts(
        {"INBOX": 100, "Drafts": 7}, 99, allowlist=["INBOX"])
    out = build_verdict(results, commit="abc1234")
    assert "allowlist: INBOX" in out
    assert "mailbox folder 'INBOX': 100 [counted]" in out
    assert "mailbox folder 'Drafts': 7 [info-only]" in out
    assert "ac_result: PASS" in out             # Drafts noise excluded from tolerance


def test_verdict_missing_allowlist_folder_listed_loud():
    results = _passing_results()
    results["bluewin"]["counts"] = compare_counts(
        {"INBOX": 100}, 100, allowlist=["INBOX", "Sent"])
    out = build_verdict(results, commit="abc1234")
    assert "FAIL allowlist folder 'Sent' not found on mailbox" in out
    assert "ac_result: FAIL" in out


def test_verdict_failures_listed_loud():
    results = _passing_results()
    results["graph"]["messages"] = evaluate_message_checks(
        [{"message_id": "g9", "body_len": 0, "searchable": None}])
    out = build_verdict(results, commit="abc1234")
    assert "FAIL g9: empty body" in out                  # AC4 loud, named failure
    assert "ac_result: FAIL" in out


# ----------------------------------------- never-raise contract (G3 S1, #2772)

class _DummyConn:
    def close(self):
        pass


def _patch_happy_collectors(monkeypatch):
    monkeypatch.setattr(vb, "_db_conn", lambda: _DummyConn())
    monkeypatch.setattr(vb, "imap_folder_counts", lambda: ({"INBOX": 10}, {}))
    monkeypatch.setattr(vb, "store_count", lambda conn, source: 10)
    monkeypatch.setattr(
        vb, "spot_check_messages",
        lambda *a, **k: [{"message_id": "m1", "body_len": 5, "searchable": True}])
    monkeypatch.setattr(
        vb, "spot_check_attachments", lambda *a, **k: [_att_row(b"x")])


def test_run_verification_emits_verdict_when_store_count_raises(monkeypatch):
    _patch_happy_collectors(monkeypatch)

    def boom(conn, source):
        raise RuntimeError("store down")
    monkeypatch.setattr(vb, "store_count", boom)

    results = run_verification(("bluewin",), "seed")     # must NOT raise
    res = results["bluewin"]
    assert any("store count failed" in e for e in res["collector_failures"])
    assert res["counts"]["folders"] == {"INBOX": 10}     # mailbox numbers preserved
    assert res["counts"]["store_count"] == -1            # gap marked, not hidden
    assert source_ok(res) is False
    out = build_verdict(results, commit="abc1234")       # full verdict still emitted
    assert "POST_DEPLOY_AC_VERDICT v1" in out
    assert "FAIL collector: store count failed: store down" in out
    assert "ac_result: FAIL" in out
    assert "done_state: NOT_DONE" in out
    assert "collector_failures 1" in out                 # surfaced in evidence line


def test_run_verification_emits_verdict_when_db_connect_raises(monkeypatch):
    _patch_happy_collectors(monkeypatch)

    def no_db():
        raise RuntimeError("DATABASE_URL not set")
    monkeypatch.setattr(vb, "_db_conn", no_db)

    results = run_verification(("bluewin",), "seed")     # must NOT raise
    res = results["bluewin"]
    assert any("db connection failed" in e for e in res["collector_failures"])
    out = build_verdict(results, commit="abc1234")
    assert "POST_DEPLOY_AC_VERDICT v1" in out
    assert "ac_result: FAIL" in out


def test_run_verification_emits_verdict_when_sampler_raises(monkeypatch):
    _patch_happy_collectors(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("attachment table missing")
    monkeypatch.setattr(vb, "spot_check_attachments", boom)

    results = run_verification(("bluewin",), "seed")     # must NOT raise
    res = results["bluewin"]
    assert any("attachment spot-check failed" in e for e in res["collector_failures"])
    assert res["counts"]["ok"] is True                   # healthy sections kept
    assert res["messages"]["ok"] is True
    assert source_ok(res) is False                       # but source still FAILs
    assert "ac_result: FAIL" in build_verdict(results, commit="abc1234")


def test_run_verification_all_collectors_healthy_passes(monkeypatch):
    _patch_happy_collectors(monkeypatch)
    results = run_verification(("bluewin",), "seed")
    res = results["bluewin"]
    assert res["collector_failures"] == []
    assert source_ok(res) is True
    assert "ac_result: PASS" in build_verdict(results, commit="abc1234")


def test_source_ok_false_on_collector_failures():
    res = _passing_results()["bluewin"]
    res["collector_failures"] = ["mailbox count collection failed: boom"]
    assert source_ok(res) is False


# ======================================================================
# INGESTION_COMPLETENESS_P0_MEASURE_1 — baseline-mode pure logic + run_baseline
# ======================================================================

_NOW = datetime(2026, 6, 29, 18, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------- compute_lag

def test_compute_lag_within_poll_interval():
    res = compute_lag(_NOW - timedelta(seconds=120), _NOW, 300, "ingest")
    assert res["lag_seconds"] == 120
    assert res["poll_interval_s"] == 300
    assert res["within_interval"] is True


def test_compute_lag_exceeds_poll_interval_fails_loud():
    res = compute_lag(_NOW - timedelta(seconds=1800), _NOW, 300, "ingest")
    assert res["lag_seconds"] == 1800
    assert res["within_interval"] is False
    assert "EXCEEDS" in res["note"]


def test_compute_lag_none_timestamp_is_unmeasurable_not_crash():
    res = compute_lag(None, _NOW, 300, "ingest")
    assert res["lag_seconds"] is None
    assert res["within_interval"] is None
    assert "unmeasurable" in res["note"]


def test_compute_lag_event_driven_source_has_no_poll_verdict():
    # whatsapp is webhook-driven: poll_interval None -> within_interval None.
    res = compute_lag(_NOW - timedelta(seconds=60), _NOW, None, "ingest")
    assert res["lag_seconds"] == 60
    assert res["within_interval"] is None
    assert "event-driven" in res["note"]


# ------------------------------------------------------- evaluate_presence_checks

def test_presence_checks_pass_all_present_nonempty():
    rows = [{"id": f"rec{i}", "present": True, "body_len": 100} for i in range(5)]
    res = evaluate_presence_checks(rows)
    assert res["ok"] is True
    assert res["passed"] == [f"rec{i}" for i in range(5)]


def test_presence_checks_absent_fails_loud():
    res = evaluate_presence_checks([{"id": "rec1", "present": False, "body_len": 0}])
    assert res["ok"] is False
    assert "ABSENT in store" in res["failures"][0]


def test_presence_checks_present_but_empty_body_fails():
    res = evaluate_presence_checks([{"id": "rec1", "present": True, "body_len": 0}])
    assert res["ok"] is False
    assert "EMPTY body" in res["failures"][0]


def test_presence_checks_extra_fail_surfaced():
    res = evaluate_presence_checks(
        [{"id": "wa1", "present": True, "body_len": 5, "extra_fail": "chat_id null"}])
    assert res["ok"] is False
    assert "chat_id null" in res["failures"][0]


def test_presence_checks_zero_rows_is_fail():
    assert evaluate_presence_checks([])["ok"] is False


def test_presence_checks_present_defaults_true():
    # store-row samples omit `present` (they're already in the store).
    res = evaluate_presence_checks([{"id": "wa1", "body_len": 10}])
    assert res["ok"] is True


# ----------------------------------------------------- run_baseline (mocked-core)

class _DummyBaselineConn:
    def cursor(self):
        raise AssertionError("run_baseline must use mocked collectors, not raw cursor")

    def rollback(self):
        pass

    def close(self):
        pass


def _patch_baseline_collectors(monkeypatch):
    monkeypatch.setattr(vb, "_db_conn", lambda: _DummyBaselineConn())
    monkeypatch.setattr(vb, "_poll_intervals",
                        lambda: {"bluewin": 300, "graph": 300, "plaud": 900, "whatsapp": None})
    # email
    monkeypatch.setattr(vb, "imap_folder_counts", lambda: ({"INBOX": 100, "Sent": 50}, {}))
    monkeypatch.setattr(vb, "graph_folder_counts", lambda: {"Inbox": 100, "Sent Items": 50})
    monkeypatch.setattr(vb, "store_count", lambda conn, source: 149)
    monkeypatch.setattr(
        vb, "spot_check_messages",
        lambda conn, source, n, seed: [
            {"message_id": f"{source}-m{i}", "body_len": 10, "searchable": True}
            for i in range(n)])
    # plaud
    monkeypatch.setattr(vb, "plaud_truth", lambda: (200, [f"rec{i}" for i in range(200)]))
    monkeypatch.setattr(vb, "meeting_store_count", lambda conn, source="plaud": 199)
    monkeypatch.setattr(
        vb, "plaud_sample",
        lambda conn, ids, n, seed: [{"id": i, "present": True, "body_len": 500}
                                    for i in ids[:n]])
    # whatsapp
    monkeypatch.setattr(vb, "whatsapp_truth_count",
                        lambda *a, **k: ({"chatA@c.us": 300, "chatB@c.us": 200}, []))
    monkeypatch.setattr(vb, "whatsapp_store_count", lambda conn: 510)
    monkeypatch.setattr(
        vb, "whatsapp_sample",
        lambda conn, n, seed: [{"id": f"wa{i}", "present": True, "body_len": 20}
                               for i in range(n)])
    # lag (all sources) — newest row 60s ago
    monkeypatch.setattr(vb, "latest_timestamp",
                        lambda conn, source, which: _NOW - timedelta(seconds=60))


def test_run_baseline_all_four_sources_healthy(monkeypatch):
    _patch_baseline_collectors(monkeypatch)
    records = run_baseline(vb.BASELINE_SOURCES, "seed", now=_NOW)
    assert set(records) == set(vb.BASELINE_SOURCES)
    for source, rec in records.items():
        assert rec["collector_failures"] == [], f"{source} had collector failures"
        assert rec["completeness"]["ok"] is True
        assert rec["sample"]["ok"] is True
    # explicit numbers preserved
    assert records["plaud"]["completeness"]["ratio"] == 0.995
    assert records["whatsapp"]["completeness"]["store_count"] == 510
    assert records["whatsapp"]["completeness"]["mailbox_total"] == 500


def test_run_baseline_lag_poll_verdict_per_source(monkeypatch):
    _patch_baseline_collectors(monkeypatch)
    records = run_baseline(vb.BASELINE_SOURCES, "seed", now=_NOW)
    # 60s lag vs 300s/900s polls -> WITHIN; whatsapp webhook -> None (N/A)
    assert records["bluewin"]["lag"]["ingest"]["within_interval"] is True
    assert records["plaud"]["lag"]["ingest"]["within_interval"] is True
    assert records["whatsapp"]["lag"]["ingest"]["within_interval"] is None
    assert records["bluewin"]["lag"]["ingest"]["lag_seconds"] == 60


def test_run_baseline_whatsapp_flags_source_column_not_migrated(monkeypatch):
    _patch_baseline_collectors(monkeypatch)
    records = run_baseline(("whatsapp",), "seed", now=_NOW)
    notes = " ".join(records["whatsapp"]["scope_notes"])
    assert "whatsapp_messages.source column" in notes
    assert "NOT migrated" in notes
    assert "OUT OF SCOPE" in notes  # all-time labelled out of scope


def test_run_baseline_never_raises_on_truth_collector_failure(monkeypatch):
    _patch_baseline_collectors(monkeypatch)

    def boom():
        raise RuntimeError("plaud token expired")
    monkeypatch.setattr(vb, "plaud_truth", boom)

    records = run_baseline(("plaud",), "seed", now=_NOW)  # must NOT raise
    rec = records["plaud"]
    assert any("plaud truth collection failed" in e for e in rec["collector_failures"])
    # report still renders in full
    out = build_baseline_report(records, "abc1234", "seed")
    assert "source=plaud" in out


def test_run_baseline_never_raises_on_db_connect_failure(monkeypatch):
    _patch_baseline_collectors(monkeypatch)

    def no_db():
        raise RuntimeError("DATABASE_URL not set")
    monkeypatch.setattr(vb, "_db_conn", no_db)

    records = run_baseline(vb.BASELINE_SOURCES, "seed", now=_NOW)  # must NOT raise
    for source, rec in records.items():
        assert any("db connection failed" in e for e in rec["collector_failures"])


def test_run_baseline_whatsapp_failed_chats_surfaced(monkeypatch):
    _patch_baseline_collectors(monkeypatch)
    monkeypatch.setattr(
        vb, "whatsapp_truth_count",
        lambda *a, **k: ({"chatA@c.us": 300}, ["chatB@c.us", "chatC@c.us"]))
    records = run_baseline(("whatsapp",), "seed", now=_NOW)
    assert any("2 chat(s) failed" in e for e in records["whatsapp"]["collector_failures"])


# ------------------------------------------------- build_baseline_report shape

def _baseline_records(monkeypatch):
    _patch_baseline_collectors(monkeypatch)
    return run_baseline(vb.BASELINE_SOURCES, "seed", now=_NOW)


def test_baseline_report_has_all_sources_and_summary(monkeypatch):
    out = build_baseline_report(_baseline_records(monkeypatch), "abc1234", "seed")
    for source in vb.BASELINE_SOURCES:
        assert f"source={source}" in out
    assert "SUMMARY (per source):" in out
    assert "read-only measurement" in out


def test_baseline_report_lists_explicit_completeness_numbers(monkeypatch):
    out = build_baseline_report(_baseline_records(monkeypatch), "abc1234", "seed")
    assert "store=510 truth=500" in out          # whatsapp explicit numbers
    assert "gap=" in out                          # gap_count present (AC5)
    assert "lag[ingest]:" in out                  # per-source lag (AC4)
    assert "lag[content]:" in out


def test_baseline_report_renders_collector_failures_loud(monkeypatch):
    records = _baseline_records(monkeypatch)
    records["plaud"]["collector_failures"] = ["plaud truth collection failed: boom"]
    out = build_baseline_report(records, "abc1234", "seed")
    assert "FAIL collector: plaud truth collection failed: boom" in out
