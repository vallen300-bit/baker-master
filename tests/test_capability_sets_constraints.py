"""Tests for the M4 CHECK constraint on ``capability_sets``.

Two tiers, mirroring ``tests/test_status_check_expand_migration.py``:

1. Parse-level (always run): the migration file declares the right shape and
   the Python bootstrap in ``memory/store_back.py`` carries the same
   constraint definition. Closes Lesson #50 (migration-vs-bootstrap drift).
2. Live-PG round-trip (gated via ``tests/conftest.py::needs_live_pg``): apply
   the migration, INSERT an archive row with non-empty ``trigger_patterns``
   → expect ``CheckViolation``; INSERT a domain row with the same patterns
   → succeeds.

Scoped to GROK_API_HARDENING_1 M4. The fix protects against future
``capability_type`` flips on archive rows (e.g. ``grok_realtime``,
``claimsmax_archive``) hijacking Cortex Phase 3 routing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required for migration tests")
from psycopg2 import errors as pg_errors  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION_PATH = REPO_ROOT / "migrations" / "20260518_capability_sets_archive_no_trigger_patterns.sql"
STORE_BACK_PATH = REPO_ROOT / "memory" / "store_back.py"

CONSTRAINT_NAME = "capability_sets_archive_no_trigger_patterns"


_SECTION_RE = re.compile(r"^--\s*==\s*migrate:(up|down)\s*==\s*$", re.MULTILINE)


def _parse_sections(sql_text: str) -> dict[str, str]:
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


# ------------------------------ parse-level ------------------------------


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.is_file()


def test_migration_orders_update_before_constraint() -> None:
    """Step 1 (UPDATE) must run before Step 2 (ADD CONSTRAINT), otherwise the
    constraint validation aborts on pre-existing archive rows. Strip SQL
    comments first — both phrases appear in the explanatory header."""
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    sections = _parse_sections(sql)
    up = re.sub(r"--[^\n]*", "", sections["up"])
    update_pos = up.upper().find("UPDATE CAPABILITY_SETS")
    add_constraint_pos = up.find("ADD CONSTRAINT")
    assert update_pos != -1, "UPDATE statement missing from migration UP"
    assert add_constraint_pos != -1, "ADD CONSTRAINT missing from migration UP"
    assert update_pos < add_constraint_pos, (
        "UPDATE must precede ADD CONSTRAINT — otherwise the new constraint "
        "fails to validate on existing archive rows."
    )


def _extract_check_predicate(sql_text: str, constraint_name: str) -> str:
    """Return the CHECK predicate body for ``constraint_name`` from ``sql_text``.

    Handles balanced parentheses so nested calls (e.g. ``jsonb_array_length(
    trigger_patterns)``) parse correctly. Returns ``""`` if not found.
    """
    pattern = re.compile(
        rf"ADD\s+CONSTRAINT\s+{re.escape(constraint_name)}\s+CHECK\s*\(",
        re.IGNORECASE,
    )
    m = pattern.search(sql_text)
    if not m:
        return ""
    start = m.end()
    depth = 1
    i = start
    while i < len(sql_text) and depth > 0:
        ch = sql_text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    if depth != 0:
        return ""
    return sql_text[start : i - 1]


def _check_predicate_clauses(predicate: str) -> list[str]:
    """Split a normalized CHECK predicate into OR-joined clauses."""
    normalized = re.sub(r"\s+", " ", predicate).strip()
    return [c.strip() for c in re.split(r"\s+OR\s+", normalized, flags=re.IGNORECASE)]


def test_store_back_bootstrap_in_sync_with_migration() -> None:
    """``_ensure_capability_sets_table`` must declare the same CHECK predicate
    clauses as the migration. Stronger than a constraint-name string match:
    extracts the predicate body from both files and asserts each load-bearing
    OR-clause is present verbatim in the bootstrap block — defends against the
    Lesson #50 failure mode of one file's predicate drifting while the other
    keeps the same constraint name."""
    migration_sql = MIGRATION_PATH.read_text(encoding="utf-8")
    migration_predicate = _extract_check_predicate(migration_sql, CONSTRAINT_NAME)
    assert migration_predicate, (
        "could not extract the CHECK predicate from the migration SQL — file "
        "shape may have changed"
    )
    migration_clauses = _check_predicate_clauses(migration_predicate)
    assert len(migration_clauses) >= 2, (
        f"expected ≥2 OR-clauses in the CHECK predicate, got: {migration_clauses!r}"
    )

    text = STORE_BACK_PATH.read_text(encoding="utf-8")
    m = re.search(
        r"def _ensure_capability_sets_table.*?(?=\n    def )",
        text,
        re.DOTALL,
    )
    assert m, "_ensure_capability_sets_table block not found in store_back.py"
    block = m.group(0)
    assert CONSTRAINT_NAME in block, (
        f"bootstrap missing the {CONSTRAINT_NAME!r} constraint — drift vs migration"
    )
    assert "UPDATE capability_sets" in block, (
        "bootstrap missing the trigger_patterns UPDATE — fresh DBs would fail the "
        "ADD CONSTRAINT if a seed left patterns on an archive row"
    )
    bootstrap_predicate = _extract_check_predicate(block, CONSTRAINT_NAME)
    assert bootstrap_predicate, (
        f"bootstrap block declares {CONSTRAINT_NAME!r} but the CHECK predicate "
        "could not be extracted — DDL shape may have changed"
    )
    bootstrap_normalized = re.sub(r"\s+", " ", bootstrap_predicate).strip()
    for clause in migration_clauses:
        assert clause in bootstrap_normalized, (
            f"bootstrap predicate missing migration clause {clause!r} — drift "
            f"vs {MIGRATION_PATH.name}. Bootstrap normalized: "
            f"{bootstrap_normalized!r}"
        )


# ------------------------------ live-PG round-trip ------------------------------


def _ensure_minimal_capability_sets_table(cur) -> None:
    """Idempotent — mirror just the columns the constraint references plus the
    minimum needed for an INSERT. The full bootstrap in store_back.py pulls in
    voyage/qdrant which we don't need for a constraint-only test."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS capability_sets (
            id                  SERIAL PRIMARY KEY,
            slug                TEXT NOT NULL UNIQUE,
            name                TEXT NOT NULL,
            capability_type     TEXT NOT NULL DEFAULT 'domain',
            domain              TEXT NOT NULL,
            role_description    TEXT NOT NULL,
            tools               JSONB DEFAULT '[]'::jsonb,
            output_format       TEXT DEFAULT 'prose',
            trigger_patterns    JSONB DEFAULT '[]'::jsonb,
            active              BOOLEAN DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def _drop_constraint_if_exists(cur) -> None:
    cur.execute(
        f"ALTER TABLE capability_sets DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}"
    )


def test_capability_sets_archive_no_trigger_patterns_constraint_blocks_insert(
    needs_live_pg,
) -> None:
    """After UP, an archive row with non-empty trigger_patterns must be rejected.
    An archive row with empty patterns succeeds."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))

    conn = psycopg2.connect(needs_live_pg)
    try:
        with conn.cursor() as cur:
            _ensure_minimal_capability_sets_table(cur)
            _drop_constraint_if_exists(cur)
            conn.commit()

            # Apply UP; idempotent guards make this safe to re-run.
            cur.execute(sections["up"])
            conn.commit()

            cur.execute(
                "SELECT conname FROM pg_constraint WHERE conname = %s",
                (CONSTRAINT_NAME,),
            )
            assert cur.fetchone(), f"{CONSTRAINT_NAME} not present after UP"

            slug_bad = "test_archive_bad_m4"
            slug_ok = "test_archive_ok_m4"

            # Negative: archive + patterns → CheckViolation.
            cur.execute("SAVEPOINT sp_bad")
            try:
                with pytest.raises(pg_errors.CheckViolation):
                    cur.execute(
                        """
                        INSERT INTO capability_sets
                            (slug, name, capability_type, domain, role_description,
                             tools, output_format, trigger_patterns, active)
                        VALUES (%s, 'bad', 'archive', 'd', 'r', '[]'::jsonb, 'json',
                                '["x"]'::jsonb, FALSE)
                        """,
                        (slug_bad,),
                    )
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT sp_bad")
                cur.execute("RELEASE SAVEPOINT sp_bad")

            # Positive: archive + empty patterns → succeeds.
            cur.execute("SAVEPOINT sp_ok")
            try:
                cur.execute(
                    """
                    INSERT INTO capability_sets
                        (slug, name, capability_type, domain, role_description,
                         tools, output_format, trigger_patterns, active)
                    VALUES (%s, 'ok', 'archive', 'd', 'r', '[]'::jsonb, 'json',
                            '[]'::jsonb, FALSE) RETURNING id
                    """,
                    (slug_ok,),
                )
                row = cur.fetchone()
                assert row is not None
                # Roll back the row so we don't pollute the live table.
                cur.execute("ROLLBACK TO SAVEPOINT sp_ok")
                cur.execute("RELEASE SAVEPOINT sp_ok")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_ok")
                cur.execute("RELEASE SAVEPOINT sp_ok")
                raise

            conn.commit()
    finally:
        # Leave the DB with the constraint installed — production state.
        try:
            with conn.cursor() as cur:
                cur.execute(sections["up"])
                conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


def test_capability_sets_domain_can_still_have_trigger_patterns(
    needs_live_pg,
) -> None:
    """Domain rows are unaffected — they may carry trigger_patterns freely."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))

    conn = psycopg2.connect(needs_live_pg)
    try:
        with conn.cursor() as cur:
            _ensure_minimal_capability_sets_table(cur)
            cur.execute(sections["up"])
            conn.commit()

            slug = "test_domain_with_patterns_m4"
            cur.execute("SAVEPOINT sp")
            try:
                cur.execute(
                    """
                    INSERT INTO capability_sets
                        (slug, name, capability_type, domain, role_description,
                         tools, output_format, trigger_patterns, active)
                    VALUES (%s, 'd', 'domain', 'legal', 'r', '[]'::jsonb, 'json',
                            '["legal", "tax"]'::jsonb, FALSE) RETURNING id
                    """,
                    (slug,),
                )
                assert cur.fetchone() is not None
                cur.execute("ROLLBACK TO SAVEPOINT sp")
                cur.execute("RELEASE SAVEPOINT sp")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp")
                cur.execute("RELEASE SAVEPOINT sp")
                raise

            conn.commit()
    finally:
        conn.close()
