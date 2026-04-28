"""Cortex matter-config drift audit (CORTEX_3T_FORMALIZE_1C, RA-23 Q6).

Walks ``$BAKER_VAULT_PATH/wiki/matters/*/cortex-config.md`` and flags any
file whose mtime is older than ``DRIFT_THRESHOLD_DAYS`` (default 30).

Mirror of the ``ai_head_weekly_audit`` pattern — non-fatal, logs only,
returns a dict counts the scheduler wrapper logs.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DRIFT_THRESHOLD_DAYS = int(os.environ.get("CORTEX_DRIFT_THRESHOLD_DAYS", "30"))
SECONDS_PER_DAY = 86_400


def _vault_root() -> Optional[Path]:
    raw = os.environ.get("BAKER_VAULT_PATH")
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_dir() else None


def run_drift_audit(vault_root: Optional[Path] = None) -> dict:
    """Scan cortex-config files; return counts dict.

    Returns:
        {"ok": bool, "checked": int, "flagged_count": int,
         "flagged": [{"slug", "age_days"}], "skipped": "..."}
    """
    root = vault_root or _vault_root()
    if root is None:
        logger.warning(
            "cortex_drift_audit: BAKER_VAULT_PATH unset or missing — skipping"
        )
        return {"ok": False, "skipped": "BAKER_VAULT_PATH unset", "flagged_count": 0}
    matters_dir = root / "wiki" / "matters"
    if not matters_dir.is_dir():
        return {"ok": False, "skipped": f"missing {matters_dir}", "flagged_count": 0}
    threshold = time.time() - (DRIFT_THRESHOLD_DAYS * SECONDS_PER_DAY)
    flagged: list[dict] = []
    checked = 0
    for slug_dir in sorted(matters_dir.iterdir()):
        if not slug_dir.is_dir():
            continue
        cfg = slug_dir / "cortex-config.md"
        if not cfg.is_file():
            continue
        checked += 1
        try:
            mtime = cfg.stat().st_mtime
        except OSError as e:
            logger.warning("cortex_drift_audit: stat failed %s: %s", cfg, e)
            continue
        if mtime < threshold:
            age_days = int((time.time() - mtime) / SECONDS_PER_DAY)
            flagged.append({"slug": slug_dir.name, "age_days": age_days})
    if flagged:
        logger.warning(
            "cortex_drift_audit: %d configs >%dd old: %s",
            len(flagged), DRIFT_THRESHOLD_DAYS,
            ", ".join(f"{f['slug']}({f['age_days']}d)" for f in flagged),
        )
    return {
        "ok": True,
        "checked": checked,
        "flagged_count": len(flagged),
        "flagged": flagged,
        "threshold_days": DRIFT_THRESHOLD_DAYS,
    }
