"""Alerts → signal_queue bridge.

Reads new ``alerts`` rows since the bridge watermark, applies the
4-axis Director-co-designed filter (tier OR matter OR VIP OR
promote-type) plus a conservative noise stop-list, projects each kept
alert into a ``signal_queue`` row, and advances the watermark.

Pure DB → DB. Zero LLM calls. The downstream pipeline (Steps 1-7)
owns all enrichment/classification/Opus work.

Watermark source: ``alerts_to_signal_bridge`` (one row in
``trigger_watermarks``). On first run with no row, the cold-start floor
is ``NOW() - INTERVAL '2 hours'`` so we never backfill 5K+ historical
alerts into the empty queue.

Idempotency: every kept alert is INSERTed under a ``NOT EXISTS``
guard on ``signal_queue.payload->>'alert_source_id'`` (and
``alert_id`` as a secondary key for defense in depth) so a watermark
glitch can't double-bridge.

Atomic batch contract: all INSERTs + the watermark UPSERT commit in
one transaction. On any error mid-batch we rollback wholesale and let
APScheduler retry on the next tick — no half-advance.

See ``briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md`` for the full
design ratification.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from kbl.db import get_conn
from kbl.logging import emit_log

_local = logging.getLogger("kbl.bridge.alerts_to_signal")

WATERMARK_SOURCE = "alerts_to_signal_bridge"

# Cold-start floor: read at most 2h of history on the first tick.
COLD_START_LOOKBACK_HOURS = 2


# --------------------------------------------------------------------------
# Filter + stop-list — pure functions, unit-testable
# --------------------------------------------------------------------------

PROMOTE_TYPES = frozenset(
    [
        "commitment",
        "deadline",
        "appointment",
        "meeting",
        "tax-opinion",
        "tax-document",
        "financial-report",
        "financial-document",
        "legal-document",
        "dispute-update",
        "contract-change",
        "investor-communication",
        "vip-message",
        "travel-info",
    ]
)

# Lightweight title-keyword fallback for promote-type detection when
# tags are absent. Strict word-boundary tokens; informational only.
_PROMOTE_TITLE_TOKENS = (
    "commitment",
    "deadline",
    "appointment",
    "meeting",
    "tax",
    "drawdown",
    "contract",
    "court",
    "hearing",
    "filing",
)

STOPLIST_TITLE_PATTERNS = (
    r"\bcomplimentary\b",
    r"\bredeem\b",
    r"\b(?:sale|% off|% discount)\b",
    r"\bsotheby(?:'s)?\b",
    r"\bwill be available\b",
    r"\bMedal Engraving\b",
    r"\bpreview ends\b",
    r"\bHotel Express Deals\b",
    r"\bForbes Under 30\b",
    r"\bwine o'clock\b",
    r"\bTAKEITOUTSIDE\b",
)

# Compile once at import. ``_STOPLIST_RE.search(title)`` returns truthy on first match.
_STOPLIST_RE = re.compile("|".join(STOPLIST_TITLE_PATTERNS), flags=re.IGNORECASE)

# Auction is special-cased: a fixed-width lookbehind would be needed to express
# the brief's "auction unless Brisen anywhere in title" rule inside a single
# regex (Python re only supports fixed-width lookbehind). Splitting the check
# in two keeps the intent ("auction noise is generic; Brisen auctions are real
# Director commitments") faithful to the brief.
_AUCTION_RE = re.compile(r"\bauction\b", flags=re.IGNORECASE)
_BRISEN_RE = re.compile(r"\bbrisen\b", flags=re.IGNORECASE)

STOPLIST_SOURCES = frozenset(
    [
        "dropbox_batch",
        "cadence_tracker",
        "sentinel_health",
        "waha_silence",
        "waha_session",
    ]
)


def _is_stoplist_noise(alert: dict) -> bool:
    """Return True if the alert matches any stop-list rule.

    Source-based check first (cheaper and more decisive than regex).
    """
    if alert.get("source") in STOPLIST_SOURCES:
        return True
    title = alert.get("title") or ""
    if not title:
        return False
    if _STOPLIST_RE.search(title):
        return True
    if _AUCTION_RE.search(title) and not _BRISEN_RE.search(title):
        return True
    return False


def _has_promote_type(alert: dict) -> bool:
    """Promote-type allowlist match.

    Two channels:
      1. ``alert.tags`` (jsonb array): any tag in PROMOTE_TYPES = match.
      2. ``alert.structured_actions``: ``type`` field in PROMOTE_TYPES = match.

    Title-keyword fallback only fires when tags AND structured_actions
    are both absent — keeps the signal strict in the common case.
    """
    tags = alert.get("tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag in PROMOTE_TYPES:
                return True

    sa = alert.get("structured_actions")
    if isinstance(sa, str):
        try:
            sa = json.loads(sa)
        except (TypeError, ValueError):
            sa = None
    if isinstance(sa, dict):
        if sa.get("type") in PROMOTE_TYPES:
            return True
    elif isinstance(sa, list):
        for entry in sa:
            if isinstance(entry, dict) and entry.get("type") in PROMOTE_TYPES:
                return True

    if not tags and not sa:
        title = (alert.get("title") or "").lower()
        for token in _PROMOTE_TITLE_TOKENS:
            if re.search(rf"\b{re.escape(token)}\b", title):
                return True

    return False


def _passes_filter_axes(
    alert: dict, vip_ids: set[str], vip_emails: set[str]
) -> bool:
    """Return True if any of the 4 inclusive-OR axes match.

    1. Tier 1 or 2 (high-priority on the Baker classifier output).
    2. matter_slug populated (any active matter).
    3. contact_id resolves to a VIP (or sender email is a VIP email).
    4. tags / structured_actions / title match a promote-type.

    Stop-list is checked separately by callers. Keeping the two
    concerns split keeps the test matrix legible and lets callers
    distinguish ``skipped_filter`` from ``skipped_stoplist``.
    """
    tier = alert.get("tier")
    try:
        if tier is not None and int(tier) <= 2:
            return True
    except (TypeError, ValueError):
        pass

    if alert.get("matter_slug"):
        return True

    contact_id = alert.get("contact_id")
    if contact_id is not None and str(contact_id) in vip_ids:
        return True

    sender_email = alert.get("sender_email") or alert.get("from_email")
    if sender_email and sender_email.lower() in vip_emails:
        return True

    if _has_promote_type(alert):
        return True

    return False


def should_bridge(
    alert: dict, vip_ids: set[str], vip_emails: set[str]
) -> bool:
    """Composite gate: stop-list FIRST (overrides permissive axes), then 4-axis filter.

    Pure function — no DB, no clock. Suitable for unit-testing every
    axis in isolation.
    """
    if _is_stoplist_noise(alert):
        return False
    return _passes_filter_axes(alert, vip_ids, vip_emails)


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------

# Maps alert.tier (1/2/3/4) to a signal_queue.priority TEXT value that
# sorts correctly under ``ORDER BY priority DESC`` — i.e. tier 1 wins.
# Lex DESC: 'urgent' (u=117) > 'normal' (n=110) > 'low' (l=108).
# Stays compatible with the existing ``DEFAULT 'normal'`` for any
# legacy producers.
_TIER_TO_PRIORITY = {
    1: "urgent",
    2: "normal",
    3: "low",
    4: "low",
}


def _derive_signal_type(alert: dict) -> str:
    """Project an alert into a coarse signal_type label.

    Step 1 (triage) refines this. We keep it stable + deterministic so
    Layer 0 + Step 1 can route on it cleanly.
    """
    src = alert.get("source")
    if src:
        return f"alert:{src}"
    return "alert:unknown"


def map_alert_to_signal(alert: dict) -> dict:
    """Project an alerts row into the signal_queue row shape.

    Returned dict keys are exactly the columns we INSERT — no
    surprise NULLs against NOT NULL columns. All other signal_queue
    columns (triage_score, vedana, etc.) are filled by pipeline steps.
    """
    tier_raw = alert.get("tier")
    try:
        tier_int = int(tier_raw) if tier_raw is not None else 3
    except (TypeError, ValueError):
        tier_int = 3
    priority = _TIER_TO_PRIORITY.get(tier_int, "low")

    payload = {
        "alert_id": alert.get("id"),
        "alert_source_id": alert.get("source_id"),
        "alert_source": alert.get("source"),
        "alert_tier": tier_int,
        "alert_title": alert.get("title"),
        "alert_body": alert.get("body"),
        "alert_matter_slug": alert.get("matter_slug"),
        "alert_tags": alert.get("tags"),
        "alert_structured_actions": alert.get("structured_actions"),
        "alert_contact_id": (
            str(alert["contact_id"]) if alert.get("contact_id") is not None else None
        ),
        "alert_created_at": (
            alert["created_at"].isoformat()
            if hasattr(alert.get("created_at"), "isoformat")
            else alert.get("created_at")
        ),
    }

    return {
        "source": "legacy_alert",
        "signal_type": _derive_signal_type(alert),
        "matter": alert.get("matter_slug"),
        "primary_matter": alert.get("matter_slug"),
        "summary": alert.get("title"),
        "priority": priority,
        "status": "pending",
        "stage": "triage",
        "payload": payload,
    }


# --------------------------------------------------------------------------
# DB helpers
# --------------------------------------------------------------------------


def _get_watermark_or_cold_start(cur) -> Any:
    """Return the bridge watermark as a TIMESTAMPTZ, or NOW()-2h on cold start.

    SELECTs both branches inside a single round-trip via COALESCE so we
    never need a Python-side ``if row is None`` two-step.
    """
    cur.execute(
        """
        SELECT COALESCE(
            (SELECT last_seen FROM trigger_watermarks WHERE source = %s),
            NOW() - INTERVAL '%s hours'
        )
        """,
        (WATERMARK_SOURCE, COLD_START_LOOKBACK_HOURS),
    )
    return cur.fetchone()[0]


def _load_vip_sets(cur) -> tuple[set[str], set[str]]:
    """Snapshot VIP id + email sets for this tick's filter pass.

    Cheap query (≪1ms on Neon at our VIP scale) and the values are
    write-rare. Re-loading per tick keeps any new VIP added via
    ``baker_upsert_vip`` visible without restart.
    """
    cur.execute("SELECT id, LOWER(email) FROM vip_contacts")
    rows = cur.fetchall()
    vip_ids: set[str] = set()
    vip_emails: set[str] = set()
    for vid, email in rows:
        if vid is not None:
            vip_ids.add(str(vid))
        if email:
            vip_emails.add(email)
    return vip_ids, vip_emails


def _read_new_alerts(cur, watermark: Any, limit: int) -> list[dict]:
    """Pull alerts strictly newer than the watermark, ordered ascending."""
    cur.execute(
        """
        SELECT id, tier, title, body, matter_slug, source, source_id,
               tags, structured_actions, contact_id, created_at
        FROM alerts
        WHERE created_at > %s
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (watermark, limit),
    )
    cols = [
        "id", "tier", "title", "body", "matter_slug", "source", "source_id",
        "tags", "structured_actions", "contact_id", "created_at",
    ]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _insert_signal_if_new(cur, signal_row: dict) -> bool:
    """Insert one signal_queue row guarded by NOT EXISTS on alert_source_id+alert_id.

    Returns True if a row was inserted, False if a duplicate was
    detected. The dual-key check (source_id OR alert_id) is the
    belt-and-suspenders against watermark drift required by the brief.
    """
    payload_json = json.dumps(signal_row["payload"])
    alert_id = signal_row["payload"].get("alert_id")
    alert_source_id = signal_row["payload"].get("alert_source_id")

    cur.execute(
        """
        INSERT INTO signal_queue (
            source, signal_type, matter, primary_matter,
            summary, priority, status, stage, payload
        )
        SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb
        WHERE NOT EXISTS (
            SELECT 1 FROM signal_queue
            WHERE source = 'legacy_alert'
              AND (
                (payload->>'alert_id')::text = %s::text
                OR (
                    %s IS NOT NULL
                    AND payload->>'alert_source_id' = %s
                )
              )
        )
        RETURNING id
        """,
        (
            signal_row["source"],
            signal_row["signal_type"],
            signal_row["matter"],
            signal_row["primary_matter"],
            signal_row["summary"],
            signal_row["priority"],
            signal_row["status"],
            signal_row["stage"],
            payload_json,
            str(alert_id) if alert_id is not None else "",
            alert_source_id,
            alert_source_id,
        ),
    )
    return cur.fetchone() is not None


def _upsert_watermark(cur, last_seen: Any) -> None:
    cur.execute(
        """
        INSERT INTO trigger_watermarks (source, last_seen, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (source) DO UPDATE
          SET last_seen = EXCLUDED.last_seen, updated_at = NOW()
        """,
        (WATERMARK_SOURCE, last_seen),
    )


# --------------------------------------------------------------------------
# Tick entrypoint
# --------------------------------------------------------------------------


def run_bridge_tick(max_bridge_per_tick: int = 50) -> dict:
    """Read new alerts, filter, map, insert; advance watermark atomically.

    Returns a counts dict with keys:
        read              - alerts read since watermark
        kept              - alerts that passed both stop-list + 4-axis filter
        bridged           - rows actually INSERTed (idempotency may drop dups)
        skipped_filter    - failed all 4 axes (and not stop-listed)
        skipped_stoplist  - matched the stop-list
        errors            - 1 if the tick raised; 0 otherwise

    Single transaction. If anything in the batch raises, the whole
    tick rolls back (including the watermark) and APScheduler retries
    on the next tick — no half-advance.
    """
    counts = {
        "read": 0,
        "kept": 0,
        "bridged": 0,
        "skipped_filter": 0,
        "skipped_stoplist": 0,
        "errors": 0,
    }

    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    watermark = _get_watermark_or_cold_start(cur)
                    vip_ids, vip_emails = _load_vip_sets(cur)
                    alerts = _read_new_alerts(cur, watermark, max_bridge_per_tick)

                counts["read"] = len(alerts)
                if not alerts:
                    return counts

                max_created_at = watermark
                with conn.cursor() as cur:
                    for alert in alerts:
                        ts = alert.get("created_at")
                        if ts is not None and ts > max_created_at:
                            max_created_at = ts

                        if _is_stoplist_noise(alert):
                            counts["skipped_stoplist"] += 1
                            continue

                        if not _passes_filter_axes(alert, vip_ids, vip_emails):
                            counts["skipped_filter"] += 1
                            continue

                        counts["kept"] += 1
                        signal_row = map_alert_to_signal(alert)
                        if _insert_signal_if_new(cur, signal_row):
                            counts["bridged"] += 1

                    _upsert_watermark(cur, max_created_at)

                conn.commit()
            except Exception:
                conn.rollback()
                raise
    except Exception as e:
        counts["errors"] = 1
        emit_log(
            "ERROR",
            "alerts_to_signal_bridge",
            None,
            f"bridge tick failed: {e}",
        )
        raise
    finally:
        _local.info("bridge_tick: %s", counts)

    return counts
