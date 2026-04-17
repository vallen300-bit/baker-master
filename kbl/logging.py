"""Tiered logging for KBL.

Local rotating file (DEBUG+, stdlib RotatingFileHandler) + PostgreSQL
kbl_log (WARN+ only, per R1.S2/S12) + WhatsApp CRITICAL alert with
5-min-bucket dedupe via kbl_alert_dedupe (D15).

R1.B5: FileHandler creation at import must not crash when /var/log/kbl
is missing (fresh install, not-yet-sudoed). Falls back to stderr.

R1.S2 invariant: INFO never routes to PG. The kbl_log CHECK constraint
also forbids it at schema level. emit_log rejects INFO and routes to
the stdlib logger only so callers can safely use INFO constants without
crashing on a CHECK violation.

R1.B3: `python3 -m kbl.logging <subcmd> <component> <message...>` argv
dispatcher so shell wrappers can escalate without importing psycopg2.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from kbl.db import get_conn

_VALID_LEVELS = {"WARN", "ERROR", "CRITICAL"}
DEDUPE_BUCKET_MINUTES = 5

# --- stdlib logger (local file; fallback to stderr on fresh install) -----

_stdlib = logging.getLogger("kbl")
if not _stdlib.handlers:
    _stdlib.setLevel(logging.INFO)
    _log_dir = os.environ.get("KBL_LOG_DIR", "/var/log/kbl")
    _log_path = os.path.join(_log_dir, "kbl.log")
    _handler: logging.Handler
    try:
        os.makedirs(_log_dir, exist_ok=True)
        _handler = RotatingFileHandler(
            _log_path, maxBytes=10 * 1024 * 1024, backupCount=5
        )
    except Exception as e:
        _handler = logging.StreamHandler(sys.stderr)
        sys.stderr.write(
            f"[kbl.logging] FileHandler unavailable ({e}); using stderr\n"
        )
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _stdlib.addHandler(_handler)


def emit_log(
    level: str,
    component: str,
    signal_id: Optional[int],
    message: str,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Tiered emission.

    WARN/ERROR/CRITICAL → local file + PG kbl_log.
    CRITICAL → additionally WhatsApp alert with 5-min dedupe.
    Anything else → stdlib local logger only (enforces R1.S2 invariant).
    """
    if level not in _VALID_LEVELS:
        # Quietly route to local file at INFO — keeps caller simple.
        _stdlib.info("[%s] signal_id=%s %s", component, signal_id, message)
        return

    _stdlib.log(
        getattr(logging, level, logging.WARNING),
        "[%s] signal_id=%s %s %s",
        component,
        signal_id,
        message,
        json.dumps(metadata, default=str) if metadata else "",
    )

    # PG write — fault-tolerant (logging must never be what breaks a tick).
    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO kbl_log (level, component, signal_id, message, metadata)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                        """,
                        (
                            level,
                            component,
                            signal_id,
                            message,
                            json.dumps(metadata, default=str) if metadata else None,
                        ),
                    )
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
    except Exception as e:
        sys.stderr.write(f"[kbl.logging] PG kbl_log insert failed: {e}\n")

    if level == "CRITICAL":
        emit_critical_alert(component, message)


def emit_critical_alert(
    component: str,
    message: str,
    bucket_minutes: int = DEDUPE_BUCKET_MINUTES,
) -> None:
    """Send CRITICAL to Director WhatsApp with 5-min bucket dedupe.

    Dedupe key: `<component>_<sha256(message)[:16]>_<5min-bucket>`. The
    UPSERT RETURNING (xmax = 0) trick reports whether the row is newly
    inserted (fire alert) or already existed (increment count only).
    """
    bucket = int(time.time() // (bucket_minutes * 60))
    msg_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
    alert_key = f"{component}_{msg_hash}_{bucket}"

    was_inserted = False
    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO kbl_alert_dedupe (alert_key) VALUES (%s)
                        ON CONFLICT (alert_key) DO UPDATE SET
                            send_count = kbl_alert_dedupe.send_count + 1,
                            last_sent = NOW()
                        RETURNING (xmax = 0) AS was_inserted
                        """,
                        (alert_key,),
                    )
                    was_inserted = bool(cur.fetchone()[0])
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
    except Exception as e:
        sys.stderr.write(f"[kbl.logging] kbl_alert_dedupe write failed: {e}\n")
        # Best-effort: without dedupe we'd risk spamming, so DON'T send in the
        # failure branch. The local file still has the CRITICAL for audit.
        return

    if was_inserted:
        try:
            from kbl.whatsapp import send_director_alert

            send_director_alert(f"[KBL CRITICAL] {component}: {message}")
        except Exception as e:
            sys.stderr.write(f"[kbl.logging] WhatsApp alert failed: {e}\n")


# --- argv dispatcher for shell wrappers (R1.B3) --------------------------

_LEVEL_MAP = {
    "emit_critical": "CRITICAL",
    "emit_error": "ERROR",
    "emit_warn": "WARN",
    # INFO not valid for PG; shim bumps to WARN so operators see it.
    "emit_info": "WARN",
}


def _cli() -> int:
    if len(sys.argv) < 4:
        sys.stderr.write(
            "usage: python3 -m kbl.logging {emit_critical|emit_error|emit_warn|emit_info} "
            "<component> <message>\n"
        )
        return 2
    cmd = sys.argv[1]
    component = sys.argv[2]
    message = " ".join(sys.argv[3:])
    level = _LEVEL_MAP.get(cmd)
    if level is None:
        sys.stderr.write(f"[kbl.logging] unknown subcommand: {cmd}\n")
        return 2
    emit_log(level, component, None, message)
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
