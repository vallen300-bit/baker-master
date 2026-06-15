"""LONG_RUNNING_JOB_OWNERSHIP_1 — cursor-stall sentinel tests.

Mocks DB (via a FakeDAO modelling the atomic alert-window claim) and the bus
(via a capture function). No live creds. Covers AC6 (a)-(g):
  (a) flat-line cursor + RUNNING + past-threshold -> alarm
  (b) advancing cursor -> no alarm
  (c) DONE (cursor>=total / state=DONE) -> no alarm
  (d) within cold-start grace -> no alarm
  (e) re-alert de-dupe holds across runs (same window)
  (f) two concurrent runs claim same window -> exactly ONE bus-post
  (g) in-process restart re-applies cold-start grace
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from triggers import cursor_stall_sentinel as css

UTC = timezone.utc


# --------------------------------------------------------------------------
# FakeDAO — in-memory model of the real DB contract, including the ATOMIC
# alert-window claim (INSERT ... ON CONFLICT DO UPDATE ... WHERE window IS
# DISTINCT FROM ... RETURNING). A claim wins only if the stored window differs.
# --------------------------------------------------------------------------
class FakeDAO:
    def __init__(self):
        # job_id -> {"cursor","updated_at","total","state","kind"}
        self.sources: dict[str, dict] = {}
        # job_id -> (observed_cursor, observed_at)
        self.observations: dict[str, tuple] = {}
        # job_id -> last_alert_window_start
        self.windows: dict[str, str] = {}
        self.self_beats: list[tuple] = []

    # --- source resolution ---
    def read_progress(self, table, cursor_col, updated_col, key_col, key_val,
                      total_col):
        s = self.sources.get(key_val)
        if s is None:
            return None
        return (s["cursor"], s["updated_at"], s.get("total"))

    def read_heartbeat(self, job_id):
        s = self.sources.get(job_id)
        if s is None:
            return None
        return (s["cursor"], s.get("state", "RUNNING"), s["updated_at"])

    # --- observation persistence ---
    def get_prior_observation(self, job_id):
        return self.observations.get(job_id)

    def record_observation(self, job_id, cursor, observed_at):
        self.observations[job_id] = (str(cursor), observed_at)

    # --- ATOMIC claim (models the real ON CONFLICT WHERE DISTINCT RETURNING) ---
    def claim_alert_window(self, job_id, cursor, observed_at, window) -> bool:
        self.observations[job_id] = (str(cursor), observed_at)
        if self.windows.get(job_id) == window:
            return False  # same window already claimed -> lose
        self.windows[job_id] = window
        return True

    def beat_self(self, job_id, ts):
        self.self_beats.append((job_id, ts))


def _entry(job_id="graph_inbox_backfill", threshold=6, kind="progress_table",
           key_val="graph:Inbox"):
    if kind == "progress_table":
        src = {
            "kind": "progress_table",
            "table": "email_backfill_progress",
            "cursor_col": "done_count",
            "updated_col": "updated_at",
            "key_col": "source",
            "key_val": key_val,
            "total_col": "total_estimate",
        }
    else:
        src = {"kind": "heartbeat", "job_id": job_id}
    return {
        "job_id": job_id,
        "description": "test",
        "trigger_reason": "detached",
        "stall_threshold_hours": threshold,
        "responsible": "b1",
        "accountable": "lead",
        "consulted": ["aid"],
        "informed": ["director"],
        "cursor_source": src,
    }


@pytest.fixture(autouse=True)
def _fresh_anchor():
    # Push the cold-start anchor far into the past so grace is NOT active by
    # default (individual tests re-stamp it when they need grace).
    css._MODULE_LOAD_TIME = datetime(2000, 1, 1, tzinfo=UTC)
    yield


def _posts_collector():
    posts = []
    def _fn(recipient, body, topic):
        posts.append({"recipient": recipient, "body": body, "topic": topic})
    return posts, _fn


# ---------------------------- (a) flat-line alarm --------------------------
def test_flatline_running_past_threshold_alarms():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": now - timedelta(hours=7),  # > 6h threshold
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert "graph_inbox_backfill" in summary["alarmed"]
    assert "graph_inbox_backfill" in summary["posted"]
    # posts to accountable (lead) — deduped (accountable == lead)
    recips = {p["recipient"] for p in posts}
    assert "lead" in recips
    assert any("graph_inbox_backfill" in p["body"] for p in posts)
    assert all(p["topic"] == "alert/job-stalled/graph_inbox_backfill" for p in posts)


# ---------------------------- (b) advancing -> no alarm -------------------
def test_advancing_cursor_no_alarm():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    # updated_at recent -> not stale
    dao.sources["graph:Inbox"] = {
        "cursor": 500, "total": 1000,
        "updated_at": now - timedelta(minutes=5),
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert summary["alarmed"] == []
    assert posts == []


def test_stale_but_cursor_advanced_vs_prior_no_alarm():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 600, "total": 1000,
        "updated_at": now - timedelta(hours=8),
    }
    dao.observations["graph_inbox_backfill"] = ("500", now - timedelta(hours=1))
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert summary["alarmed"] == []
    assert posts == []


# ---------------------------- (c) DONE -> no alarm ------------------------
def test_done_progress_table_no_alarm():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 1000, "total": 1000,  # cursor >= total -> DONE
        "updated_at": now - timedelta(hours=48),
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert summary["alarmed"] == []
    assert posts == []


def test_done_heartbeat_state_no_alarm():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["hb_job"] = {
        "cursor": "x", "state": "DONE",
        "updated_at": now - timedelta(hours=48),
    }
    posts, fn = _posts_collector()
    e = _entry(job_id="hb_job", kind="heartbeat")
    summary = css.check_cursor_stalls(
        register=[e], dao=dao, now=now, bus_post_fn=fn)
    assert summary["alarmed"] == []
    assert posts == []


def test_heartbeat_running_stale_alarms():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["hb_job"] = {
        "cursor": "uid-42", "state": "RUNNING",
        "updated_at": now - timedelta(hours=9),
    }
    posts, fn = _posts_collector()
    e = _entry(job_id="hb_job", kind="heartbeat")
    summary = css.check_cursor_stalls(
        register=[e], dao=dao, now=now, bus_post_fn=fn)
    assert "hb_job" in summary["alarmed"]
    assert len(posts) >= 1


# ---------------------------- (d) cold-start grace ------------------------
def test_within_cold_start_grace_no_alarm():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    css._MODULE_LOAD_TIME = now - timedelta(seconds=60)  # inside 900s grace
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": now - timedelta(hours=7),
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert summary["skipped_cold_start"] is True
    assert posts == []


# ---------------------------- (e) re-alert de-dupe ------------------------
def test_re_alert_dedupe_same_window():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": now - timedelta(hours=7),
    }
    posts, fn = _posts_collector()
    # run 1 -> posts; run 2 (same stall/window) -> no new post
    css.check_cursor_stalls(register=[_entry()], dao=dao,
                            now=now, bus_post_fn=fn)
    n_after_first = len(posts)
    css.check_cursor_stalls(register=[_entry()], dao=dao,
                            now=now + timedelta(minutes=30), bus_post_fn=fn)
    assert n_after_first >= 1
    assert len(posts) == n_after_first  # no additional posts


def test_new_episode_after_resume_realerts():
    base = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": base - timedelta(hours=7),
    }
    posts, fn = _posts_collector()
    # run 1: flat-line at 270 -> alarm + post (episode 1, window = updated_at1)
    css.check_cursor_stalls(register=[_entry()], dao=dao,
                            now=base, bus_post_fn=fn)
    first = len(posts)
    assert first >= 1

    # run 2: job RESUMED — cursor advanced to 400, fresh updated_at -> NOT stale,
    # sentinel records new baseline (400), no post.
    t2 = base + timedelta(hours=10)
    dao.sources["graph:Inbox"] = {
        "cursor": 400, "total": 1000,
        "updated_at": t2 - timedelta(minutes=2),
    }
    css.check_cursor_stalls(register=[_entry()], dao=dao,
                            now=t2, bus_post_fn=fn)
    assert len(posts) == first  # advancement -> no new post

    # run 3: re-stalled at 400 with a NEW old updated_at (new episode/window) ->
    # baseline now 400, flat-line confirmed -> re-alert.
    t3 = t2 + timedelta(hours=10)
    dao.sources["graph:Inbox"] = {
        "cursor": 400, "total": 1000,
        "updated_at": t3 - timedelta(hours=7),
    }
    css.check_cursor_stalls(register=[_entry()], dao=dao,
                            now=t3, bus_post_fn=fn)
    assert len(posts) > first


# ---------------------------- (f) atomic claim ---------------------------
def test_two_concurrent_runs_exactly_one_post():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()  # shared DAO == shared DB row
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": now - timedelta(hours=7),
    }
    posts, fn = _posts_collector()
    # Two runs against the SAME dao + SAME window. Only one wins the claim.
    css.check_cursor_stalls(register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    css.check_cursor_stalls(register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    posts_for_job = [p for p in posts if "graph_inbox_backfill" in p["body"]
                     and p["recipient"] == "lead"]
    assert len(posts_for_job) == 1


def test_claim_alert_window_contract():
    dao = FakeDAO()
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    assert dao.claim_alert_window("j", 1, now, "W1") is True
    assert dao.claim_alert_window("j", 1, now, "W1") is False  # same window
    assert dao.claim_alert_window("j", 1, now, "W2") is True   # new window


# ---------------------------- (g) restart re-grace -----------------------
def test_restart_reapplies_cold_start_grace():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    # anchor is far in the past (fixture) -> grace inactive
    css.reset_cold_start_anchor()  # re-stamps to ~now
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": now - timedelta(hours=7),
    }
    posts, fn = _posts_collector()
    # use real wall-clock now (anchor just stamped) -> grace active
    summary = css.check_cursor_stalls(register=[_entry()], dao=dao,
                                      bus_post_fn=fn)
    assert summary["skipped_cold_start"] is True
    assert posts == []


# --------- (S2 codex G3) heartbeat state is completion source of truth ----
def test_progress_table_null_total_with_heartbeat_done_no_alarm():
    # graph total_estimate can be NULL (folder-total read fail). cursor>=total is
    # then unreliable, but the backfill wrote state=DONE -> never alarm.
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": None,
        "updated_at": now - timedelta(hours=48),
    }
    dao.sources["graph_inbox_backfill"] = {  # heartbeat row
        "cursor": "270", "state": "DONE",
        "updated_at": now - timedelta(hours=48),
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert summary["alarmed"] == []
    assert posts == []


def test_progress_table_cursor_below_total_with_heartbeat_done_no_alarm():
    # bluewin done_count is an inserted-delta (< processed) so cursor<total even
    # when finished. heartbeat state=DONE must suppress the false alarm.
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["bluewin:INBOX"] = {
        "cursor": 900, "total": 33686,  # delta < total, but job is done
        "updated_at": now - timedelta(hours=48),
    }
    dao.sources["bluewin_inbox_backfill"] = {
        "cursor": "900", "state": "DONE",
        "updated_at": now - timedelta(hours=48),
    }
    posts, fn = _posts_collector()
    e = _entry(job_id="bluewin_inbox_backfill", key_val="bluewin:INBOX")
    summary = css.check_cursor_stalls(
        register=[e], dao=dao, now=now, bus_post_fn=fn)
    assert summary["alarmed"] == []
    assert posts == []


def test_progress_table_heartbeat_running_still_alarms_on_stall():
    # heartbeat says RUNNING but the progress cursor has flat-lined past
    # threshold -> this IS the stall we must catch.
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": 1000,
        "updated_at": now - timedelta(hours=8),
    }
    dao.sources["graph_inbox_backfill"] = {
        "cursor": "270", "state": "RUNNING",
        "updated_at": now - timedelta(hours=8),
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert "graph_inbox_backfill" in summary["alarmed"]
    assert len(posts) >= 1


def test_progress_table_null_total_no_heartbeat_falls_back_and_alarms():
    # No heartbeat row + NULL total + stale flat-line: cannot prove completion,
    # so the fallback treats it as RUNNING and alarms (correct — unknown state).
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 270, "total": None,
        "updated_at": now - timedelta(hours=9),
    }
    posts, fn = _posts_collector()
    summary = css.check_cursor_stalls(
        register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert "graph_inbox_backfill" in summary["alarmed"]


# ---------------------------- self-heartbeat -----------------------------
def test_sentinel_emits_self_heartbeat():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    dao = FakeDAO()
    dao.sources["graph:Inbox"] = {
        "cursor": 500, "total": 1000,
        "updated_at": now - timedelta(minutes=2),
    }
    _, fn = _posts_collector()
    css.check_cursor_stalls(register=[_entry()], dao=dao, now=now, bus_post_fn=fn)
    assert any(b[0] == "cursor_stall_sentinel" for b in dao.self_beats)
