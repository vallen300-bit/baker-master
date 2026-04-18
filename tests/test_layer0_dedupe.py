"""Tests for kbl.layer0_dedupe — S5 content-hash + S6 review-queue writers.

Unit-level tests mock psycopg2; an optional live-DB round-trip exists
behind TEST_DATABASE_URL so the SQL is exercised end-to-end when PG is
available (mirrors tests/test_migrations.py pattern).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kbl import layer0_dedupe
from kbl.layer0_dedupe import (
    _SIG_PATTERNS,
    cleanup_expired,
    content_hash,
    has_seen_recent,
    insert_hash,
    kbl_layer0_review_insert,
    normalize_for_hash,
)

psycopg2 = pytest.importorskip(
    "psycopg2", reason="psycopg2 required — live-PG tests skipped without it"
)

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
requires_db = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL unset — skipping live-PG round trip"
)


# ----------------------------- normalize_for_hash -----------------------------


def test_normalize_empty_returns_empty() -> None:
    assert normalize_for_hash("") == ""
    assert normalize_for_hash(None) == ""  # type: ignore[arg-type]


def test_normalize_deterministic_same_input() -> None:
    """Same input → same output. Non-negotiable for hash store stability."""
    text = "Hagenauer closed today. See thread."
    assert normalize_for_hash(text) == normalize_for_hash(text)


def test_normalize_drops_quoted_reply_lines() -> None:
    original = (
        "Thanks Dimitry.\n"
        "> On Wed, Apr 17, 2026, Dimitry wrote:\n"
        "> > Please review the draft.\n"
        "Regards"
    )
    out = normalize_for_hash(original)
    assert "please review" not in out
    assert "on wed" not in out
    assert "thanks dimitry" in out


def test_normalize_truncates_at_signature() -> None:
    """Best regards / sign-offs stripped so two copies with different
    signatures still hash identical."""
    body_a = "Deal closes Friday.\n\nBest regards,\nDimitry"
    body_b = "Deal closes Friday.\n\nBest regards,\nAO"
    assert normalize_for_hash(body_a) == normalize_for_hash(body_b)


def test_normalize_truncates_at_rfc_sig_delimiter() -> None:
    body = "Deal closes Friday.\n-- \nDimitry Vallen\nBrisen Group"
    normalized = normalize_for_hash(body)
    assert "dimitry vallen" not in normalized
    assert "brisen group" not in normalized
    assert "deal closes friday" in normalized


def test_normalize_collapses_whitespace() -> None:
    body = "line one\n\n\n   line two\t\t\n\nline three"
    normalized = normalize_for_hash(body)
    # Single-space-separated, no runs.
    assert "  " not in normalized
    assert "\n" not in normalized
    assert "\t" not in normalized
    assert normalized == "line one line two line three"


def test_normalize_lowercases() -> None:
    assert normalize_for_hash("HELLO") == "hello"
    assert normalize_for_hash("CamelCase Body") == "camelcase body"


def test_sig_patterns_regex_compiles() -> None:
    """Guard against accidental breakage of the module-level pattern."""
    assert _SIG_PATTERNS.search("\nBest regards,\n") is not None
    assert _SIG_PATTERNS.search("\n-- \n") is not None


# ----------------------------- content_hash -----------------------------


def test_content_hash_is_sha256_hex() -> None:
    h = content_hash("hello world")
    assert len(h) == 64  # sha256 hex
    assert all(c in "0123456789abcdef" for c in h)


def test_content_hash_stable_across_sig_variants() -> None:
    """Two copies with different sig blocks must hash identical."""
    a = "Please confirm by EOD.\nBest regards,\nDimitry"
    b = "Please confirm by EOD.\n-- \nD. Vallen"
    assert content_hash(a) == content_hash(b)


def test_content_hash_differs_for_different_content() -> None:
    assert content_hash("alpha") != content_hash("beta")


# ----------------------------- has_seen_recent (mock) -----------------------------


def _mock_conn(fetch_result=None, raise_exc: Exception | None = None) -> MagicMock:
    cursor = MagicMock()
    if raise_exc is not None:
        cursor.execute.side_effect = raise_exc
    cursor.fetchone.return_value = fetch_result
    cursor_ctx = MagicMock()
    cursor_ctx.__enter__.return_value = cursor
    cursor_ctx.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cursor_ctx
    return conn


def test_has_seen_recent_true_when_row_present() -> None:
    conn = _mock_conn(fetch_result=(1,))
    assert has_seen_recent(conn, "abc") is True


def test_has_seen_recent_false_when_empty() -> None:
    conn = _mock_conn(fetch_result=None)
    assert has_seen_recent(conn, "abc") is False


def test_has_seen_recent_false_for_empty_hash() -> None:
    """No lookup issued when hash is empty — saves a DB round-trip."""
    conn = _mock_conn(fetch_result=None)
    assert has_seen_recent(conn, "") is False
    conn.cursor.assert_not_called()


def test_has_seen_recent_rollback_on_error() -> None:
    conn = _mock_conn(raise_exc=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        has_seen_recent(conn, "abc")
    conn.rollback.assert_called_once()


def test_has_seen_recent_query_uses_ttl_filter() -> None:
    """Must filter on ``ttl_expires_at > now()`` so expired rows don't hit."""
    conn = _mock_conn(fetch_result=None)
    has_seen_recent(conn, "abc")
    cur = conn.cursor.return_value.__enter__.return_value
    sql, params = cur.execute.call_args.args
    assert "ttl_expires_at > now()" in sql
    assert params == ("abc",)


# ----------------------------- insert_hash (mock) -----------------------------


def test_insert_hash_uses_on_conflict_do_nothing() -> None:
    conn = _mock_conn()
    insert_hash(conn, "abc", source_signal_id=42, source_kind="email")
    cur = conn.cursor.return_value.__enter__.return_value
    sql, _ = cur.execute.call_args.args
    assert "ON CONFLICT (content_hash) DO NOTHING" in sql


def test_insert_hash_passes_ttl_as_interval_arg() -> None:
    """TTL expressed as parameter, not SQL string interpolation."""
    conn = _mock_conn()
    insert_hash(conn, "abc", source_signal_id=1, source_kind="email", ttl_hours=24)
    cur = conn.cursor.return_value.__enter__.return_value
    _, params = cur.execute.call_args.args
    assert "24" in params
    # source_signal_id + source_kind also passed
    assert 1 in params
    assert "email" in params


def test_insert_hash_rejects_empty_hash() -> None:
    with pytest.raises(ValueError, match="content_hash_value"):
        insert_hash(_mock_conn(), "", source_signal_id=1, source_kind="email")


def test_insert_hash_rejects_empty_source_kind() -> None:
    with pytest.raises(ValueError, match="source_kind"):
        insert_hash(_mock_conn(), "abc", source_signal_id=1, source_kind="")


def test_insert_hash_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="ttl_hours"):
        insert_hash(
            _mock_conn(), "abc", source_signal_id=1, source_kind="email", ttl_hours=0
        )


def test_insert_hash_rollback_on_error() -> None:
    conn = _mock_conn(raise_exc=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        insert_hash(conn, "abc", source_signal_id=1, source_kind="email")
    conn.rollback.assert_called_once()


# ----------------------------- cleanup_expired (mock) -----------------------------


def test_cleanup_expired_returns_rowcount() -> None:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 7
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    assert cleanup_expired(conn) == 7


def test_cleanup_expired_issues_delete_query() -> None:
    conn = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = 0
    conn.cursor.return_value.__enter__.return_value = cursor
    conn.cursor.return_value.__exit__.return_value = False
    cleanup_expired(conn)
    sql = cursor.execute.call_args.args[0]
    assert "DELETE FROM kbl_layer0_hash_seen" in sql
    assert "ttl_expires_at < now()" in sql


# ----------------------------- review-queue writer -----------------------------


def test_review_insert_uses_pr5_column_names() -> None:
    """N2 reconciliation: PR #5 canonical names, NOT B3 draft names."""
    conn = _mock_conn()
    kbl_layer0_review_insert(
        conn,
        signal_id=123,
        dropped_by_rule="email_newsletter_domain",
        signal_excerpt="Hello world",
        source_kind="email",
    )
    cur = conn.cursor.return_value.__enter__.return_value
    sql, params = cur.execute.call_args.args
    assert "kbl_layer0_review" in sql
    # PR #5 column names — explicit anti-regression.
    assert "dropped_by_rule" in sql
    assert "signal_excerpt" in sql
    assert "source_kind" in sql
    # B3-draft names must NOT appear.
    assert "rule_name" not in sql
    assert "excerpt" not in sql.split("signal_excerpt")[0]
    assert params == (123, "email_newsletter_domain", "Hello world", "email")


def test_review_insert_truncates_excerpt_to_500() -> None:
    long_body = "x" * 1200
    conn = _mock_conn()
    kbl_layer0_review_insert(
        conn,
        signal_id=1,
        dropped_by_rule="r",
        signal_excerpt=long_body,
        source_kind="email",
    )
    cur = conn.cursor.return_value.__enter__.return_value
    _, params = cur.execute.call_args.args
    assert len(params[2]) == 500


def test_review_insert_rejects_empty_rule_name() -> None:
    with pytest.raises(ValueError, match="dropped_by_rule"):
        kbl_layer0_review_insert(
            _mock_conn(),
            signal_id=1,
            dropped_by_rule="",
            signal_excerpt="x",
            source_kind="email",
        )


# ============================== live-PG round trip ==============================
# Exercises the SQL against a throwaway DB when TEST_DATABASE_URL is set.


@requires_db
def test_hash_store_round_trip_against_live_pg() -> None:
    """insert_hash → has_seen_recent → (advance clock via manual TTL) →
    cleanup_expired. Tables created via the loop-infrastructure migration."""
    import re as _re

    path = MIGRATIONS_DIR / "20260418_loop_infrastructure.sql"
    sql = path.read_text(encoding="utf-8")
    up = sql.split("-- == migrate:up ==", 1)[1].split("-- == migrate:down ==", 1)[0]
    down_commented = sql.split("-- == migrate:down ==", 1)[1]
    down = "\n".join(
        line.replace("-- ", "", 1).replace("--", "", 1)
        if line.lstrip().startswith("--")
        else line
        for line in down_commented.splitlines()
    )

    conn = psycopg2.connect(TEST_DB_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(down)  # defensive cleanup
            conn.commit()
            cur.execute(up)
            conn.commit()

            h = content_hash("hello world from live pg")

            # Not seen initially
            assert has_seen_recent(conn, h) is False

            insert_hash(conn, h, source_signal_id=1, source_kind="email")
            conn.commit()

            assert has_seen_recent(conn, h) is True

            # Manually expire the row: set ttl_expires_at to the past.
            cur.execute(
                "UPDATE kbl_layer0_hash_seen SET ttl_expires_at = now() - INTERVAL '1 hour' "
                "WHERE content_hash = %s",
                (h,),
            )
            conn.commit()
            assert has_seen_recent(conn, h) is False

            purged = cleanup_expired(conn)
            conn.commit()
            assert purged >= 1

            # Teardown
            cur.execute(down)
            conn.commit()
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute(down)
                conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
