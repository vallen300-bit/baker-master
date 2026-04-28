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
from typing import Any, Optional

from kbl.db import get_conn
from kbl.logging import emit_log

_local = logging.getLogger("kbl.bridge.alerts_to_signal")

WATERMARK_SOURCE = "alerts_to_signal_bridge"

# Cold-start floor: read at most 2h of history on the first tick.
COLD_START_LOOKBACK_HOURS = 2

# BRIDGE_HOT_MD_AND_TUNING_1: Postgres advisory lock serializes concurrent
# ticks (APScheduler retries / multi-pod deploys) so the NOT EXISTS guard
# can't be raced. Stable hardcoded 64-bit int — mnemonic sibling of
# ``_MIGRATION_LOCK_KEY`` in config/migration_runner.py (0x42BA4E00001).
# Transaction-scoped form (``_xact_lock``) means the lock releases at the
# next COMMIT or ROLLBACK — no explicit unlock required.
_BRIDGE_ADVISORY_LOCK_KEY: int = 0x42BA4E00002

# BRIDGE_HOT_MD_AND_TUNING_1: Director-curated signals. Path is read via
# the vault mirror (Phase D MCP substrate), not a local disk path —
# vault_mirror ensures freshness (5-min pull) and scope safety.
HOT_MD_VAULT_PATH = "_ops/hot.md"
HOT_MD_MIN_PATTERN_LENGTH = 4


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
    # BRIDGE_HOT_MD_AND_TUNING_1: additions from Day 1 Batch #1 dismissals.
    # Each pattern is additive — the audit trail below lets a future brief
    # retire any line if the matter-tag classifier tunes away the mis-match.
    r"\bcigar\s+(?:market|news|review|lounge|industry)\b",  # Batch #1 #9: Austrian Tax mis-match
    r"\bluxury\s+cigar\b",                                  # Batch #1 #9: Austrian Tax mis-match
    r"\bphone\s+scam(?:s)?\b",                              # Batch #1 #10: Financing mis-match
    r"\bscam(?:s)?\b",                                       # Batch #1 #10: generic-scam copy
    r"\bfuel\s+(?:price|tax|duty)\b",                       # Batch #1 #5/#7: energy policy noise
    r"\benergy\s+policy\b",                                  # Batch #1 #7: Austrian Tax mis-match
    r"\bretail\s+market\s+update\b",                        # Batch #1 #6: German Property Tax mis-match
    r"\bretail[-\s]+chain\s+turnover\b",                    # Batch #1 #6: retail-chain copy
    r"\bTK\s*Maxx\b",                                        # Batch #1 #6: discount-retail mis-match
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


def load_hot_md_patterns() -> list[str]:
    """Read ``_ops/hot.md`` via the vault mirror; return parsed pattern list.

    Parse rules (brief §1):
      * lines starting with ``#`` → comment, ignored
      * blank lines → ignored
      * leading ``-`` or ``*`` bullet markers stripped
      * remaining text shorter than ``HOT_MD_MIN_PATTERN_LENGTH`` ignored
        (prevents ``"EU"`` matching every real-estate email)

    Any failure to read the mirror (missing file, import error, truncated
    oversize response) returns an empty list — the hot.md axis simply
    doesn't fire that tick and the other 4 axes carry on unchanged.
    Loud-fail is inappropriate here: a missing hot.md is a normal state
    (first-deploy before Director seeds it, or transient clone miss).
    """
    try:
        from vault_mirror import read_ops_file, VaultPathError
    except Exception as e:  # pragma: no cover - defensive
        _local.debug("hot.md: vault_mirror import failed: %s", e)
        return []

    try:
        record = read_ops_file(HOT_MD_VAULT_PATH)
    except VaultPathError:
        return []
    except Exception as e:
        _local.warning("hot.md: read_ops_file raised: %s", e)
        return []

    if record.get("error") or record.get("truncated"):
        return []

    content = record.get("content_utf8") or ""
    patterns: list[str] = []
    for raw in content.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Strip a single leading bullet marker (``-`` or ``*``) and any
        # whitespace that follows. Multi-byte/multi-char markers (e.g.
        # ``--``) are intentionally left alone to avoid silently eating
        # Director-typed content.
        if stripped[0] in ("-", "*"):
            stripped = stripped[1:].lstrip()
        if len(stripped) < HOT_MD_MIN_PATTERN_LENGTH:
            continue
        patterns.append(stripped)
    return patterns


def hot_md_match(alert: dict, patterns: list[str]) -> Optional[str]:
    """Return the first hot.md pattern that matches alert title+body, else None.

    Case-insensitive substring search. Patterns are checked in the order
    they appear in the file so Director's implicit weekly priority order
    is preserved in the attributed match (top-of-file wins a tie).
    """
    if not patterns:
        return None
    haystack = " ".join(
        [alert.get("title") or "", alert.get("body") or ""]
    ).lower()
    if not haystack.strip():
        return None
    for pattern in patterns:
        if len(pattern) < HOT_MD_MIN_PATTERN_LENGTH:
            continue
        if pattern.lower() in haystack:
            return pattern
    return None


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
    """Return True if any of the 5 inclusive-OR axes match.

    1. Tier 1 or 2 (high-priority on the Baker classifier output).
    2. matter_slug populated (any active matter).
    3. contact_id resolves to a VIP (or sender email is a VIP email).
    4. tags / structured_actions / title match a promote-type.
    5. hot.md match — Director-curated weekly priority (BRIDGE_HOT_MD_AND_TUNING_1).

    Axis 5 expects the caller (``run_bridge_tick``) to have pre-populated
    ``alert["hot_md_match"]`` with a hit or left it absent/None. Keeping
    the match computation outside this pure function lets the tick load
    hot.md patterns once per batch instead of once per alert.

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

    if alert.get("hot_md_match"):
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
        # BRIDGE_HOT_MD_AND_TUNING_1: Director-curated axis-5 attribution.
        # NULL when another axis fired; the matched line verbatim otherwise.
        "hot_md_match": alert.get("hot_md_match"),
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


def _insert_signal_if_new(cur, signal_row: dict):
    """Insert one signal_queue row guarded by NOT EXISTS on alert_source_id+alert_id.

    Returns the inserted ``signal_queue.id`` (int) on success, or ``None``
    when the dedup guard suppressed a duplicate. The dual-key check
    (source_id OR alert_id) is the belt-and-suspenders against watermark
    drift required by the brief.

    Return-shape change (CORTEX_3T_FORMALIZE_1C Amendment A2): callers
    used to receive a bool; we now propagate the row id so the post-
    commit Cortex dispatcher can address the inserted signal directly.
    Truthy semantics are preserved (None is falsy, int>=1 is truthy).
    """
    payload_json = json.dumps(signal_row["payload"])
    alert_id = signal_row["payload"].get("alert_id")
    alert_source_id = signal_row["payload"].get("alert_source_id")

    cur.execute(
        """
        INSERT INTO signal_queue (
            source, signal_type, matter, primary_matter,
            summary, priority, status, stage, payload, hot_md_match
        )
        SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s
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
            signal_row.get("hot_md_match"),
            str(alert_id) if alert_id is not None else "",
            alert_source_id,
            alert_source_id,
        ),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row[0]


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


def _dispatch_cortex_for_inserted(inserted: list) -> None:
    """Fire ``triggers.cortex_pipeline.maybe_dispatch`` for every row that
    landed in ``signal_queue`` this tick.

    CORTEX_3T_FORMALIZE_1C Amendment A2: env-flag-gated by
    ``CORTEX_PIPELINE_ENABLED`` (default off). The dispatch call MUST
    never propagate an exception back to the bridge tick — the bridge
    write is canonical, Cortex is best-effort. Wrapped in try/except
    individually per signal so a poison signal doesn't starve siblings.
    """
    if not inserted:
        return
    try:
        from triggers.cortex_pipeline import maybe_dispatch
    except Exception as e:
        _local.warning("cortex_pipeline import failed: %s", e)
        return
    for signal_id, matter_slug in inserted:
        try:
            maybe_dispatch(signal_id=signal_id, matter_slug=matter_slug)
        except Exception as e:
            _local.warning(
                "cortex maybe_dispatch raised for signal_id=%s matter=%s: %s",
                signal_id, matter_slug, e,
            )


def run_bridge_tick(max_bridge_per_tick: int = 50) -> dict:
    """Read new alerts, filter, map, insert; advance watermark atomically.

    Returns a counts dict with keys:
        read              - alerts read since watermark
        kept              - alerts that passed both stop-list + 5-axis filter
        bridged           - rows actually INSERTed (idempotency may drop dups)
        skipped_filter    - failed all 5 axes (and not stop-listed)
        skipped_stoplist  - matched the stop-list
        errors            - 1 if the tick raised; 0 otherwise
        skipped_locked    - lock held by sibling tick; no-op (BRIDGE_HOT_MD_AND_TUNING_1)

    Single transaction. If anything in the batch raises, the whole
    tick rolls back (including the watermark) and APScheduler retries
    on the next tick — no half-advance.

    BRIDGE_HOT_MD_AND_TUNING_1: wrapped in a Postgres transaction-scoped
    advisory lock. Two ticks firing 625ms apart previously both read the
    same alert + both passed NOT EXISTS + both inserted (Batch #1 dup).
    ``pg_try_advisory_xact_lock`` is non-blocking: the second caller
    receives ``False``, rolls back its (empty) transaction, and no-ops.
    Lock releases automatically at COMMIT/ROLLBACK — no manual unlock.
    """
    counts = {
        "read": 0,
        "kept": 0,
        "bridged": 0,
        "skipped_filter": 0,
        "skipped_stoplist": 0,
        "errors": 0,
        "skipped_locked": 0,
    }

    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_try_advisory_xact_lock(%s)",
                        (_BRIDGE_ADVISORY_LOCK_KEY,),
                    )
                    row = cur.fetchone()
                    lock_acquired = bool(row and row[0])

                if not lock_acquired:
                    # Sibling tick in-flight. Roll back our empty txn so
                    # the lock-contention attempt doesn't linger, and
                    # skip cleanly. APScheduler's next tick retries.
                    conn.rollback()
                    counts["skipped_locked"] = 1
                    _local.info(
                        "bridge_tick: advisory lock held by sibling tick; skipping"
                    )
                    return counts

                with conn.cursor() as cur:
                    watermark = _get_watermark_or_cold_start(cur)
                    vip_ids, vip_emails = _load_vip_sets(cur)
                    alerts = _read_new_alerts(cur, watermark, max_bridge_per_tick)

                counts["read"] = len(alerts)
                if not alerts:
                    # Still commit so the xact-scoped lock is released
                    # (rather than relying on conn close). Cheap no-op.
                    conn.commit()
                    return counts

                # Loaded once per batch — not once per alert. A hot.md edit
                # mid-tick is visible on the next tick (<=60 s), which
                # matches the brief's "5 min freshness" guarantee plus
                # the scheduler cadence floor.
                hot_md_patterns = load_hot_md_patterns()

                max_created_at = watermark
                # CORTEX_3T_FORMALIZE_1C Amendment A2: collect (signal_id,
                # matter_slug) for every signal_queue INSERT so that, AFTER
                # the transaction commits, we can fire the Cortex dispatcher
                # per row. Dispatch lives outside the transaction so that
                # any cortex_pipeline failure cannot roll back the bridge
                # write — Cortex is downstream/best-effort, signal_queue is
                # upstream/canonical.
                inserted_signals: list[tuple[int, Any]] = []
                with conn.cursor() as cur:
                    for alert in alerts:
                        ts = alert.get("created_at")
                        if ts is not None and ts > max_created_at:
                            max_created_at = ts

                        if _is_stoplist_noise(alert):
                            counts["skipped_stoplist"] += 1
                            continue

                        alert["hot_md_match"] = hot_md_match(
                            alert, hot_md_patterns
                        )

                        if not _passes_filter_axes(alert, vip_ids, vip_emails):
                            counts["skipped_filter"] += 1
                            continue

                        counts["kept"] += 1
                        signal_row = map_alert_to_signal(alert)
                        inserted_id = _insert_signal_if_new(cur, signal_row)
                        if inserted_id is not None:
                            counts["bridged"] += 1
                            inserted_signals.append(
                                (inserted_id, signal_row.get("matter")),
                            )

                    _upsert_watermark(cur, max_created_at)

                conn.commit()
                # Post-commit Cortex dispatch (Amendment A2). Failures here
                # MUST NOT affect the just-committed bridge write — wrapped
                # in try/except + env-flag-gated.
                _dispatch_cortex_for_inserted(inserted_signals)
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
