"""Tests for BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1.

Two tiers:
    1. Parse-level checks (always run) — migration file exists with UP/DOWN
       sections, UP contains the ALTER COLUMN TYPE TEXT intent, bootstrap
       DDL in ``memory/store_back.py`` declares ``hot_md_match TEXT`` (not
       BOOLEAN), and the type-reconciliation DO block lives inside
       ``_ensure_signal_queue_additions``.
    2. Live-PG round-trip (gated via ``tests/conftest.py::needs_live_pg``)
       — three paths:
         (a) legacy DB with BOOLEAN column → apply migration → TEXT.
         (b) legacy DB with BOOLEAN column → run bootstrap additions
             (self-heal path) → TEXT.
         (c) fresh DB via ``_ensure_signal_queue_base`` → TEXT from
             minute zero.

All three paths must end at ``data_type = 'text'``. This is the regression
gate against the hot_md_match BOOLEAN/TEXT drift diagnosed in
``briefs/_reports/B2_bridge_hot_md_match_drift_20260421.md``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required for migration tests")


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "20260421b_alter_hot_md_match_to_text.sql"
STORE_BACK_PATH = (
    Path(__file__).resolve().parent.parent / "memory" / "store_back.py"
)


_SECTION_RE = re.compile(r"^--\s*==\s*migrate:(up|down)\s*==\s*$", re.MULTILINE)


def _parse_sections(sql_text: str) -> dict[str, str]:
    """Local mirror of tests/test_status_check_expand_migration.py parser —
    keeps this module self-contained (no cross-test import)."""
    matches = list(_SECTION_RE.finditer(sql_text))
    if not matches:
        raise RuntimeError("no `-- == migrate:(up|down) ==` markers found")
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql_text)
        sections[label] = sql_text[start:end].strip()
    return sections


# --------------------------- parse-level checks ---------------------------


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"BRIDGE_HOT_MD_MATCH_TYPE_REPAIR_1 migration missing at "
        f"{MIGRATION_PATH}. Filename must sort AFTER "
        f"20260421_signal_queue_hot_md_match.sql so the runner applies "
        f"it second."
    )


def test_migration_sorts_after_original() -> None:
    """Runner sorts `*.sql` lexicographically and applies in order. The
    type-repair must fire AFTER the original `ADD COLUMN IF NOT EXISTS`
    migration (which may be a no-op on legacy DBs with pre-existing
    BOOLEAN column), so the repair is what actually flips the type."""
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    names = [f.name for f in files]
    try:
        repair_idx = names.index("20260421b_alter_hot_md_match_to_text.sql")
        original_idx = names.index("20260421_signal_queue_hot_md_match.sql")
    except ValueError as e:
        pytest.fail(f"migration not found in glob order: {e}")
    assert repair_idx > original_idx, (
        f"type-repair must sort after the original hot_md_match "
        f"migration so ALTER COLUMN TYPE TEXT runs last. "
        f"Got repair_idx={repair_idx}, original_idx={original_idx}"
    )


def test_migration_has_up_and_down_sections() -> None:
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert "up" in sections, "migration missing -- == migrate:up == section"
    assert "down" in sections, "migration missing -- == migrate:down == section"
    assert len(sections["up"]) > 0, "UP section is empty"


def test_migration_up_contains_alter_column_type_text() -> None:
    """UP must reference the ALTER COLUMN ... TYPE TEXT USING ::text intent.
    Exact formatting flexes; semantic tokens do not."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    up = sections["up"].lower()
    assert "alter table signal_queue" in up
    assert "alter column hot_md_match" in up
    assert "type text" in up
    assert "using hot_md_match::text" in up


def test_migration_up_is_idempotent_on_already_text() -> None:
    """UP must guard on information_schema data_type = 'boolean' so
    re-running on a DB where the column is already TEXT is a no-op (no
    unnecessary table rewrite, no error)."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    up = sections["up"].lower()
    assert "information_schema.columns" in up
    assert "data_type" in up
    assert "boolean" in up
    assert "do $$" in up  # conditional DO block
    assert "end $$" in up


def test_bootstrap_base_declares_hot_md_match_as_text() -> None:
    """``_ensure_signal_queue_base`` CREATE TABLE must declare
    ``hot_md_match TEXT`` (not BOOLEAN). Prevents fresh-DB boots from
    recreating the drift on minute zero."""
    text = STORE_BACK_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"def _ensure_signal_queue_base.*?(?=\n    def )",
        text,
        re.DOTALL,
    )
    assert m, "_ensure_signal_queue_base block not found"
    block = m.group(0)
    # Canonical TEXT declaration must be present.
    assert re.search(r"hot_md_match\s+TEXT", block), (
        "_ensure_signal_queue_base must declare hot_md_match TEXT"
    )
    # Legacy BOOLEAN declaration must not be present.
    assert not re.search(r"hot_md_match\s+BOOLEAN", block), (
        "_ensure_signal_queue_base still declares hot_md_match BOOLEAN "
        "— post-fix this should be TEXT"
    )


def test_bootstrap_additions_has_type_reconciliation_block() -> None:
    """``_ensure_signal_queue_additions`` must contain the
    BOOLEAN→TEXT reconciliation DO block so legacy deployments
    self-heal on boot even if the migration ledger is stale."""
    text = STORE_BACK_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"def _ensure_signal_queue_additions.*?(?=\n    def )",
        text,
        re.DOTALL,
    )
    assert m, "_ensure_signal_queue_additions block not found"
    block = m.group(0)
    # Look for the signature tokens of the reconciliation block.
    assert "information_schema.columns" in block
    assert "hot_md_match" in block
    assert "data_type" in block and "boolean" in block
    assert "ALTER COLUMN hot_md_match TYPE TEXT" in block
    assert "USING hot_md_match::text" in block


# --------------------------- live-PG round-trip ---------------------------


def _drop_and_create_as_boolean(conn) -> None:
    """Force the legacy shape on the test DB: hot_md_match BOOLEAN."""
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE signal_queue DROP COLUMN IF EXISTS hot_md_match"
        )
        cur.execute(
            "ALTER TABLE signal_queue ADD COLUMN hot_md_match BOOLEAN"
        )
    conn.commit()


def _column_data_type(conn, col: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'signal_queue' AND column_name = %s",
            (col,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def test_migration_up_flips_boolean_to_text_live(needs_live_pg) -> None:
    """Apply the migration UP to a DB whose hot_md_match is BOOLEAN and
    assert the column ends as TEXT. This is the exact recovery path the
    bridge needs on production."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))

    conn = psycopg2.connect(needs_live_pg)
    try:
        _drop_and_create_as_boolean(conn)
        assert _column_data_type(conn, "hot_md_match") == "boolean"

        with conn.cursor() as cur:
            cur.execute(sections["up"])
        conn.commit()

        assert _column_data_type(conn, "hot_md_match") == "text"
    finally:
        conn.close()


def test_migration_up_idempotent_on_text_column_live(needs_live_pg) -> None:
    """Apply the migration UP a SECOND time (once column is already
    TEXT) and assert it stays TEXT and the call does not raise. Guards
    the ``IF data_type = 'boolean'`` condition."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))

    conn = psycopg2.connect(needs_live_pg)
    try:
        # Ensure column is TEXT (either already, or coerced here).
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE signal_queue "
                "ADD COLUMN IF NOT EXISTS hot_md_match TEXT"
            )
            cur.execute(
                "DO $$ BEGIN "
                "IF EXISTS ("
                "  SELECT 1 FROM information_schema.columns "
                "   WHERE table_name='signal_queue' "
                "     AND column_name='hot_md_match' "
                "     AND data_type='boolean'"
                ") THEN "
                "  ALTER TABLE signal_queue "
                "    ALTER COLUMN hot_md_match TYPE TEXT "
                "    USING hot_md_match::text; "
                "END IF; END $$;"
            )
        conn.commit()
        assert _column_data_type(conn, "hot_md_match") == "text"

        with conn.cursor() as cur:
            cur.execute(sections["up"])
        conn.commit()

        # Still TEXT, no raise.
        assert _column_data_type(conn, "hot_md_match") == "text"
    finally:
        conn.close()


def test_bootstrap_additions_self_heals_boolean_to_text_live(
    needs_live_pg,
) -> None:
    """Force the legacy shape (hot_md_match BOOLEAN), then call
    ``SentinelStoreBack._ensure_signal_queue_additions`` — the bootstrap
    reconciliation block must coerce the column to TEXT. This is the
    defense-in-depth layer for deployments whose migration ledger is
    stale for whatever reason."""
    import os
    from unittest.mock import patch

    conn = psycopg2.connect(needs_live_pg)
    try:
        _drop_and_create_as_boolean(conn)
        assert _column_data_type(conn, "hot_md_match") == "boolean"
    finally:
        conn.close()

    # Point SentinelStoreBack at the same ephemeral DB the test conn used.
    # POSTGRES_URL / DATABASE_URL override in the store_back path —
    # monkeypatch via env var for the duration of this call.
    with patch.dict(os.environ, {"DATABASE_URL": needs_live_pg}):
        from memory.store_back import SentinelStoreBack

        # Reset singleton so the store picks up the DATABASE_URL override
        # instead of any prior cached pool.
        SentinelStoreBack._instance = None
        store = SentinelStoreBack()
        store._ensure_signal_queue_additions()

    conn = psycopg2.connect(needs_live_pg)
    try:
        assert _column_data_type(conn, "hot_md_match") == "text"
    finally:
        conn.close()


def test_bootstrap_base_creates_fresh_table_with_text_column_live(
    needs_live_pg,
) -> None:
    """Fresh-DB path: drop the whole signal_queue table, re-run
    ``_ensure_signal_queue_base``, assert hot_md_match comes back as
    TEXT from minute zero (not BOOLEAN). Guards against a regression
    of the KBL-19-era bootstrap DDL declaration.
    """
    import os
    from unittest.mock import patch

    conn = psycopg2.connect(needs_live_pg)
    try:
        with conn.cursor() as cur:
            # CASCADE handles any dependent views / FKs (there are none
            # in the spec but keep the test robust against future ones).
            cur.execute("DROP TABLE IF EXISTS signal_queue CASCADE")
        conn.commit()
    finally:
        conn.close()

    with patch.dict(os.environ, {"DATABASE_URL": needs_live_pg}):
        from memory.store_back import SentinelStoreBack

        SentinelStoreBack._instance = None
        store = SentinelStoreBack()
        store._ensure_signal_queue_base()

    conn = psycopg2.connect(needs_live_pg)
    try:
        # Table must exist.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'signal_queue'"
            )
            assert cur.fetchone() is not None, "signal_queue not recreated"
        # hot_md_match must be TEXT, not BOOLEAN.
        assert _column_data_type(conn, "hot_md_match") == "text", (
            "fresh bootstrap must declare hot_md_match as TEXT (not BOOLEAN)"
        )
    finally:
        conn.close()
