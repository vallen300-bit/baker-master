"""Tests for kbl.loop — Learning Loop read-side helpers (LOOP-HELPERS-1).

Covers the three public functions: load_hot_md, load_recent_feedback,
render_ledger, plus the LoopReadError exception class. Uses psycopg2 mocks
for the feedback_ledger tests so CI can run without a live PG instance;
an optional live-DB round-trip guard is included behind TEST_DATABASE_URL.
"""
from __future__ import annotations

import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kbl import loop
from kbl.loop import LoopReadError, load_hot_md, load_recent_feedback, render_ledger

FIXTURES = Path(__file__).parent / "fixtures"
HOT_MD_SAMPLE = FIXTURES / "hot_md_sample.md"
HOT_MD_EMPTY = FIXTURES / "hot_md_empty.md"


# ------------------------------ load_hot_md ------------------------------


def test_load_hot_md_happy_path_explicit() -> None:
    content = load_hot_md(HOT_MD_SAMPLE)
    assert isinstance(content, str)
    assert content.startswith("# Hot")
    # Spot-check a few bullets so fixture drift is caught — not content-brittle.
    assert "Hagenauer" in content
    assert "MORV" in content


def test_load_hot_md_empty_file_returns_empty_string() -> None:
    """Empty file is a valid state — contents are '', not None."""
    content = load_hot_md(HOT_MD_EMPTY)
    assert content == ""


def test_load_hot_md_missing_file_returns_none(tmp_path: Path) -> None:
    """Missing file is zero-Gold per CHANDA Inv 1 — NOT an error."""
    missing = tmp_path / "never-existed.md"
    assert load_hot_md(missing) is None


def test_load_hot_md_vault_env_happy_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    hot = wiki / "hot.md"
    hot.write_text("- bullet", encoding="utf-8")
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    assert load_hot_md() == "- bullet"


def test_load_hot_md_vault_env_unset_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BAKER_VAULT_PATH", raising=False)
    with pytest.raises(LoopReadError, match="BAKER_VAULT_PATH"):
        load_hot_md()


def test_load_hot_md_vault_env_missing_file_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Vault exists but wiki/hot.md absent — zero-Gold, returns None."""
    monkeypatch.setenv("BAKER_VAULT_PATH", str(tmp_path))
    assert load_hot_md() is None


@pytest.mark.skipif(
    os.geteuid() == 0, reason="chmod-based permission test needs non-root"
)
def test_load_hot_md_permission_error_raises(tmp_path: Path) -> None:
    blocked = tmp_path / "hot.md"
    blocked.write_text("x", encoding="utf-8")
    blocked.chmod(0)  # remove all permissions
    try:
        with pytest.raises(LoopReadError, match="failed to read"):
            load_hot_md(blocked)
    finally:
        # Restore perms so tmp_path cleanup succeeds.
        blocked.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_load_hot_md_expands_tilde(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """~ in explicit path must expand so Director-written config works."""
    monkeypatch.setenv("HOME", str(tmp_path))
    hot = tmp_path / "hot.md"
    hot.write_text("tilde", encoding="utf-8")
    assert load_hot_md("~/hot.md") == "tilde"


# ------------------------------ load_recent_feedback ------------------------------


def _mock_conn(rows: list[tuple] | None, raise_exc: Exception | None = None) -> MagicMock:
    """Build a psycopg2-shaped mock connection.

    conn.cursor() must return a context manager yielding a cursor whose
    .execute + .fetchall either return ``rows`` or raise ``raise_exc``.
    """
    cursor = MagicMock()
    if raise_exc is not None:
        cursor.execute.side_effect = raise_exc
    cursor.fetchall.return_value = rows or []

    cursor_ctx = MagicMock()
    cursor_ctx.__enter__.return_value = cursor
    cursor_ctx.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cursor_ctx
    return conn


_SAMPLE_ROW = (
    42,                                              # id
    datetime(2026, 4, 17, 14, 3, tzinfo=timezone.utc),  # created_at
    "promote",                                       # action_type
    "hagenauer",                                     # target_matter
    "wiki/matters/hagenauer/cards/legal.md",         # target_path
    777,                                             # signal_id
    {"reason": "new Gewährleistung motion filed"},   # payload
    "Director: escalate to counsel",                 # director_note
)


def test_load_recent_feedback_happy_path() -> None:
    conn = _mock_conn([_SAMPLE_ROW])
    result = load_recent_feedback(conn, limit=5)
    assert len(result) == 1
    row = result[0]
    assert row["id"] == 42
    assert row["action_type"] == "promote"
    assert row["target_matter"] == "hagenauer"
    assert row["director_note"] == "Director: escalate to counsel"
    assert row["payload"] == {"reason": "new Gewährleistung motion filed"}
    # Verify the query went out with the expected limit.
    cursor = conn.cursor.return_value.__enter__.return_value
    args, _ = cursor.execute.call_args
    assert "LIMIT %s" in args[0]
    assert "ORDER BY created_at DESC" in args[0]
    assert args[1] == (5,)


def test_load_recent_feedback_empty_table_returns_empty_list() -> None:
    """Empty table is zero-Gold per CHANDA Inv 1 — NOT an error."""
    conn = _mock_conn([])
    assert load_recent_feedback(conn, limit=5) == []


def test_load_recent_feedback_db_error_raises() -> None:
    conn = _mock_conn(None, raise_exc=RuntimeError("boom"))
    with pytest.raises(LoopReadError, match="failed to read feedback_ledger"):
        load_recent_feedback(conn, limit=5)
    # Rollback must be attempted so caller's txn isn't left aborted.
    conn.rollback.assert_called_once()


def test_load_recent_feedback_db_error_tolerates_rollback_failure() -> None:
    """Rollback itself can fail on a dead connection — original error must
    still surface as LoopReadError."""
    conn = _mock_conn(None, raise_exc=RuntimeError("boom"))
    conn.rollback.side_effect = RuntimeError("dead conn")
    with pytest.raises(LoopReadError, match="failed to read feedback_ledger"):
        load_recent_feedback(conn, limit=5)


def test_load_recent_feedback_env_var_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_STEP1_LEDGER_LIMIT", "7")
    conn = _mock_conn([])
    load_recent_feedback(conn)
    cursor = conn.cursor.return_value.__enter__.return_value
    args, _ = cursor.execute.call_args
    assert args[1] == (7,)


def test_load_recent_feedback_env_var_unset_uses_20(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KBL_STEP1_LEDGER_LIMIT", raising=False)
    conn = _mock_conn([])
    load_recent_feedback(conn)
    cursor = conn.cursor.return_value.__enter__.return_value
    args, _ = cursor.execute.call_args
    assert args[1] == (20,)


def test_load_recent_feedback_explicit_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_STEP1_LEDGER_LIMIT", "99")
    conn = _mock_conn([])
    load_recent_feedback(conn, limit=3)
    cursor = conn.cursor.return_value.__enter__.return_value
    args, _ = cursor.execute.call_args
    assert args[1] == (3,)


def test_load_recent_feedback_rejects_non_positive_limit() -> None:
    conn = _mock_conn([])
    with pytest.raises(LoopReadError, match="positive int"):
        load_recent_feedback(conn, limit=0)
    with pytest.raises(LoopReadError, match="positive int"):
        load_recent_feedback(conn, limit=-5)


def test_load_recent_feedback_rejects_malformed_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KBL_STEP1_LEDGER_LIMIT", "banana")
    conn = _mock_conn([])
    with pytest.raises(LoopReadError, match="KBL_STEP1_LEDGER_LIMIT"):
        load_recent_feedback(conn)


# ------------------------------ render_ledger ------------------------------


def test_render_ledger_empty_returns_placeholder() -> None:
    out = render_ledger([])
    assert out == "(no recent Director actions)"


def test_render_ledger_single_row() -> None:
    row = {
        "id": 1,
        "created_at": datetime(2026, 4, 17, tzinfo=timezone.utc),
        "action_type": "promote",
        "target_matter": "hagenauer",
        "target_path": None,
        "signal_id": 77,
        "payload": {},
        "director_note": "escalate",
    }
    out = render_ledger([row])
    assert out == "[2026-04-17] promote hagenauer: escalate"


def test_render_ledger_falls_back_to_target_path_then_dash() -> None:
    rows = [
        {
            "created_at": "2026-04-16T00:00:00+00:00",
            "action_type": "correct",
            "target_matter": None,
            "target_path": "wiki/matters/movie/cards/legal.md",
            "payload": {},
            "director_note": "fix slug typo",
        },
        {
            "created_at": datetime(2026, 4, 15, tzinfo=timezone.utc),
            "action_type": "ignore",
            "target_matter": None,
            "target_path": None,
            "payload": None,
            "director_note": None,
        },
    ]
    out = render_ledger(rows).splitlines()
    assert out[0] == (
        "[2026-04-16] correct wiki/matters/movie/cards/legal.md: fix slug typo"
    )
    # Dash + "(no detail)" when both target and detail are absent.
    assert out[1] == "[2026-04-15] ignore —: (no detail)"


def test_render_ledger_falls_back_to_payload_when_note_missing() -> None:
    row = {
        "created_at": datetime(2026, 4, 14, tzinfo=timezone.utc),
        "action_type": "ayoniso_respond",
        "target_matter": "morv",
        "target_path": None,
        "payload": {"beneficiary": "buyer-3", "amount_eur": 1234},
        "director_note": None,
    }
    out = render_ledger([row])
    assert out.startswith("[2026-04-14] ayoniso_respond morv: ")
    # Stable sort_keys=True ordering so the test isn't flaky on dict iteration.
    assert '"amount_eur": 1234' in out
    assert '"beneficiary": "buyer-3"' in out


def test_render_ledger_collapses_multiline_note() -> None:
    """director_note with embedded newlines must stay on one line so the
    prompt block keeps one row per line."""
    row = {
        "created_at": datetime(2026, 4, 13, tzinfo=timezone.utc),
        "action_type": "promote",
        "target_matter": "aukera",
        "target_path": None,
        "payload": {},
        "director_note": "line one\nline two\n\tindented third",
    }
    out = render_ledger([row])
    assert "\n" not in out.split(": ", 1)[1]
    assert out == "[2026-04-13] promote aukera: line one line two indented third"


def test_render_ledger_twenty_rows_all_rendered() -> None:
    rows = [
        {
            "created_at": datetime(2026, 4, i + 1, tzinfo=timezone.utc),
            "action_type": "promote",
            "target_matter": f"matter_{i}",
            "target_path": None,
            "payload": {},
            "director_note": f"note {i}",
        }
        for i in range(20)
    ]
    out = render_ledger(rows)
    lines = out.splitlines()
    assert len(lines) == 20
    # First and last lines both present; order follows input order.
    assert lines[0].endswith("promote matter_0: note 0")
    assert lines[-1].endswith("promote matter_19: note 19")


def test_render_ledger_handles_unknown_date_shape_without_raising() -> None:
    """Garbage created_at must degrade to a ?-placeholder, not raise — the
    renderer is a best-effort display layer."""
    row = {
        "created_at": 12345,  # not a datetime, not a date-prefix string
        "action_type": "ignore",
        "target_matter": None,
        "target_path": None,
        "payload": {},
        "director_note": "x",
    }
    out = render_ledger([row])
    assert out.startswith("[????-??-??] ignore")


# ------------------------------ module surface ------------------------------


def test_loop_module_public_surface() -> None:
    """Guard against accidental public-API drift."""
    assert hasattr(loop, "LoopReadError")
    assert hasattr(loop, "load_hot_md")
    assert hasattr(loop, "load_recent_feedback")
    assert hasattr(loop, "render_ledger")
    assert issubclass(loop.LoopReadError, RuntimeError)
