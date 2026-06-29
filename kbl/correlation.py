"""Bus<->signal_queue thread-back identity primitive (CORRELATION_ID_PRIMITIVE_1).

Read-only. Mints a stable correlation token from ``signal_queue.id``, carries it
in the bus topic slug, parses a one-line structured check-in reply, and resolves
a signal id back to its row. No writes, no SLA/monitor, no scheduler — the future
Dispatcher/monitor consumes this; nothing calls it in prod yet.

Spec: cowork-ah1 bus #4623 + outputs/correlation-id-primitive-spec.md.
"""

from __future__ import annotations

import re

from kbl.db import get_conn

_SIG_RE = re.compile(r"sig-(\d+)")

_OUTCOMES = {
    "VALID",
    "FAKE",
    "DUPLICATE",
    "WRONG_TERMINAL",
    "NEEDS_LUGGAGE",
    "CHECK_IN_MISSED",
}


def corr_id(signal_id: int) -> str:
    """Mint the stable correlation token for a signal id: ``sig-<id>``."""
    return f"sig-{int(signal_id)}"


def parse_corr_id(text: str) -> int | None:
    """Extract the signal id from a topic or body. First ``sig-<digits>`` wins.

    Works on a topic (``checkin/<owner>/sig-123``) or a free body. Returns None
    for empty input, no token, or a non-numeric token (``sig-abc``).
    """
    if not text:
        return None
    m = _SIG_RE.search(text)
    return int(m.group(1)) if m else None


def checkin_topic(owner_slug: str, signal_id: int) -> str:
    """Build the check-in dispatch topic: ``checkin/<owner>/sig-<id>``."""
    return f"checkin/{owner_slug}/{corr_id(signal_id)}"


def checkin_reply_topic(owner_slug: str, signal_id: int) -> str:
    """Build the check-in reply topic: ``checkin-reply/<owner>/sig-<id>``."""
    return f"checkin-reply/{owner_slug}/{corr_id(signal_id)}"


def parse_checkin_verdict(body: str) -> dict | None:
    """Parse the first body line ``CHECK_IN_VERDICT v1 sig=<id> outcome=<X> by=<slug>``.

    Never raises. Returns None for empty/garbled/wrong-version/unknown-outcome/
    missing-key bodies; the caller treats None as UNKNOWN.
    """
    if not body:
        return None
    line = body.strip().splitlines()[0].strip()
    if not line.startswith("CHECK_IN_VERDICT v1"):
        return None
    kv = dict(re.findall(r"(\w+)=(\S+)", line))
    if "sig" not in kv or "by" not in kv:
        return None
    try:
        sig = int(kv["sig"])
    except ValueError:
        return None
    outcome = kv.get("outcome", "")
    if outcome not in _OUTCOMES:
        return None
    return {"sig": sig, "outcome": outcome, "by": kv["by"]}


def resolve_signal(signal_id: int) -> dict | None:
    """Read-only resolve of a signal id to ``{id, status, matter_slug}``.

    The only DB touch in this module. Never raises: any failure (connection,
    execute, missing row) returns None; ``rollback()`` runs on a query error.

    Column note: ``signal_queue`` has no ``matter_slug`` column. The matter is
    carried in ``primary_matter`` (the column prod code reads — see
    ``kbl/steps/step6_finalize.py``). We select ``primary_matter`` and expose it
    under the brief's documented ``matter_slug`` return key so the primitive's
    contract holds. (Spec source said ``matter_slug``; corrected here — flagged
    to lead.)
    """
    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, status, primary_matter FROM signal_queue "
                        "WHERE id=%s LIMIT 1",
                        (int(signal_id),),
                    )
                    row = cur.fetchone()
            except Exception:
                conn.rollback()
                return None
            if not row:
                return None
            return {"id": row[0], "status": row[1], "matter_slug": row[2]}
    except Exception:
        return None
