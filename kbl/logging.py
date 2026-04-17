"""Tiered logging for KBL: local rotating file (stdlib) + PG (WARN+).

Phase 4 (this commit) is the minimal shape: stdlib logger configured with
a FileHandler under /var/log/kbl/, and emit_log() writing WARN+ rows to
kbl_log. Phase 8 extends with:
  - CRITICAL WhatsApp alert dedupe via kbl_alert_dedupe
  - `python3 -m kbl.logging <level> <component> <message>` argv dispatcher
    so the shell wrappers can escalate without importing psycopg2
  - heartbeat / vault-size telemetry helpers
"""

from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any, Optional

from kbl.db import get_conn

_VALID_LEVELS = {"WARN", "ERROR", "CRITICAL"}

# R1.B5: a missing /var/log/kbl (fresh install, not-yet-sudoed) must not
# crash module import. Fall back to a stderr StreamHandler so pipeline
# progress is still visible.
_stdlib = logging.getLogger("kbl")
if not _stdlib.handlers:
    _stdlib.setLevel(logging.INFO)
    _log_dir = os.environ.get("KBL_LOG_DIR", "/var/log/kbl")
    _log_path = os.path.join(_log_dir, "kbl.log")
    try:
        os.makedirs(_log_dir, exist_ok=True)
        _handler: logging.Handler = RotatingFileHandler(
            _log_path, maxBytes=10 * 1024 * 1024, backupCount=5
        )
    except Exception as e:
        _handler = logging.StreamHandler(sys.stderr)
        sys.stderr.write(f"[kbl.logging] FileHandler unavailable ({e}); using stderr\n")
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
    """Route a WARN+ event to PostgreSQL kbl_log and mirror to the local file.

    level must be one of {'WARN','ERROR','CRITICAL'} — INFO-level telemetry
    belongs in the stdlib logger directly (see §12 / R1.S2 invariant).
    """
    if level not in _VALID_LEVELS:
        _stdlib.warning(
            "emit_log called with invalid level %r (component=%s msg=%s) — routing to stdlib only",
            level,
            component,
            message,
        )
        _stdlib.log(logging.INFO, "[%s] %s", component, message)
        return

    # Mirror to local file (structured line for grep)
    _stdlib.log(
        getattr(logging, level, logging.WARNING),
        "[%s] signal_id=%s %s %s",
        component,
        signal_id,
        message,
        json.dumps(metadata, default=str) if metadata else "",
    )

    # Fault-tolerant PG write — logging must never be the thing that
    # breaks the pipeline tick.
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
