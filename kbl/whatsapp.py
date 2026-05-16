"""Thin KBL → WhatsApp wrapper (R1.S1).

Wraps the existing WAHA sender (outputs/whatsapp_sender.py — canonical
Baker send path) with a KBL-branded `send_director_alert(message)`
convenience. No new HTTP, no reimplementation — just a prefix + reuse.

Note: the underlying `send_whatsapp()` has a Director-directed filter
that drops strings containing 'cost alert', 'budget exceeded', 'daily
spend', 'circuit breaker'. KBL CRITICAL wording is intentionally chosen
not to trip those keywords (e.g., "Anthropic circuit opened",
"KBL cost cap reached"). If that ever collides, escalate — don't
silently route around.
"""

from __future__ import annotations

import logging as _stdlib_logging

_local = _stdlib_logging.getLogger("kbl")


def send_director_alert(message: str, kind: str | None = None) -> bool:
    """Send a CRITICAL-level alert to the Director over WhatsApp.
    Returns True on success; False on any failure (the caller should
    already have logged locally before calling this).

    `kind` is passed through to the underlying chokepoint
    (BAKER_WA_DIRECTOR_FILTER_1). KBL CRITICAL alerts (Anthropic circuit
    open, KBL cost cap reached) should pass `kind='kbl_critical'` — these
    are Director-actionable and dedupe-bucketed upstream in
    `kbl.logging.emit_critical_alert`. Generic infra noise (anything
    NOT on the allowlist) leaves `kind` as None — the chokepoint blocks +
    audits to baker_actions, restoring signal-to-noise on Director's
    primary alert channel."""
    try:
        from outputs.whatsapp_sender import send_whatsapp, DIRECTOR_WHATSAPP

        return send_whatsapp(message, chat_id=DIRECTOR_WHATSAPP, kind=kind)
    except Exception as e:
        _local.warning("[kbl.whatsapp] send_director_alert failed: %s", e)
        return False
