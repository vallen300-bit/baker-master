"""Migration runner for Render-hosted Baker services.

Applied exclusively from ``outputs/dashboard.py`` startup hook. Mac Mini
``poller.py`` MUST NOT invoke this: schema apply is Render's responsibility.
By analogy to CHANDA Inv 9 (single AGENT writer for signals), Render is the
single SCHEMA writer for migrations — multiple writers would race on
``schema_migrations`` inserts and could half-apply a file even with the
advisory lock (the lock only serializes within Postgres, not across hosts
that might target different databases).

Design points (per B2-APPROVED brief v2, commit ``a532a13``):

* **Own connection, not ``_get_store()``.** Runner opens a dedicated
  ``psycopg2.connect(DATABASE_URL)`` so a migration failure never masks
  as a Qdrant/Voyage bootstrap failure inside ``SentinelStoreBack``.

* **Advisory lock** (``pg_try_advisory_lock(0x42BA4E00001)``) serializes
  concurrent boots within Postgres. 30s non-blocking poll, graceful
  ``return []`` on timeout so a second replica can boot against the
  sibling's applied state instead of deadlocking forever.

* **sha256 drift aborts startup.** Migrations are immutable once applied;
  editing an applied file is a bug. The runner aborts loud so Director
  reconciles manually (``DELETE FROM schema_migrations WHERE filename=...``
  + restart).

* **Per-file transaction.** One file = one ``BEGIN``/``COMMIT``. On SQL
  error → ``ROLLBACK``, log, raise ``MigrationError``. Never leave a
  half-applied file claimed in ``schema_migrations``.

* **``schema_migrations`` column-drift defense.** After
  ``CREATE TABLE IF NOT EXISTS`` the runner verifies column shape via
  ``information_schema`` — catches the "we upgraded the runner but
  forgot to migrate its own table" failure mode that ``IF NOT EXISTS``
  silently papers over.

* **Raise-loud vs. warn-swallow.** This runner raises on any error
  (except the advisory-lock-timeout graceful path). That is deliberately
  DIFFERENT from ``outputs.dashboard._init_store``'s warn-swallow-on-PG-
  cold-start policy: cold-start is a transient retry; migration drift is
  a permanent state bug. P2 of the B2-approved polish list explicitly
  keeps those two semantics separate.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

import psycopg2

logger = logging.getLogger("config.migration_runner")

# Constant advisory-lock key — mnemonic "Baker migrations v1". Stays in int8
# range. Must not collide with ad-hoc locks; no other Baker code holds this key.
_MIGRATION_LOCK_KEY: int = 0x42BA4E00001

# Module-level so Test #8 can monkey-patch to a short timeout (P1).
_LOCK_TIMEOUT_SECONDS: float = 30.0
_LOCK_POLL_INTERVAL_SECONDS: float = 0.5

_DEFAULT_MIGRATIONS_DIR: str = "migrations"

# Phase 1 legacy files — authored before the ``-- == migrate:up ==`` marker
# convention landed. Retire no earlier than Phase 2 (when both are rewritten
# with markers in the same PR that drops them from this set). CI test
# ``test_migration_file_has_up_marker`` skips files in this set.
_GRANDFATHERED: frozenset[str] = frozenset(
    {
        "20260419_mac_mini_heartbeat.sql",
        "20260419_add_kbl_cost_ledger_and_kbl_log.sql",
    }
)


class MigrationError(RuntimeError):
    """Raised when a migration fails or sha256 drift is detected.

    Startup MUST abort — the caller in ``outputs.dashboard._run_migrations``
    propagates this to FastAPI lifespan so the process never finishes
    startup on a half-applied or drifted schema.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _ensure_tracking_table(conn) -> None:
    """Create ``schema_migrations`` if absent, then verify column shape (N4)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                sha256     TEXT NOT NULL
            )
            """
        )
        conn.commit()

        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'schema_migrations'
            """
        )
        cols = {row[0] for row in cur.fetchall()}
    expected = {"filename", "applied_at", "sha256"}
    missing = expected - cols
    if missing:
        raise MigrationError(
            f"schema_migrations exists but is missing expected columns: {sorted(missing)}. "
            f"Drop and recreate manually, then restart."
        )


def _applied_set(conn) -> dict[str, str]:
    """Return ``{filename: stored_sha256}`` for all claimed migrations."""
    with conn.cursor() as cur:
        cur.execute("SELECT filename, sha256 FROM schema_migrations")
        return {r[0]: r[1] for r in cur.fetchall()}


def _apply_one(conn, path: Path, sha: str) -> None:
    """Apply one migration file in its own transaction. Raise on any error."""
    sql = path.read_text()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename, sha256) VALUES (%s, %s)",
                (path.name, sha),
            )
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(
            "migration failed: filename=%s error=%s — rolled back, startup aborting",
            path.name,
            e,
        )
        raise MigrationError(f"migration {path.name!r} failed: {e}") from e


def _acquire_lock(conn) -> bool:
    """Non-blocking advisory-lock acquisition with module-level timeout.

    Uses ``pg_try_advisory_lock`` (non-blocking) in a poll loop rather than
    ``pg_advisory_lock`` (blocking) so a stuck sibling that crashed mid-apply
    before running ``finally`` cannot deadlock the second replica forever.
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    with conn.cursor() as cur:
        while True:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))
            row = cur.fetchone()
            if row and row[0]:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(_LOCK_POLL_INTERVAL_SECONDS)


def _release_lock(conn) -> None:
    """Best-effort advisory-lock release. Never raise — logger only."""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))
    except Exception as e:
        logger.warning("pg_advisory_unlock failed (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run_pending_migrations(
    database_url: str,
    migrations_dir: str = _DEFAULT_MIGRATIONS_DIR,
) -> list[str]:
    """Apply all pending ``*.sql`` files under ``migrations_dir`` in lex order.

    Returns the list of newly-applied filenames (empty on "all up-to-date"
    and on advisory-lock-timeout graceful-degrade).

    Raises ``MigrationError`` on sha256 drift, SQL error, or schema_migrations
    column drift. The caller (startup hook) MUST abort on that exception —
    half-applied schemas are worse than a failed deploy.
    """
    conn = psycopg2.connect(database_url)
    try:
        acquired = _acquire_lock(conn)
        if not acquired:
            logger.warning(
                "migration runner could not acquire advisory lock within %.0fs; "
                "another replica is mid-apply. Continuing startup without running migrations.",
                _LOCK_TIMEOUT_SECONDS,
            )
            return []

        try:
            _ensure_tracking_table(conn)
            applied = _applied_set(conn)

            mig_dir = Path(migrations_dir)
            files = sorted(mig_dir.glob("*.sql"))
            result: list[str] = []
            for path in files:
                current_sha = _sha256(path)
                stored = applied.get(path.name)
                if stored is not None:
                    if stored != current_sha:
                        raise MigrationError(
                            f"migration sha256 drift: filename={path.name} "
                            f"stored={stored} current={current_sha}. "
                            f"Rebase, revert, or force-re-apply via "
                            f"DELETE FROM schema_migrations WHERE filename='{path.name}'"
                        )
                    continue
                _apply_one(conn, path, current_sha)
                logger.info(
                    "migration applied: %s (sha256: %s)", path.name, current_sha[:8]
                )
                result.append(path.name)
            return result
        finally:
            _release_lock(conn)
    finally:
        conn.close()
