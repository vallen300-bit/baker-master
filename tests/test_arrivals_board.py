"""ARRIVALS_BOARD_LIVE_1 tests.

Pure tests cover overlay/render behavior without a DB. The upsert round-trip is
live-PG gated through ``needs_live_pg`` and skips cleanly when no test DB exists.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient

from orchestrator import arrivals_board as ab

NOW = datetime(2026, 7, 8, 10, 0, 0, tzinfo=timezone.utc)
MIGRATION = Path("migrations/20260708a_flight_board_state.sql")


def test_effective_status_overlays_past_due_without_hiding_terminal_states():
    assert ab.effective_status(
        {"status": "ON TIME", "arrives_on": date(2026, 7, 7)},
        today=date(2026, 7, 8),
    ) == "DELAYED"
    assert ab.effective_status(
        {"status": "LANDED", "arrives_on": date(2026, 7, 7)},
        today=date(2026, 7, 8),
    ) == "LANDED"
    assert ab.effective_status({}, today=date(2026, 7, 8)) == "CHECK-IN"
    assert ab.effective_status(
        {"status": "ON TIME", "arrives_on": date(2026, 7, 8)},
        today=date(2026, 7, 8),
    ) == "ON TIME"


def test_migration_shape_has_flight_board_contract():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "-- == migrate:up ==" in sql
    assert "CREATE TABLE IF NOT EXISTS flight_board_state" in sql
    for col in (
        "project_code",
        "status",
        "arrives_on",
        "cockpit_url",
        "updated_by",
        "updated_at",
    ):
        assert col in sql
    for status in ab.STATUSES:
        assert status in sql


def test_render_board_html_uses_template_tokens_and_filters_old_landed():
    rows = [
        {
            "project_number": "BB-AUK-001",
            "desk_owner": "baden-baden-desk",
            "matter_slug": "lilienmatt",
            "status": "FINAL APPROACH",
            "arrives_on": date(2026, 7, 10),
            "airline": "Baden-Baden",
            "destination": "Aukera financing",
            "cockpit_url": "/\\external.example/landing",
            "updated_at": NOW,
        },
        {
            "project_number": "AO-OSK-001",
            "desk_owner": "ao-desk",
            "matter_slug": "ao",
            "status": None,
            "updated_at": None,
        },
        {
            "project_number": "OLD-LND-001",
            "desk_owner": "brisen-desk",
            "matter_slug": "brisen",
            "status": "LANDED",
            "updated_at": NOW - timedelta(days=8),
        },
    ]
    html = ab.render_board_html(rows, now=NOW)
    assert 'data-flap="BB-AUK-001"' in html
    assert "external.example" not in html
    assert 'onclick="location.href=&quot;/cockpit/BB-AUK-001&quot;"' in html
    assert 'onclick="location.href=&quot;/cockpit/AO-OSK-001&quot;"' in html
    assert "blinkgrp" in html
    assert 'data-flap="FINAL APPROACH"' in html
    assert 'data-flap="PENDING"' in html
    assert 'data-flap="CHECK-IN"' in html
    assert "OLD-LND-001" not in html
    assert "__ROWS__" not in html
    assert "__STAMP__" not in html
    assert '<meta http-equiv="refresh" content="120">' in html
    assert 'style="overflow-x:auto"' in html


def test_cockpit_url_rejects_backslashes():
    assert ab._optional_cockpit_url("/flights/BB-AUK-001") == "/flights/BB-AUK-001"
    for url in ("/\\evil.example/path", "/flights\\BB-AUK-001"):
        with pytest.raises(ValueError):
            ab._optional_cockpit_url(url)


def _bootstrap_live_pg(dsn: str) -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS baker_actions (
                    id SERIAL PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    target_task_id TEXT,
                    payload JSONB,
                    trigger_source TEXT,
                    success BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            cur.execute(
                "DELETE FROM flight_board_state WHERE project_code = %s",
                ("TST-ARR-001",),
            )
            cur.execute(
                "DELETE FROM baker_actions WHERE target_task_id = %s",
                ("TST-ARR-001",),
            )


def test_upsert_board_state_validates_and_audits_live_pg(needs_live_pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", needs_live_pg)
    _bootstrap_live_pg(needs_live_pg)

    try:
        try:
            ab.upsert_board_state("TST-ARR-001", {"status": "BOARDING"}, "pytest")
            raise AssertionError("bad status should have raised")
        except ValueError:
            pass

        row = ab.upsert_board_state(
            "TST-ARR-001",
            {
                "status": "ON TIME",
                "arrives_on": "2026-07-10",
                "airline": "Test Air",
                "destination": "Control Tower",
                "cockpit_url": "/flights/TST-ARR-001",
                "page_version": "pytest",
            },
            "pytest",
        )
        assert row["project_code"] == "TST-ARR-001"
        assert row["status"] == "ON TIME"

        with psycopg2.connect(needs_live_pg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                     WHERE table_name = 'flight_board_state'
                     ORDER BY column_name
                    """
                )
                cols = {r[0] for r in cur.fetchall()}
                assert {"project_code", "status", "arrives_on", "updated_by"} <= cols
                cur.execute(
                    """
                    SELECT COUNT(*) FROM baker_actions
                     WHERE target_task_id = %s AND trigger_source = %s
                    """,
                    ("TST-ARR-001", "arrivals_board"),
                )
                assert cur.fetchone()[0] == 1
    finally:
        with psycopg2.connect(needs_live_pg) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM flight_board_state WHERE project_code = %s",
                    ("TST-ARR-001",),
                )
                cur.execute(
                    "DELETE FROM baker_actions WHERE target_task_id = %s",
                    ("TST-ARR-001",),
                )


def _client(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    from outputs import dashboard

    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)
    dashboard.app.dependency_overrides.pop(dashboard.verify_api_key, None)
    return TestClient(dashboard.app)


def test_flight_board_endpoint_requires_key_and_rejects_bad_status(monkeypatch):
    client = _client(monkeypatch)
    no_key = client.post("/api/flight-board/BB-AUK-001", json={"status": "ON TIME"})
    assert no_key.status_code in (401, 403)

    bad = client.post(
        "/api/flight-board/BB-AUK-001",
        headers={"X-Baker-Key": "test-key"},
        json={"status": "BOARDING"},
    )
    assert bad.status_code == 422


def test_arrivals_json_uses_effective_status(monkeypatch):
    monkeypatch.setenv("BAKER_API_KEY", "test-key")
    monkeypatch.setenv("ARRIVALS_BOARD_PIN", "123456")
    from outputs import dashboard

    rows = [
        {
            "project_number": "BB-AUK-001",
            "desk_owner": "baden-baden-desk",
            "matter_slug": "lilienmatt",
            "status": "ON TIME",
            "arrives_on": date(2026, 7, 7),
            "updated_at": NOW,
        }
    ]
    monkeypatch.setattr(ab, "list_board_rows", lambda: rows)
    monkeypatch.setattr(dashboard, "_BAKER_API_KEY", "test-key", raising=False)
    client = TestClient(dashboard.app, base_url="https://testserver")

    no_key = client.get("/api/arrivals.json")
    assert no_key.status_code == 404

    page_no_key = client.get("/arrivals")
    assert page_no_key.status_code == 404

    wrong_pin = client.get("/arrivals?pin=111111")
    assert wrong_pin.status_code == 404

    page = client.get("/arrivals?key=test-key")
    assert page.status_code == 200
    assert 'data-flap="BB-AUK-001"' in page.text

    header_page = client.get("/arrivals", headers={"X-Baker-Key": "test-key"})
    assert header_page.status_code == 200

    pin_page = client.get("/arrivals?pin=123456")
    assert pin_page.status_code == 200
    set_cookie = pin_page.headers.get("set-cookie", "")
    assert "arrivals_board_access" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie

    bare_page_with_cookie = client.get("/arrivals")
    assert bare_page_with_cookie.status_code == 200
    assert 'data-flap="BB-AUK-001"' in bare_page_with_cookie.text

    resp = client.get("/api/arrivals.json?key=test-key")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["rows"][0]["effective_status"] == "DELAYED"

    fresh_client = TestClient(dashboard.app, base_url="https://testserver")
    pin_resp = fresh_client.get("/api/arrivals.json?pin=123456")
    assert pin_resp.status_code == 200
    api_set_cookie = pin_resp.headers.get("set-cookie", "")
    assert "arrivals_board_access" in api_set_cookie
    assert "HttpOnly" in api_set_cookie
    assert "Secure" in api_set_cookie
    assert "SameSite=strict" in api_set_cookie

    cookie_resp = fresh_client.get("/api/arrivals.json")
    assert cookie_resp.status_code == 200
    assert cookie_resp.json()["rows"][0]["effective_status"] == "DELAYED"


# =====================================================================
# ARRIVALS_BOARD_CLICKUP_MILESTONE_SYNC_1 — deriver + anti-flap + sync
# =====================================================================
# TDD seams (brief): (1) pure derive_next_milestone(tasks, today),
# (2) pure sync_should_write(row, now), (3) run_clickup_milestone_sync
# orchestration with the DB + ClickUp seams monkeypatched (no live PG needed).

_UTC = timezone.utc


def _task(name, due_ms, closed=False):
    return {
        "name": name,
        "due_date": due_ms,
        "status": {"status": "complete" if closed else "in progress",
                   "type": "closed" if closed else "open"},
    }


def _ms(y, m, d, hh=12, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=_UTC).timestamp() * 1000)


# --- AC1: derive_next_milestone --------------------------------------
def test_derive_earliest_incomplete_with_due_wins():
    tasks = [
        _task("Later milestone", _ms(2026, 8, 1)),
        _task("Next milestone", _ms(2026, 7, 20)),
        _task("Latest", _ms(2026, 9, 1)),
    ]
    got = ab.derive_next_milestone(tasks, date(2026, 7, 15))
    assert got == {"arrives_on": date(2026, 7, 20), "arrives_label": "Next milestone"}


def test_derive_ignores_closed_and_no_due():
    tasks = [
        _task("Closed earlier", _ms(2026, 7, 10), closed=True),
        _task("No due date", None),
        _task("Real next", _ms(2026, 7, 25)),
    ]
    got = ab.derive_next_milestone(tasks, date(2026, 7, 15))
    assert got == {"arrives_on": date(2026, 7, 25), "arrives_label": "Real next"}


def test_derive_empty_and_all_closed_return_none():
    assert ab.derive_next_milestone([], date(2026, 7, 15)) is None
    assert ab.derive_next_milestone(
        [_task("done", _ms(2026, 7, 20), closed=True), _task("nodue", None)],
        date(2026, 7, 15),
    ) is None


def test_derive_label_truncated_to_128():
    long_name = "X" * 400
    got = ab.derive_next_milestone([_task(long_name, _ms(2026, 7, 20))], date(2026, 7, 15))
    assert len(got["arrives_label"]) == 128


# --- AC10 (R2): ms-epoch is UTC-pinned, no host-local day shift -------
def test_derive_due_date_utc_pinned_no_day_shift():
    # 2026-07-20 23:00 UTC. A host in a negative-offset zone using bare
    # date.fromtimestamp would render 2026-07-20 too, but a positive-offset
    # host (e.g. CET, +2) would shift to 07-21. UTC pinning must yield 07-20
    # regardless of host TZ.
    due_ms = int(datetime(2026, 7, 20, 23, 0, tzinfo=_UTC).timestamp() * 1000)
    got = ab.derive_next_milestone([_task("Late-day milestone", due_ms)], date(2026, 7, 1))
    assert got["arrives_on"] == date(2026, 7, 20)


# --- AC5: sync_should_write anti-flap --------------------------------
def test_sync_should_write_no_row_or_missing_ts():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    assert ab.sync_should_write(None, now) is True
    assert ab.sync_should_write({"updated_by": "desk"}, now) is True  # no updated_at


def test_sync_should_write_machine_last_writer_always_ok():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    row = {"updated_by": ab._SYNC_UPDATED_BY, "updated_at": now - timedelta(minutes=1)}
    assert ab.sync_should_write(row, now) is True


def test_sync_should_write_manual_edit_wins_for_24h():
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    fresh_manual = {"updated_by": "hag-desk", "updated_at": now - timedelta(hours=1)}
    assert ab.sync_should_write(fresh_manual, now) is False
    stale_manual = {"updated_by": "hag-desk", "updated_at": now - timedelta(hours=25)}
    assert ab.sync_should_write(stale_manual, now) is True


# --- orchestration (DB + ClickUp seams monkeypatched) ----------------
class _FakeClient:
    def __init__(self, tasks_by_list):
        self._t = tasks_by_list

    def get_tasks(self, list_id, date_updated_gt=None):
        val = self._t.get(list_id)
        if isinstance(val, Exception):
            raise val
        return val or []


def _install_sync_seams(monkeypatch, rows, tasks_by_list, captured):
    monkeypatch.setattr(ab, "_sync_candidate_rows", lambda: rows)
    monkeypatch.setattr(
        ab, "_audit_sync_summary",
        lambda s: captured.setdefault("summaries", []).append(dict(s)),
    )

    def fake_upsert(code, fields, updated_by):
        captured.setdefault("writes", []).append((code, dict(fields), updated_by))
        return {"project_code": code, **fields, "updated_by": updated_by}

    monkeypatch.setattr(ab, "upsert_board_state", fake_upsert)
    import clickup_client
    monkeypatch.setattr(
        clickup_client.ClickUpClient, "_get_global_instance",
        classmethod(lambda cls: _FakeClient(tasks_by_list)),
    )


def test_run_sync_writes_derived_and_threads_status(monkeypatch):
    # AC9 (R1): status threaded through unchanged; updated_by = sync tag.
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": "ON TIME", "arrives_on": date(2026, 6, 1),
        "arrives_label": "Old", "updated_by": ab._SYNC_UPDATED_BY,
        "updated_at": now - timedelta(days=2),
    }]
    tasks = {"901524194809": [_task("Financing close", _ms(2026, 7, 30))]}
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)

    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["written"] == 1 and summary["checked"] == 1
    (code, fields, by) = captured["writes"][0]
    assert code == "BB-AUK-001"
    assert fields["arrives_on"] == date(2026, 7, 30)
    assert fields["arrives_label"] == "Financing close"
    assert fields["status"] == "ON TIME"     # R1: status preserved verbatim
    assert by == ab._SYNC_UPDATED_BY
    assert captured["summaries"][-1]["written"] == 1


def test_run_sync_default_status_when_no_board_row(monkeypatch):
    # AC9: no existing status -> default CHECK-IN (sync never invents a status).
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": None, "arrives_on": None, "arrives_label": None,
        "updated_by": None, "updated_at": None,
    }]
    tasks = {"901524194809": [_task("Kickoff", _ms(2026, 7, 30))]}
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    ab.run_clickup_milestone_sync(now=now)
    assert captured["writes"][0][1]["status"] == "CHECK-IN"


def test_run_sync_noop_suppressed(monkeypatch):
    # AC6: derived == current -> no upsert, no per-flight write.
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": "ON TIME", "arrives_on": date(2026, 7, 30),
        "arrives_label": "Financing close", "updated_by": ab._SYNC_UPDATED_BY,
        "updated_at": now - timedelta(days=2),
    }]
    tasks = {"901524194809": [_task("Financing close", _ms(2026, 7, 30))]}
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["written"] == 0 and summary["skipped_noop"] == 1
    assert "writes" not in captured


def test_run_sync_manual_hold_blocks_write(monkeypatch):
    # AC5: a desk manual edit < 24h old is never overwritten.
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": "HOLDING", "arrives_on": date(2026, 7, 5),
        "arrives_label": "Desk value", "updated_by": "hag-desk",
        "updated_at": now - timedelta(hours=3),
    }]
    tasks = {"901524194809": [_task("Machine milestone", _ms(2026, 7, 30))]}
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["skipped_manual"] == 1 and summary["written"] == 0
    assert "writes" not in captured


def test_run_sync_no_milestone_leaves_value_untouched(monkeypatch):
    # AC2 fallback: no upcoming milestone -> skip, no write.
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": "ON TIME", "arrives_on": date(2026, 7, 5),
        "arrives_label": "Manual", "updated_by": "hag-desk",
        "updated_at": now - timedelta(days=10),
    }]
    tasks = {"901524194809": []}   # all-empty -> derive returns None
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["skipped_no_milestone"] == 1 and summary["written"] == 0
    assert "writes" not in captured


def test_run_sync_independent_per_flight_on_error(monkeypatch):
    # AC7: one flight's ClickUp error must not abort the tick for the others.
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [
        {"project_code": "BB-AUK-001", "clickup_list_id": "list-bad",
         "status": "ON TIME", "arrives_on": None, "arrives_label": None,
         "updated_by": ab._SYNC_UPDATED_BY, "updated_at": now - timedelta(days=2)},
        {"project_code": "MO-VIE-001", "clickup_list_id": "list-good",
         "status": "ON TIME", "arrives_on": None, "arrives_label": None,
         "updated_by": ab._SYNC_UPDATED_BY, "updated_at": now - timedelta(days=2)},
    ]
    tasks = {
        "list-bad": RuntimeError("clickup 500"),
        "list-good": [_task("Good milestone", _ms(2026, 7, 30))],
    }
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["errors"] == 1
    assert summary["written"] == 1
    assert captured["writes"][0][0] == "MO-VIE-001"   # the healthy flight still wrote


# --- codex #4 (P2): same-day milestones break ties by TIME, not response order
def test_derive_same_day_breaks_tie_by_time():
    early = int(datetime(2026, 7, 20, 8, 0, tzinfo=_UTC).timestamp() * 1000)
    late = int(datetime(2026, 7, 20, 18, 0, tzinfo=_UTC).timestamp() * 1000)
    # feed the LATER task first so a day-granularity/response-order sort would
    # wrongly pick it; the full-timestamp sort must still pick the earlier one.
    tasks = [_task("Late same-day", late), _task("Early same-day", early)]
    got = ab.derive_next_milestone(tasks, date(2026, 7, 1))
    assert got["arrives_label"] == "Early same-day"
    assert got["arrives_on"] == date(2026, 7, 20)


# --- codex #1 (P1): a LANDED/DIVERTED flight is never re-derived ------
def test_run_sync_skips_terminal_landed_flight(monkeypatch):
    # Re-upserting a landed flight would refresh updated_at and defeat the
    # >7-day old-landed hide on the Director-facing board.
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": "LANDED", "arrives_on": date(2026, 7, 1),
        "arrives_label": "Arrived", "updated_by": ab._SYNC_UPDATED_BY,
        "updated_at": now - timedelta(days=8),
    }]
    tasks = {"901524194809": [_task("Some future task", _ms(2026, 8, 1))]}
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["skipped_terminal"] == 1
    assert summary["checked"] == 0 and summary["written"] == 0
    assert "writes" not in captured


# --- CLICKUP_GET_TASKS_ROBUSTNESS_1 (caller side): outage skipped knowingly ---
def test_run_sync_clickup_outage_skipped_knowingly(monkeypatch):
    # F1: get_tasks now RAISES ClickUpUnavailable on a ClickUp outage (vs the old
    # []). The sync must count it as skipped_outage (fail-loud) and NEVER overwrite
    # the board with an outage-derived empty — distinct from a generic error.
    from clickup_client import ClickUpUnavailable
    now = datetime(2026, 7, 15, 12, 0, tzinfo=_UTC)
    rows = [{
        "project_code": "BB-AUK-001", "clickup_list_id": "901524194809",
        "status": "ON TIME", "arrives_on": date(2026, 7, 20),
        "arrives_label": "Existing", "updated_by": ab._SYNC_UPDATED_BY,
        "updated_at": now - timedelta(days=2),
    }]
    tasks = {"901524194809": ClickUpUnavailable("clickup down")}
    captured = {}
    _install_sync_seams(monkeypatch, rows, tasks, captured)
    summary = ab.run_clickup_milestone_sync(now=now)
    assert summary["skipped_outage"] == 1
    assert summary["written"] == 0 and summary["errors"] == 0
    assert "writes" not in captured


# --- lead #11775: 'done'-type completions are terminal, not just 'closed' ------
def test_derive_ignores_done_type_not_just_closed():
    # BB-AUK-001 connector list marks completions status.type "done" ("complete"),
    # not "closed" — excluding only "closed" left them deriving as next milestone.
    done_task = {"name": "Completed B18", "due_date": _ms(2026, 7, 10),
                 "status": {"status": "complete", "type": "done"}}
    tasks = [done_task, _task("Real next", _ms(2026, 7, 25))]
    got = ab.derive_next_milestone(tasks, date(2026, 7, 15))
    assert got == {"arrives_on": date(2026, 7, 25), "arrives_label": "Real next"}
    # a list of ONLY done/closed tasks -> None (board leaves existing value untouched)
    only_finished = [
        done_task,
        {"name": "c", "due_date": _ms(2026, 7, 5), "status": {"type": "closed"}},
    ]
    assert ab.derive_next_milestone(only_finished, date(2026, 7, 15)) is None
