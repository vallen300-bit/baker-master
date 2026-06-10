"""BACKFILL_VERIFY_1: unit tests for the verification harness pure logic.

No network, no DB — counts/sample/verdict logic only (live collectors are
exercised at RUN time against the real mailboxes/store)."""
import hashlib

import pytest

from scripts.verify_backfill import (
    build_verdict,
    compare_counts,
    deterministic_order_key,
    evaluate_attachment_checks,
    evaluate_message_checks,
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


def test_verdict_failures_listed_loud():
    results = _passing_results()
    results["graph"]["messages"] = evaluate_message_checks(
        [{"message_id": "g9", "body_len": 0, "searchable": None}])
    out = build_verdict(results, commit="abc1234")
    assert "FAIL g9: empty body" in out                  # AC4 loud, named failure
    assert "ac_result: FAIL" in out
