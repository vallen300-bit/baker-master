"""Fixture tests for kbl.correlation (CORRELATION_ID_PRIMITIVE_1).

Pure-string round-trip + parser tests need no DB/network. The read-only
resolver is verified against a stubbed get_conn (no live DB), confirming the
row→dict map, the None paths, rollback-on-error, the LIMIT 1, and that the SQL
is read-only.
"""

from __future__ import annotations

import contextlib

import kbl.correlation as corr


# --- AC1: corr_id mint ----------------------------------------------------


def test_corr_id_mints_token():
    assert corr.corr_id(123) == "sig-123"
    # accepts int-coercible input, strips nothing else
    assert corr.corr_id(0) == "sig-0"


# --- AC2: parse_corr_id ---------------------------------------------------


def test_parse_corr_id_from_topic_and_body():
    assert corr.parse_corr_id("checkin/baden-baden-desk/sig-123") == 123
    assert corr.parse_corr_id("checkin-reply/x/sig-7") == 7
    assert corr.parse_corr_id("no-token") is None
    assert corr.parse_corr_id("sig-abc") is None
    assert corr.parse_corr_id("") is None
    assert corr.parse_corr_id(None) is None  # type: ignore[arg-type]


# --- AC3: topic builders --------------------------------------------------


def test_checkin_topic_builders():
    assert corr.checkin_topic("ao-desk", 9) == "checkin/ao-desk/sig-9"
    assert corr.checkin_reply_topic("ao-desk", 9) == "checkin-reply/ao-desk/sig-9"


# --- AC4: parse_checkin_verdict happy path --------------------------------


def test_parse_checkin_verdict_valid():
    body = (
        "CHECK_IN_VERDICT v1 sig=42 outcome=VALID by=baden-baden-desk\n"
        "free prose below the verdict line"
    )
    assert corr.parse_checkin_verdict(body) == {
        "sig": 42,
        "outcome": "VALID",
        "by": "baden-baden-desk",
    }


# --- AC5: parse_checkin_verdict rejects + never raises --------------------


def test_parse_checkin_verdict_rejects_and_never_raises():
    cases = [
        "CHECK_IN_VERDICT v2 sig=42 outcome=VALID by=x",  # wrong version
        "CHECK_IN_VERDICT v1 outcome=VALID by=x",  # missing sig
        "CHECK_IN_VERDICT v1 sig=abc outcome=VALID by=x",  # non-int sig
        "CHECK_IN_VERDICT v1 sig=42 outcome=BOGUS by=x",  # outcome not in enum
        "CHECK_IN_VERDICT v1 sig=42 outcome=VALID",  # missing by
        "",  # empty
        None,  # None
        "totally unrelated line",  # no prefix
    ]
    for c in cases:
        assert corr.parse_checkin_verdict(c) is None  # type: ignore[arg-type]


def test_parse_checkin_verdict_strictness_regressions():
    """F1 bounce (codex-arch #4642): the old prefix+findall parser accepted
    these. The anchored, order-strict fullmatch parser must reject them all."""
    cases = [
        # v10 must NOT match the v1 prefix (future-protocol misread).
        "CHECK_IN_VERDICT v10 sig=42 outcome=VALID by=desk",
        # leading junk token between the version and sig=.
        "CHECK_IN_VERDICT v1 garbage sig=42 outcome=VALID by=desk",
        # trailing extra token after a fully-valid line.
        "CHECK_IN_VERDICT v1 sig=42 outcome=VALID by=desk extra",
        # duplicate outcome= (last-wins could flip BOGUS -> VALID).
        "CHECK_IN_VERDICT v1 sig=42 outcome=BOGUS outcome=VALID by=desk",
        "CHECK_IN_VERDICT v1 sig=42 outcome=VALID outcome=VALID by=desk",
        # wrong field order (order-strict).
        "CHECK_IN_VERDICT v1 outcome=VALID sig=42 by=desk",
        "CHECK_IN_VERDICT v1 sig=42 by=desk outcome=VALID",
        # extra whitespace between fields (single-space contract).
        "CHECK_IN_VERDICT v1  sig=42 outcome=VALID by=desk",
        # leading junk before the marker.
        "noise CHECK_IN_VERDICT v1 sig=42 outcome=VALID by=desk",
        # whitespace-only body must not raise (IndexError guard).
        "   ",
        "\n\n",
    ]
    for c in cases:
        assert corr.parse_checkin_verdict(c) is None


def test_parse_checkin_verdict_accepts_every_enum_outcome():
    for outcome in (
        "VALID",
        "FAKE",
        "DUPLICATE",
        "WRONG_TERMINAL",
        "NEEDS_LUGGAGE",
        "CHECK_IN_MISSED",
    ):
        body = f"CHECK_IN_VERDICT v1 sig=1 outcome={outcome} by=desk"
        assert corr.parse_checkin_verdict(body) == {
            "sig": 1,
            "outcome": outcome,
            "by": "desk",
        }


# --- AC6: read-only resolver (stubbed get_conn, no live DB) ----------------


class _FakeCursor:
    def __init__(self, row, raise_on_execute=False):
        self._row = row
        self._raise = raise_on_execute
        self.executed_sql = None
        self.executed_params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed_sql = sql
        self.executed_params = params
        if self._raise:
            raise RuntimeError("boom on execute")

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row, raise_on_execute=False):
        self.cur = _FakeCursor(row, raise_on_execute)
        self.rolled_back = False

    def cursor(self):
        return self.cur

    def rollback(self):
        self.rolled_back = True


def _make_get_conn(conn):
    @contextlib.contextmanager
    def _gc():
        yield conn

    return _gc


def test_resolve_signal_returns_dict_for_row(monkeypatch):
    conn = _FakeConn((42, "pending", "oskolkov"))
    monkeypatch.setattr(corr, "get_conn", _make_get_conn(conn))
    out = corr.resolve_signal(42)
    assert out == {"id": 42, "status": "pending", "matter_slug": "oskolkov"}
    assert "LIMIT 1" in conn.cur.executed_sql
    assert conn.cur.executed_params == (42,)


def test_resolve_signal_none_when_no_row(monkeypatch):
    conn = _FakeConn(None)
    monkeypatch.setattr(corr, "get_conn", _make_get_conn(conn))
    assert corr.resolve_signal(99) is None


def test_resolve_signal_none_and_rollback_on_execute_error(monkeypatch):
    conn = _FakeConn(None, raise_on_execute=True)
    monkeypatch.setattr(corr, "get_conn", _make_get_conn(conn))
    assert corr.resolve_signal(7) is None
    assert conn.rolled_back is True


def test_resolve_signal_none_when_get_conn_raises(monkeypatch):
    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(corr, "get_conn", _boom)
    assert corr.resolve_signal(1) is None


def test_resolve_signal_sql_is_read_only(monkeypatch):
    conn = _FakeConn((1, "pending", "x"))
    monkeypatch.setattr(corr, "get_conn", _make_get_conn(conn))
    corr.resolve_signal(1)
    sql = conn.cur.executed_sql.upper()
    for forbidden in ("INSERT", "UPDATE", "DELETE"):
        assert forbidden not in sql
