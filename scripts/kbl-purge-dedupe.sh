#!/bin/bash
# kbl-purge-dedupe.sh — nightly 03:15 Europe/Vienna cleanup.
# 1) Prune kbl_alert_dedupe rows older than 7 days (retention target: 14).
# 2) Reset cost_circuit_open at UTC midnight via daily_cost_circuit_clear().

set -euo pipefail

REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
LOG="/var/log/kbl/purge.log"

mkdir -p "$(dirname "${LOG}")" 2>/dev/null || true

# B2.B1: launchd does NOT source ~/.zshrc — load secrets explicitly.
[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"

cd "${REPO}"
python3 - <<'PY' >> "${LOG}" 2>&1
from kbl.cost import daily_cost_circuit_clear
from kbl.db import get_conn

with get_conn() as conn:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kbl_alert_dedupe WHERE last_sent < NOW() - INTERVAL '7 days'"
            )
            conn.commit()
    except Exception:
        conn.rollback()
        raise

daily_cost_circuit_clear()
PY
