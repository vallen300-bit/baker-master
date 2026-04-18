"""Tests for SQL migration files in migrations/.

Strategy — gated live-PostgreSQL test. Runs the UP migration against a test
database, verifies each expected table + index exists, runs the DOWN
migration, verifies cleanup. Skips entirely when TEST_DATABASE_URL is unset
so local unit runs and CI (no DB) don't fail.

Set TEST_DATABASE_URL to a throwaway branch/schema — NOT production. The
test wraps each migration in its own transaction and drops tables at the
end even if assertions fail, but cross-test contamination is only fully
guaranteed when the URL points at an ephemeral DB.

Discovery: migration files under migrations/ get a dedicated test module
each (one module per migration ticket) so a failure localizes to a ticket.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required for migration tests")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")

requires_db = pytest.mark.skipif(
    not TEST_DB_URL,
    reason="TEST_DATABASE_URL unset — skipping live-PG migration check",
)


_SECTION_RE = re.compile(
    r"^--\s*==\s*migrate:(up|down)\s*==\s*$",
    re.MULTILINE,
)


def _parse_sections(sql_text: str) -> dict[str, str]:
    """Split a migration file into {'up': ..., 'down': ...} sections.

    DOWN section ships commented out (disaster recovery only). This parser
    strips the leading `-- ` from each line so it becomes executable SQL.
    """
    matches = list(_SECTION_RE.finditer(sql_text))
    if not matches:
        raise RuntimeError("no `-- == migrate:(up|down) ==` markers found")
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(sql_text)
        body = sql_text[start:end].strip()
        if label == "down":
            body = "\n".join(
                _strip_comment_leader(line) for line in body.splitlines()
            ).strip()
        sections[label] = body
    return sections


def _strip_comment_leader(line: str) -> str:
    """Uncomment `-- ` prefix if present. Leaves pure comment lines (the
    header notes above the SQL) intact so BEGIN;/COMMIT;/DROP stay anchored."""
    stripped = line.lstrip()
    if stripped.startswith("--"):
        rest = stripped[2:]
        if rest.startswith(" "):
            return line.replace("-- ", "", 1)
        return line.replace("--", "", 1)
    return line


# --------------------- parser unit tests (no DB needed) ---------------------


def test_parse_sections_finds_both_markers():
    sample = (
        "-- header\n"
        "-- == migrate:up ==\n"
        "CREATE TABLE t (id INT);\n"
        "-- == migrate:down ==\n"
        "-- DROP TABLE t;\n"
    )
    sections = _parse_sections(sample)
    assert set(sections) == {"up", "down"}
    assert "CREATE TABLE t" in sections["up"]
    assert "DROP TABLE t;" in sections["down"]
    assert "-- DROP TABLE" not in sections["down"]  # comment leader stripped


def test_parse_sections_raises_on_missing_markers():
    with pytest.raises(RuntimeError, match="no `-- == migrate"):
        _parse_sections("CREATE TABLE t (id INT);")


# --------------- migration syntax check (parses but does not run) -----------


def test_loop_infrastructure_migration_file_exists():
    assert (MIGRATIONS_DIR / "20260418_loop_infrastructure.sql").is_file()


def test_loop_infrastructure_migration_parses_to_up_and_down():
    path = MIGRATIONS_DIR / "20260418_loop_infrastructure.sql"
    sections = _parse_sections(path.read_text(encoding="utf-8"))
    # signal_queue.id BIGINT upgrade must run BEFORE the new tables.
    assert "ALTER TABLE signal_queue ALTER COLUMN id TYPE BIGINT" in sections["up"]
    assert "ALTER SEQUENCE signal_queue_id_seq AS BIGINT" in sections["up"]
    assert sections["up"].index("ALTER TABLE signal_queue") < sections["up"].index(
        "CREATE TABLE IF NOT EXISTS feedback_ledger"
    )
    assert "CREATE TABLE IF NOT EXISTS feedback_ledger" in sections["up"]
    assert "CREATE TABLE IF NOT EXISTS kbl_layer0_hash_seen" in sections["up"]
    assert "CREATE TABLE IF NOT EXISTS kbl_layer0_review" in sections["up"]
    # DOWN: tables drop BEFORE signal_queue downgrade (reverse of UP).
    assert "DROP TABLE IF EXISTS feedback_ledger" in sections["down"]
    assert "DROP TABLE IF EXISTS kbl_layer0_hash_seen" in sections["down"]
    assert "DROP TABLE IF EXISTS kbl_layer0_review" in sections["down"]
    assert "ALTER TABLE signal_queue ALTER COLUMN id TYPE INTEGER" in sections["down"]
    assert "ALTER SEQUENCE signal_queue_id_seq AS INTEGER" in sections["down"]
    assert sections["down"].index("DROP TABLE IF EXISTS feedback_ledger") < sections[
        "down"
    ].index("ALTER TABLE signal_queue")


# ------------- live-PG round-trip (skipped without TEST_DATABASE_URL) --------


@requires_db
def test_loop_infrastructure_up_down_round_trip():
    path = MIGRATIONS_DIR / "20260418_loop_infrastructure.sql"
    sections = _parse_sections(path.read_text(encoding="utf-8"))

    expected_tables = ("feedback_ledger", "kbl_layer0_hash_seen", "kbl_layer0_review")
    expected_indexes = (
        "idx_feedback_ledger_created_at",
        "idx_feedback_ledger_matter",
        "idx_kbl_layer0_hash_ttl",
        "idx_kbl_layer0_review_pending",
    )

    conn = psycopg2.connect(TEST_DB_URL)
    try:
        with conn.cursor() as cur:
            # Defensive cleanup in case a prior failed run left residue.
            cur.execute(sections["down"])
            conn.commit()

            # UP
            cur.execute(sections["up"])
            conn.commit()
            for t in expected_tables:
                cur.execute(
                    "SELECT to_regclass(%s)::text",
                    (f"public.{t}",),
                )
                row = cur.fetchone()
                assert row and row[0] == t, f"table {t} not present after UP"
            for idx in expected_indexes:
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname=%s",
                    (idx,),
                )
                assert cur.fetchone(), f"index {idx} not present after UP"

            # Idempotency — running UP again must not error.
            cur.execute(sections["up"])
            conn.commit()

            # DOWN
            cur.execute(sections["down"])
            conn.commit()
            for t in expected_tables:
                cur.execute(
                    "SELECT to_regclass(%s)::text",
                    (f"public.{t}",),
                )
                row = cur.fetchone()
                assert not row or row[0] is None, f"table {t} still present after DOWN"
    finally:
        # Belt-and-suspenders: attempt cleanup even if assertions failed.
        try:
            with conn.cursor() as cur:
                cur.execute(sections["down"])
                conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
