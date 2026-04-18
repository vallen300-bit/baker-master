"""Key-value access to kbl_runtime_state (atomic UPSERT for writes)."""

from __future__ import annotations

from kbl.db import get_conn


def get_state(key: str, default: str = "") -> str:
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM kbl_runtime_state WHERE key = %s", (key,))
                row = cur.fetchone()
                return row[0] if row else default
        except Exception:
            conn.rollback()
            raise


def set_state(key: str, value: str, updated_by: str = "pipeline") -> None:
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kbl_runtime_state (key, value, updated_at, updated_by)
                    VALUES (%s, %s, NOW(), %s)
                    ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        updated_at = EXCLUDED.updated_at,
                        updated_by = EXCLUDED.updated_by
                    """,
                    (key, value, updated_by),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise


def increment_state(key: str, updated_by: str = "pipeline") -> int:
    """Atomic counter increment; returns the new value."""
    with get_conn() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kbl_runtime_state (key, value, updated_at, updated_by)
                    VALUES (%s, '1', NOW(), %s)
                    ON CONFLICT (key) DO UPDATE
                    SET value = (kbl_runtime_state.value::int + 1)::text,
                        updated_at = NOW(),
                        updated_by = EXCLUDED.updated_by
                    RETURNING value
                    """,
                    (key, updated_by),
                )
                new_value = int(cur.fetchone()[0])
                conn.commit()
                return new_value
        except Exception:
            conn.rollback()
            raise
