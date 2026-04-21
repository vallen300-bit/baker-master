"""Tests for migrations/20260418_expand_signal_queue_status_check.sql.

Two tiers:
    1. Parse-level checks (always run) — UP/DOWN sections present, all
       34 status values declared, Python writer in ``memory/store_back.py``
       stays in sync with the SQL migration.
    2. Live-PG round-trip (gated via ``tests/conftest.py::needs_live_pg``,
       which resolves ``TEST_DATABASE_URL`` or an ephemeral Neon branch)
       — applies UP, INSERTs one row per legal status + asserts a bogus
       status raises ``CheckViolation``; applies DOWN and re-verifies.

Matches the pattern in ``tests/test_migrations.py`` — separate module so
a migration-specific failure localizes to this ticket.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 required for migration tests")
from psycopg2 import errors as pg_errors  # noqa: E402


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "20260418_expand_signal_queue_status_check.sql"
STORE_BACK_PATH = (
    Path(__file__).resolve().parent.parent / "memory" / "store_back.py"
)


_SECTION_RE = re.compile(r"^--\s*==\s*migrate:(up|down)\s*==\s*$", re.MULTILINE)


def _parse_sections(sql_text: str) -> dict[str, str]:
    """Mirror of the parser in ``tests/test_migrations.py`` — kept local
    to keep this test module self-contained (no cross-file import).
    DOWN section ships commented out; strip the leading ``-- `` so it
    becomes executable SQL when the live round-trip replays it."""
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
    stripped = line.lstrip()
    if stripped.startswith("--"):
        rest = stripped[2:]
        if rest.startswith(" "):
            return line.replace("-- ", "", 1)
        return line.replace("--", "", 1)
    return line


# -----------------------------------------------------------------------------
# The canonical 34-value set. Tests assert both the SQL migration and the
# Python writer in store_back.py declare exactly this set.
# -----------------------------------------------------------------------------

EXPANDED_STATUS_SET: frozenset[str] = frozenset(
    {
        # KBL-A legacy (8)
        "pending",
        "processing",
        "done",
        "failed",
        "expired",
        "classified-deferred",
        "failed-reviewed",
        "cost-deferred",
        # KBL-B Layer 0 (1)
        "dropped_layer0",
        # KBL-B Step 1 triage (5)
        "awaiting_triage",
        "triage_running",
        "triage_failed",
        "triage_invalid",
        "routed_inbox",
        # KBL-B Step 2 resolve (3)
        "awaiting_resolve",
        "resolve_running",
        "resolve_failed",
        # KBL-B Step 3 extract (3)
        "awaiting_extract",
        "extract_running",
        "extract_failed",
        # KBL-B Step 4 classify (3)
        "awaiting_classify",
        "classify_running",
        "classify_failed",
        # KBL-B Step 5 opus (4)
        "awaiting_opus",
        "opus_running",
        "opus_failed",
        "paused_cost_cap",
        # KBL-B Step 6 finalize (3)
        "awaiting_finalize",
        "finalize_running",
        "finalize_failed",
        # KBL-B Step 7 commit (3)
        "awaiting_commit",
        "commit_running",
        "commit_failed",
        # KBL-B terminal (1)
        "completed",
    }
)


def _extract_status_values(sql_text: str) -> set[str]:
    """Pull the first ``status IN (...)`` CHECK body from a SQL string and
    return the literal single-quoted values as a set.

    Comments are stripped BEFORE the search so section separators like
    ``-- KBL-A legacy (preserved)`` don't confuse the paren counter — the
    `(preserved)` inside the comment would otherwise close the IN body
    prematurely.
    """
    cleaned = re.sub(r"--[^\n]*", "", sql_text)
    m = re.search(
        r"CHECK\s*\(\s*status\s+IN\s*\(([^)]*)\)",
        cleaned,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return set()
    return set(re.findall(r"'([^']+)'", m.group(1)))


# ------------------------------ parse-level ------------------------------


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.is_file()


def test_migration_parses_to_up_and_down() -> None:
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    assert "up" in sections and "down" in sections
    assert "ALTER TABLE signal_queue" in sections["up"]
    assert "DROP CONSTRAINT IF EXISTS signal_queue_status_check" in sections["up"]
    assert "ADD CONSTRAINT signal_queue_status_check" in sections["up"]


def test_migration_up_contains_exact_expanded_status_set() -> None:
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    up_values = _extract_status_values(sections["up"])
    # All legal states present, nothing extra, nothing missing.
    assert up_values == EXPANDED_STATUS_SET


def test_migration_down_reverts_to_kbl_a_eight() -> None:
    """DOWN narrows back to the pre-KBL-B 8-value set. Important for
    disaster recovery reviewers to see the diff explicitly."""
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))
    down_values = _extract_status_values(sections["down"])
    legacy_eight = {
        "pending",
        "processing",
        "done",
        "failed",
        "expired",
        "classified-deferred",
        "failed-reviewed",
        "cost-deferred",
    }
    assert down_values == legacy_eight


def test_store_back_python_writer_in_sync_with_migration() -> None:
    """``memory/store_back.py`` re-asserts the CHECK on every app boot;
    it MUST carry the same 34-value set or the migration gets reverted."""
    text = STORE_BACK_PATH.read_text(encoding="utf-8")
    # Narrow the parse to the _ensure_signal_queue_additions block so we
    # only pick up the status CHECK, not some other status IN list.
    m = re.search(
        r"def _ensure_signal_queue_additions.*?(?=\n    def )",
        text,
        re.DOTALL,
    )
    assert m, "_ensure_signal_queue_additions block not found in store_back.py"
    block = m.group(0)
    # Extract the first `status IN ( ... )` inside that block only.
    values = _extract_status_values(block)
    assert values == EXPANDED_STATUS_SET, (
        "store_back.py status CHECK drifted from migration set; diff="
        f"{sorted(EXPANDED_STATUS_SET.symmetric_difference(values))}"
    )


def test_migration_uses_running_naming_convention() -> None:
    """No legacy `<step>ing` aliases leak in — writers across PR #7/#8/#10/#11
    all emit `<step>_running`. Reconciled per AI Head 2026-04-18."""
    up_values = _extract_status_values(
        _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))["up"]
    )
    forbidden = {"triaging", "resolving", "extracting", "classifying", "committing"}
    assert up_values.isdisjoint(forbidden), (
        f"legacy -ing aliases leaked: {sorted(up_values & forbidden)}"
    )


def test_all_per_step_states_have_awaiting_running_failed_triple() -> None:
    """Every Step 1–7 phase except Layer 0 and terminal exposes the full
    awaiting/running/failed triple. Protects future writers from typos."""
    phases = (
        "triage",
        "resolve",
        "extract",
        "classify",
        "opus",
        "finalize",
        "commit",
    )
    missing: list[str] = []
    for phase in phases:
        for suffix in ("awaiting", "running", "failed"):
            state = f"awaiting_{phase}" if suffix == "awaiting" else f"{phase}_{suffix}"
            if state not in EXPANDED_STATUS_SET:
                missing.append(state)
    assert not missing, f"per-step states missing from set: {missing}"


# --------- live-PG round-trip (gated via conftest.py::needs_live_pg) ---------


def test_check_constraint_round_trip(needs_live_pg) -> None:
    """Apply UP, INSERT one signal with each legal status (should succeed),
    INSERT with a bogus status (should raise CheckViolation), apply DOWN,
    re-verify the KBL-B-only statuses now fail.

    Uses a savepoint per INSERT so a single failure doesn't tear down the
    whole transaction — psycopg2 would otherwise abort subsequent queries
    after the first CheckViolation.
    """
    sections = _parse_sections(MIGRATION_PATH.read_text(encoding="utf-8"))

    conn = psycopg2.connect(needs_live_pg)
    try:
        with conn.cursor() as cur:
            # UP — idempotent; safe even if a prior run left the widened
            # constraint in place.
            cur.execute(sections["up"])
            conn.commit()

            # Verify the constraint exists under the expected name.
            cur.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'public.signal_queue'::regclass "
                "  AND conname = 'signal_queue_status_check'"
            )
            assert cur.fetchone(), "signal_queue_status_check not present after UP"

            # Each legal status should INSERT successfully. Use a SAVEPOINT
            # so a per-row failure can roll back without trashing the
            # session-level tx. Rows get cleaned up via ROLLBACK TO + the
            # outer commit only after the happy path.
            for status in sorted(EXPANDED_STATUS_SET):
                cur.execute("SAVEPOINT sp_ok")
                try:
                    cur.execute(
                        # STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1
                        # (2026-04-21): ``raw_content`` is not a real
                        # signal_queue column — the bridge writes body
                        # text into ``payload->>'alert_body'``. The body
                        # text is irrelevant to the status-CHECK test
                        # assertion (only ``status`` matters), so use
                        # ``summary`` — a real TEXT column — instead.
                        "INSERT INTO signal_queue (source, summary, status) "
                        "VALUES ('migration_test', %s, %s) RETURNING id",
                        (f"status-check-expand-1 probe: {status}", status),
                    )
                    inserted_id = cur.fetchone()[0]
                    # Keep the session clean — release the savepoint but
                    # roll back the row so we don't pollute the live table.
                    cur.execute("ROLLBACK TO SAVEPOINT sp_ok")
                    cur.execute("RELEASE SAVEPOINT sp_ok")
                    assert inserted_id is not None
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_ok")
                    cur.execute("RELEASE SAVEPOINT sp_ok")
                    raise

            # Bogus status → CheckViolation.
            cur.execute("SAVEPOINT sp_bad")
            try:
                with pytest.raises(pg_errors.CheckViolation):
                    cur.execute(
                        "INSERT INTO signal_queue (source, summary, status) "
                        "VALUES ('migration_test', 'probe', 'garbage_state')"
                    )
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT sp_bad")
                cur.execute("RELEASE SAVEPOINT sp_bad")

            conn.commit()

            # DOWN — narrows back to the KBL-A 8-value set. A KBL-B-only
            # status must now fail.
            cur.execute(sections["down"])
            conn.commit()

            cur.execute("SAVEPOINT sp_after_down")
            try:
                with pytest.raises(pg_errors.CheckViolation):
                    cur.execute(
                        "INSERT INTO signal_queue (source, summary, status) "
                        "VALUES ('migration_test', 'probe', 'awaiting_triage')"
                    )
            finally:
                cur.execute("ROLLBACK TO SAVEPOINT sp_after_down")
                cur.execute("RELEASE SAVEPOINT sp_after_down")
    finally:
        # Always leave the DB on the expanded set so follow-up tests in
        # the same TEST_DATABASE_URL run against a known-good constraint.
        try:
            with conn.cursor() as cur:
                cur.execute(sections["up"])
                conn.commit()
        except Exception:
            conn.rollback()
        conn.close()
