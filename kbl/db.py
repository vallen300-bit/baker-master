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

import psycopg2


@contextmanager
def get_conn():
    """Yield a psycopg2 connection; close on exit.

    psycopg2's own connection __exit__ commits or rolls back the
    in-flight transaction — but does NOT close the connection; the
    contextmanager's finally does that explicitly.
    """
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
    finally:
        conn.close()
