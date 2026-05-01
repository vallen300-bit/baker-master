#!/usr/bin/env python3
"""Refresh ``migrations/applied_migrations.lock`` from prod ``schema_migrations``.

Run AFTER a new migration is applied to prod (Render boot picks up the file,
inserts the row, then this script captures the new authoritative row).

Usage:
    DATABASE_URL=$PROD_URL python3 scripts/refresh_applied_migrations_lock.py

The lock file is the only source of truth the pre-commit hook + start.sh
pre-flight consult; any divergence between disk and prod-applied sha256
fails CI/local commits unless explicitly authorized.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

LOCK_PATH = Path("migrations/applied_migrations.lock")

HEADER = """\
# Baker applied_migrations.lock — sha256 snapshot of prod-applied migrations.
# DO NOT edit by hand. Refresh after applying a new migration to prod with:
#   DATABASE_URL=$PROD_URL python3 scripts/refresh_applied_migrations_lock.py
# Format: <sha256>  <filename>   (compatible with `shasum -a 256 -c`)
"""


def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[refresh_applied_migrations_lock] DATABASE_URL is required", file=sys.stderr)
        return 1

    try:
        import psycopg2  # local import so the script is import-safe even if deps missing
    except ImportError:
        print(
            "[refresh_applied_migrations_lock] psycopg2 not installed; "
            "run inside the project venv (pip install -r requirements.txt)",
            file=sys.stderr,
        )
        return 1

    try:
        conn = psycopg2.connect(url)
    except Exception as e:
        print(f"[refresh_applied_migrations_lock] DB connect failed: {e}", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT filename, sha256 FROM schema_migrations ORDER BY filename"
            )
            rows = cur.fetchall()
    except Exception as e:
        print(
            f"[refresh_applied_migrations_lock] schema_migrations query failed: {e}",
            file=sys.stderr,
        )
        conn.close()
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if not rows:
        print(
            "[refresh_applied_migrations_lock] schema_migrations is empty — "
            "refusing to overwrite lock with zero entries",
            file=sys.stderr,
        )
        return 1

    if not LOCK_PATH.parent.is_dir():
        print(
            f"[refresh_applied_migrations_lock] {LOCK_PATH.parent} is not a directory; "
            "are you running from repo root?",
            file=sys.stderr,
        )
        return 1

    body_lines = [f"{sha}  {filename}\n" for filename, sha in rows]
    tmp_path = LOCK_PATH.with_suffix(LOCK_PATH.suffix + ".tmp")
    tmp_path.write_text(HEADER + "".join(body_lines))
    os.replace(tmp_path, LOCK_PATH)
    print(
        f"[refresh_applied_migrations_lock] wrote {len(rows)} entries to {LOCK_PATH}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
