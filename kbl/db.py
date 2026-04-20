"""Short-lived PG connection helper for KBL modules.

Per R2.NEW-B1: bypasses SentinelStoreBack (which lacks a public .conn
attribute, drags in Qdrant/Voyage bootstrap, and uses a pool that
requires manual putconn). KBL's Mac Mini usage pattern is ~one
connection per cron tick and Neon's server-side pool handles Render's
concurrent access, so a direct short-lived connection is the simplest
correct shape.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from urllib.parse import quote_plus

import psycopg2


def _build_dsn() -> str:
    """Return a psycopg2 DSN from either DATABASE_URL or POSTGRES_* split env.

    Precedence: DATABASE_URL wins when set. Otherwise compose from the split
    form used by `config/settings.py` and Mac Mini's ~/.kbl.env. Covers the
    env-convention drift lesson #36 (PR #19 hotfix).
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    required = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"neither DATABASE_URL nor POSTGRES_* fallback available; missing: {missing}"
        )
    host = os.environ["POSTGRES_HOST"]
    user = quote_plus(os.environ["POSTGRES_USER"])
    pw = quote_plus(os.environ["POSTGRES_PASSWORD"])
    db = os.environ["POSTGRES_DB"]
    port = os.environ.get("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{pw}@{host}:{port}/{db}"


@contextmanager
def get_conn():
    """Yield a psycopg2 connection; close on exit.

    psycopg2's own connection __exit__ commits or rolls back the
    in-flight transaction — but does NOT close the connection; the
    contextmanager's finally does that explicitly.
    """
    conn = psycopg2.connect(_build_dsn())
    try:
        yield conn
    finally:
        conn.close()
