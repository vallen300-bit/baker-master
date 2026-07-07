"""Airport Ticketing Bridge.

Turns raw Sentinel arrivals into candidate AIRPORT_TICKET records and wakes the
owning desk for check-in. The bridge is deliberately non-substantive: it routes
source-grounded tickets, but it does not decide legal, finance, CP, or nudge
outcomes.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from orchestrator.dispatcher import RESERVED_RECIPIENTS, resolve_owner_slug
from kbl.db import get_conn
from kbl.project_registry_store import (
    active_participant_values,
    desk_owner_for_matter,
    extract_project_codes,
    resolve_by_participant,
    resolve_project_number,
)

logger = logging.getLogger("sentinel.airport_ticketing")

# THREAD_CONTINUITY_ROUTING_1 — code-bound terminal_reason prefixes. These are the
# ONLY prior dispositions the thread-continuity lane may inherit from: an explicit
# registered ACTIVE project code drove each of them. Anything else (a soft / alias /
# participant-only match, or the (f) safe-default desk ticket) is deliberately
# excluded so continuity can never launder a weak match forward. The (e.5)/(e.7)
# writes build their reason from these prefixes, and resolve_by_thread filters on the
# same two prefixes, so the coupling is a single greppable pair — never a magic string.
_HARD_LANE_REASON_PREFIX = "hard_lane_project_code_participant_bound:"   # (e.5) FAST_TICKET
_CODE_ROUTED_REASON_PREFIX = "explicit_code_routed_ticket:"             # (e.7) routed TICKET
# The thread-continuity lane's OWN reason. Deliberately NOT in the inheritable set
# above: a thread-routed ticket is itself an inheritance, and the original code-bound
# ticket always remains on the thread for later replies, so re-inheriting a
# thread-routed row would only add transitive drift with no recall gain.
_THREAD_CONTINUITY_REASON_PREFIX = "thread_continuity_routed_ticket:"

_ENABLED_ENV = "AIRPORT_TICKETING_BRIDGE_ENABLED"
_KEYWORDS_ENV = "AIRPORT_TICKETING_KEYWORDS"
_DESK_ENV = "AIRPORT_TICKETING_DESK"
_MATTER_ENV = "AIRPORT_TICKETING_MATTER_SLUG"
_FLIGHT_ENV = "AIRPORT_TICKETING_FLIGHT"
_LOOKBACK_HOURS_ENV = "AIRPORT_TICKETING_LOOKBACK_HOURS"
_MAX_POSTS_ENV = "AIRPORT_TICKETING_MAX_POSTS_PER_TICK"
_BUS_URL_ENV = "AIRPORT_TICKETING_BUS_URL"
_KEY_ENV = "AIRPORT_TICKETING_TERMINAL_KEY"
_DEFAULT_BUS_URL = "https://brisen-lab.onrender.com"
_DEFAULT_KEYWORDS = ("aukera", "annaberg", "lilienmatt")
_DEFAULT_DESK = "baden-baden-desk"
_DEFAULT_MATTER = "lilienmatt"
_DEFAULT_FLIGHT = "aukera-annaberg-financing"
_DEFAULT_LOOKBACK_HOURS = 48
_DEFAULT_MAX_POSTS = 5

# BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — phase-1 non-mail source lanes (Plaud + WhatsApp).
# The email lane tickets email only; Plaud transcripts + WhatsApp messages already in the
# store never board a flight. These two lanes fetch them into the SAME airport_tickets
# spine (source_channel already includes 'plaud'/'whatsapp' + dedup_key UNIQUE). Ships
# DARK behind AIRPORT_NONMAIL_SOURCES_ENABLED (default OFF): run_tick calls the new
# fetchers ONLY when true, so a merge is a pure no-op until the flag flips. Rule 11c
# preview-first: AIRPORT_NONMAIL_DRY_RUN logs would-be tickets WITHOUT inserting (and does
# NOT advance the per-source watermark, so the preview re-shows until the real run).
# News/RSS/X/Substack = phase 2, Director-gated — ZERO code here.
_NONMAIL_ENABLED_ENV = "AIRPORT_NONMAIL_SOURCES_ENABLED"
_NONMAIL_DRY_RUN_ENV = "AIRPORT_NONMAIL_DRY_RUN"
# Per-source watermark keys — DISTINCT from the email cursor + from each other so no lane
# can advance another's cursor.
_WATERMARK_SOURCE_PLAUD = "airport_ticketing:plaud"
_WATERMARK_SOURCE_WHATSAPP = "airport_ticketing:whatsapp"
# Non-mail lookback FLOOR. Brief: watermark starts at flag-enable minus 7 days (OOM lesson
# — no full-history backfill on startup). Configurable; a blank cursor starts at this floor.
_NONMAIL_LOOKBACK_HOURS_ENV = "AIRPORT_NONMAIL_LOOKBACK_HOURS"
_DEFAULT_NONMAIL_LOOKBACK_HOURS = 168  # 7 days

# BOX5_DROP_OBSERVABILITY_1 (G3 rework #4957) — Gate-2 miss-fetch cap. Observability is
# TWO DECOUPLED queries: an UNCHANGED keyword-ILIKE match fetch decides what tickets
# (byte-for-byte parity), and a SEPARATE, independently-bounded query fetches the recent
# NON-matching set for drop-logging ONLY. This cap bounds that miss fetch ALONE; it can
# NEVER affect the ticketed set. The earlier single-superset-under-a-cap approach was
# G3-rejected for exactly that failure mode: a row cap on the un-prefiltered fetch could
# starve real keyword matches behind older non-matches and thereby change what tickets.
# When the miss fetch hits the cap the tick logs it (never a silent cut).
_MISS_FETCH_CAP_ENV = "AIRPORT_TICKETING_MISS_FETCH_CAP"
_DEFAULT_MISS_FETCH_CAP = 500

# BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 — a SECOND, DECOUPLED fetch lane keyed on sender
# identity in the project registry (channel=email), unioned into the ticketed set. It
# widens Gate-2 reachability beyond the keyword ILIKE: a matter email from a KNOWN
# registered participant with NO keyword on a brand-new (unbound) thread is fetched (and
# safe-default TICKETed) instead of only drop-logged as a keyword-prefilter miss. Dark by
# default: flag OFF -> the lane is a pure no-op and fetch_email_arrivals is byte-identical
# to the keyword-only match fetch (AC6). The cap bounds this lane ALONE (the allow-set is
# already tiny — registered email participants, ~a dozen today) and, like the miss cap,
# can NEVER affect the keyword match set (two decoupled queries).
_PARTICIPANT_LANE_ENV = "BOX5_PARTICIPANT_FETCH_LANE_ENABLED"
_PARTICIPANT_FETCH_CAP_ENV = "AIRPORT_TICKETING_PARTICIPANT_FETCH_CAP"
_DEFAULT_PARTICIPANT_FETCH_CAP = 200

# DATA_OPS_AO_PLAUD_BACKFILL_WA_NOISE_1 task 6 (lead #6200/#6619, Director #6209) — WA
# identity-only ticket suppression. A WhatsApp arrival fetched ONLY on registered-
# participant identity (participant_matched, NO active-keyword hit) carries no matter
# signal: every WA sender is a real contact the Director talks to, so identity alone
# floods the flight with ack/chatter tickets ("call later" / "Ок" / "1.30"). This knob
# suppresses MINTING such tickets — the underlying whatsapp_messages row is never touched
# (store-everything: the message stays searchable + classifiable to its correct matter),
# and keyword/matter matches STILL ticket to the correct desk regardless of this knob.
# Semantics of AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS:
#   0  (default) -> suppress ALL identity-only WA tickets regardless of age (#6619 shape).
#   N>0          -> suppress identity-only WA older than N hours (age-ceiling, #6200).
#   <0           -> DISABLED: legacy behavior, identity-only always tickets (escape hatch).
# Suppressed arrivals ADVANCE the watermark (they are intentionally handled, not held) so
# they are never re-fetched/re-ticketed next tick — distinct from a build_fn None, which
# means desk-misconfig and holds the cursor.
_WA_IDENTITY_TICKET_MAX_AGE_ENV = "AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS"
_DEFAULT_WA_IDENTITY_TICKET_MAX_AGE_HOURS = 0

# BOX5_DROP_OBSERVABILITY_1 — drop-log gate vocabulary (mirrors the CHECK in
# migrations/20260701d_box5_dropped_signals.sql). keyword_prefilter = Gate-2 miss (not
# ticketed); routing_unrouted / routing_conflict = Gate-3 (ticketed to safe-default
# desk review but not confidently auto-routed); other = reserved.
_GATE_KEYWORD_PREFILTER = "keyword_prefilter"
_GATE_ROUTING_UNROUTED = "routing_unrouted"
_GATE_ROUTING_CONFLICT = "routing_conflict"
_DROP_LOG_SAVEPOINT = "airport_drop_log"

_SKIP_EMAIL_SENDER_PATTERNS = (
    "noreply@",
    "no-reply@",
    "notifications@",
    "notification@",
    "@clickup.com",
    "@todoist.com",
)

# BOX5_OUTBOUND_INGEST_1 — direction-aware ingestion (Director ruling 2026-07-01).
# A sender in a Brisen-controlled domain OR address is OUTBOUND; everyone else is
# INBOUND. Read ONCE at import (module-level): this is a rarely-changing allowlist
# set in Render env, not a per-tick knob like the keyword/lookback reads.
_OUTBOUND_INGEST_ENV = "AIRPORT_OUTBOUND_INGEST_ENABLED"
_BRISEN_OUTBOUND_DOMAINS = {
    d.strip().lower()
    for d in os.environ.get("BRISEN_OUTBOUND_DOMAINS", "brisengroup.com").split(",")
    if d.strip()
}
_BRISEN_OUTBOUND_ADDRESSES = {
    a.strip().lower()
    for a in os.environ.get(
        "BRISEN_OUTBOUND_ADDRESSES",
        "vallen300@gmail.com,dvallen@bluewin.ch,office.vienna@brisengroup.com",
    ).split(",")
    if a.strip()
}
# Sentinel proposed_desk_slug for a captured OUTBOUND row. Outbound NEVER boards a
# real desk (no bus post), so this is a bookkeeping placeholder only — distinct from
# _NOISE_DESK so captured outbound is never confused with REJECT_NOISE.
_OUTBOUND_DESK = "outbound"

VALID_CHECK_IN_OUTCOMES = frozenset(
    {"VALID", "FAKE", "DUPLICATE", "WRONG_TERMINAL", "URGENT", "NEEDS_LUGGAGE_READ"}
)
VALID_URGENCY = frozenset({"low", "normal", "high", "urgent"})


@dataclass(frozen=True)
class EmailArrival:
    message_id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    full_body: str
    received_date: Optional[datetime]
    source: str
    attachments: tuple[dict[str, Any], ...] = ()
    # BOX5_GATE2_PARTICIPANT_FETCH_LANE_1: True iff this arrival entered ONLY via the
    # participant-identity fetch lane (a registered project participant with NO keyword
    # match). It makes the arrival ticket-worthy on sender identity alone —
    # build_email_ticket relaxes its keyword gate for it. Default False keeps every
    # keyword-lane arrival byte-identical.
    participant_fetched: bool = False


@dataclass(frozen=True)
class AirportTicket:
    ticket_id: str
    dedup_key: str
    created_at: datetime
    source_channel: str
    source_id: str
    source_received_at: Optional[datetime]
    originator: str
    suspected_matter_slug: str
    suspected_flight: str
    proposed_desk_slug: str
    urgency_hint: str
    luggage: tuple[str, ...]
    why_ticketed: tuple[str, ...]
    known_limits: tuple[str, ...]
    # THREAD_CONTINUITY_ROUTING_1: email thread identity, persisted as a queryable
    # airport_tickets column (see reserve_ticket). Default "" keeps the field optional
    # for any non-email constructor; NOT added to payload() so the AIRPORT_TICKET v1
    # bus contract stays byte-identical.
    thread_id: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "contract": "AIRPORT_TICKET v1",
            "ticket_id": self.ticket_id,
            "created_at": self.created_at.isoformat(),
            "source_channel": self.source_channel,
            "source_id": self.source_id,
            "source_received_at": (
                self.source_received_at.isoformat() if self.source_received_at else None
            ),
            "originator": self.originator,
            "suspected_matter_slug": self.suspected_matter_slug,
            "suspected_flight": self.suspected_flight,
            "proposed_desk_slug": self.proposed_desk_slug,
            "urgency_hint": self.urgency_hint,
            "luggage": list(self.luggage),
            "why_ticketed": list(self.why_ticketed),
            "known_limits": list(self.known_limits),
        }


# BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — non-mail arrival shapes, mirroring EmailArrival.
# Each carries a `*_matched` bool (symmetric to EmailArrival.participant_fetched): True
# iff the row entered ONLY via the identity lane (registry matter_slug for Plaud, registry
# WhatsApp participant for WA) with NO keyword hit, so build_*_ticket tickets it on
# identity alone. `received_at` feeds the same contiguous-prefix watermark _advance the
# email lane uses.
@dataclass(frozen=True)
class PlaudArrival:
    transcript_id: str
    title: str
    summary: str
    full_transcript: str
    received_at: Optional[datetime]
    matter_slug: str
    matter_matched: bool = False


@dataclass(frozen=True)
class WhatsAppArrival:
    message_id: str
    sender: str
    sender_name: str
    chat_id: str
    full_text: str
    received_at: Optional[datetime]
    participant_matched: bool = False


def bridge_enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# BOX5_TICKETING_RUNNER_1 — runner kill-switch + cursor + gauge constants.
_FAST_LANE_ENV = "BOX5_FAST_LANE_ENABLED"
# DISTINCT watermark key — must never collide with the live email poll
# ('email_poll' / 'email_poll_checked'), or the runner would rewind that cursor.
_WATERMARK_SOURCE = "airport_ticketing:email"
_STUCK_ARRIVAL_MINUTES = 30
# Sentinel desk for REJECT_NOISE rows (build_email_ticket returned None, so no real
# desk owns the arrival). reserve_noise_row keys the dedup on this so repeated noise
# de-dups; the row exists only to carry the terminal_status.
_NOISE_DESK = "unrouted"


def fast_lane_enabled() -> bool:
    """When False, every non-deterministic-clear arrival routes to the safe default
    terminal_status='TICKET' (full desk review). Freeze-by-flag kill switch
    (blocker 7b); default closed, no deploy needed to freeze a misroute. BRIEF-C has
    no fast lane yet — this only future-proofs D/E, but it is read + honored now."""
    raw = os.environ.get(_FAST_LANE_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def trigger_state_get_watermark(source: str) -> datetime:
    """Lazy wrapper over the trigger_state singleton (avoids a module-load import
    cycle; single monkeypatch point for tests)."""
    from triggers.state import trigger_state

    return trigger_state.get_watermark(source)


def trigger_state_watermark_raw(source: str) -> Optional[datetime]:
    """Lazy wrapper: raw watermark (None when NO row exists), NOT the NOW-24h
    fallback. run_tick needs to tell 'never activated' from a real cursor so a blank
    cursor starts at the full lookback floor instead of stranding the 24h→lookback
    backlog."""
    from triggers.state import trigger_state

    return trigger_state.get_watermark_raw(source)


def trigger_state_set_watermark(source: str, timestamp: datetime) -> None:
    from triggers.state import trigger_state

    trigger_state.set_watermark(source, timestamp)


def max_posts_per_tick() -> int:
    try:
        value = int(os.environ.get(_MAX_POSTS_ENV, str(_DEFAULT_MAX_POSTS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_POSTS
    return max(0, min(value, 25))


def lookback_hours() -> int:
    try:
        value = int(os.environ.get(_LOOKBACK_HOURS_ENV, str(_DEFAULT_LOOKBACK_HOURS)))
    except (TypeError, ValueError):
        return _DEFAULT_LOOKBACK_HOURS
    return max(1, min(value, 24 * 14))


def nonmail_sources_enabled() -> bool:
    """BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 master flag. Default OFF -> run_tick never calls
    the Plaud/WhatsApp fetchers, so a merge is a pure no-op on the email lane."""
    raw = os.environ.get(_NONMAIL_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def nonmail_dry_run() -> bool:
    """Rule 11c preview-first: when true the non-mail lanes LOG would-be tickets without
    inserting or advancing the watermark. The first live run with the master flag on
    should be a dry run before the real one."""
    raw = os.environ.get(_NONMAIL_DRY_RUN_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def nonmail_lookback_hours() -> int:
    try:
        value = int(
            os.environ.get(
                _NONMAIL_LOOKBACK_HOURS_ENV, str(_DEFAULT_NONMAIL_LOOKBACK_HOURS)
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_NONMAIL_LOOKBACK_HOURS
    return max(1, min(value, 24 * 30))


def active_keywords() -> tuple[str, ...]:
    raw = os.environ.get(_KEYWORDS_ENV, "")
    values = [part.strip().lower() for part in raw.split(",") if part.strip()]
    return tuple(values) if values else _DEFAULT_KEYWORDS


def _miss_fetch_cap() -> int:
    """BOX5_DROP_OBSERVABILITY_1 (G3 rework #4957) — hard row cap on the Gate-2 MISS
    fetch (drop-logging only). Env-tunable; bounded so a misconfig cannot trigger an
    unbounded scan. This bounds the drop-log query ALONE and is fully decoupled from the
    match fetch that decides what tickets — it can never starve a real keyword match."""
    try:
        value = int(os.environ.get(_MISS_FETCH_CAP_ENV, str(_DEFAULT_MISS_FETCH_CAP)))
    except (TypeError, ValueError):
        return _DEFAULT_MISS_FETCH_CAP
    return max(1, min(value, 5000))


def participant_lane_enabled() -> bool:
    """BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 dark flag (default OFF). OFF -> the participant
    fetch lane is a pure no-op and fetch_email_arrivals returns EXACTLY the keyword match
    set (byte-identical to pre-change, AC6). AH1 flips it in Render (merge-mode) to widen
    Gate-2 reachability. Orthogonal to the master gate, the fast-lane flag, and the
    outbound-ingest flag."""
    raw = os.environ.get(_PARTICIPANT_LANE_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _participant_fetch_cap() -> int:
    """BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 — hard row cap on the participant fetch lane
    ALONE (mirrors _miss_fetch_cap). The allow-set is already tiny, but this bounds the
    scan so a registry misconfig cannot trigger an unbounded fetch. Decoupled from the
    keyword match fetch — it can never starve a real keyword match."""
    try:
        value = int(
            os.environ.get(
                _PARTICIPANT_FETCH_CAP_ENV, str(_DEFAULT_PARTICIPANT_FETCH_CAP)
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_PARTICIPANT_FETCH_CAP
    return max(1, min(value, 5000))


def _wa_identity_ticket_max_age_hours() -> int:
    """DATA_OPS_AO_PLAUD_BACKFILL_WA_NOISE_1 task 6 — WA identity-only ticket suppression
    knob. Returns hours: 0 = suppress all identity-only WA tickets regardless of age
    (#6619 default), N>0 = suppress only those older than N hours (#6200 ceiling), and a
    negative value = DISABLED (legacy: identity-only always tickets). Bounded at 1y so a
    misconfig cannot overflow; a non-integer value falls back to the default."""
    try:
        value = int(
            os.environ.get(
                _WA_IDENTITY_TICKET_MAX_AGE_ENV,
                str(_DEFAULT_WA_IDENTITY_TICKET_MAX_AGE_HOURS),
            )
        )
    except (TypeError, ValueError):
        return _DEFAULT_WA_IDENTITY_TICKET_MAX_AGE_HOURS
    if value < 0:
        return -1
    return min(value, 8760)


def _wa_identity_only(
    arrival: "WhatsAppArrival", keywords: tuple[str, ...] | None = None
) -> bool:
    """True iff a WA arrival is identity-only: fetched on registered-participant identity
    (participant_matched) with NO active-keyword hit. A keyword match is never identity-
    only and always tickets, so it is exempt from task-6 suppression."""
    if not arrival.participant_matched:
        return False
    keys = keywords or active_keywords()
    return not _match_active_keywords("", arrival.full_text, keys)


def _wa_identity_suppressed(
    arrival: "WhatsAppArrival",
    now: datetime,
    keywords: tuple[str, ...] | None = None,
) -> bool:
    """Task 6: should this WA arrival's identity-only ticket be suppressed (not minted)?
    Config-driven via AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS. NEVER suppresses a
    keyword/matter match — only identity-only arrivals. Suppression mints no ticket; the
    stored whatsapp_messages row is untouched (store-everything). Callers must advance the
    watermark past a suppressed arrival (it is intentionally handled)."""
    if not _wa_identity_only(arrival, keywords):
        return False
    max_age = _wa_identity_ticket_max_age_hours()
    if max_age < 0:
        return False  # DISABLED (legacy escape hatch): identity-only still tickets
    if max_age == 0:
        return True  # suppress all identity-only regardless of age (#6619)
    if arrival.received_at is None:
        return True  # cannot prove recency -> suppress (noise-reduction default)
    age_hours = (now - arrival.received_at).total_seconds() / 3600.0
    return age_hours >= max_age


def _match_active_keywords(
    subject: str, full_body: str, keys: tuple[str, ...]
) -> list[str]:
    """Single source of truth for the active-keyword match (Gate 2). Case-insensitive
    substring over subject + body — the Python mirror of the SQL
    `subject ILIKE %kw% OR full_body ILIKE %kw%` prefilter. Used by build_email_ticket
    to record which keywords a ticketed arrival matched (urgency + matched_keywords), so
    the ticket's recorded match can never drift from the SQL gate that admitted it."""
    haystack = f"{subject} {full_body}".lower()
    return [kw for kw in keys if kw and kw.lower() in haystack]


def _keyword_ilike_where(keys: tuple[str, ...]) -> tuple[str, list[str]]:
    """Build the Gate-2 keyword-ILIKE predicate + its bind params, shared by the match
    fetch and the (negated) miss fetch so the two are EXACT complements — the miss set
    is byte-for-byte 'the rows the match query would not return'. This is the IDENTICAL
    construction the pre-observability match query used inline, so restoring it in the
    match fetch keeps what tickets byte-for-byte the same (parity)."""
    clauses: list[str] = []
    params: list[str] = []
    for keyword in keys:
        pattern = f"%{keyword}%"
        clauses.append("(subject ILIKE %s OR full_body ILIKE %s)")
        params.extend([pattern, pattern])
    return " OR ".join(clauses), params


def _desk_slug() -> str:
    return os.environ.get(_DESK_ENV, _DEFAULT_DESK).strip() or _DEFAULT_DESK


def _matter_slug() -> str:
    return os.environ.get(_MATTER_ENV, _DEFAULT_MATTER).strip() or _DEFAULT_MATTER


def _desk_for_matter(matter_slug: Optional[str], conn: Any = None) -> str:
    """AO_FLIGHT_PROD_TICKET_ROUTING_1 — per-matter desk resolution for the mint sites.

    Returns the matter's registry ``desk_owner`` when it is known AND a live conn is in
    hand, else the global ``_desk_slug()`` (today's routing). Resolved through
    ``resolve_owner_slug`` + ``RESERVED_RECIPIENTS`` exactly as the mint sites do, so a
    mapped-but-invalid desk falls back rather than minting to a reserved recipient.

    ``conn`` is optional so the pure builders stay callable DB-free (conn=None -> global
    desk, ZERO registry hit — keeps unit tests byte-identical); run_tick passes the tick's
    conn so the registry read shares the open transaction (no extra connection). Sourcing
    from ``project_registry.desk_owner`` (not an env map) is lead ruling #6850 — the
    registry is the single source of truth already consumed fleet-wide.

    Fault-tolerant: any failure (or a None conn / unknown / ambiguous matter) yields the
    global desk — NEVER raises, NEVER an empty desk."""
    fallback = resolve_owner_slug(_desk_slug()) or _desk_slug()
    if conn is None or not matter_slug:
        return fallback
    try:
        owner = desk_owner_for_matter(conn, matter_slug)
    except Exception as e:
        logger.warning(
            "airport ticketing per-matter desk lookup failed (%s): %s", matter_slug, e
        )
        return fallback
    if not owner:
        return fallback
    resolved = resolve_owner_slug(owner) or owner
    if not resolved or resolved in RESERVED_RECIPIENTS:
        logger.warning(
            "airport ticketing per-matter desk %r invalid, using global", owner
        )
        return fallback
    return resolved


def _flight_name() -> str:
    return os.environ.get(_FLIGHT_ENV, _DEFAULT_FLIGHT).strip() or _DEFAULT_FLIGHT


def _json_param(payload: Any) -> Any:
    # Accepts any JSON-serializable value (dict for action payloads, list for
    # box5_dropped_signals.matched_keywords). psycopg2 Json() adapts both.
    try:
        import psycopg2.extras

        return psycopg2.extras.Json(payload)
    except Exception:
        return json.dumps(payload)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_text(value: str, *, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def _ticket_id(source_channel: str, source_id: str, desk_slug: str) -> str:
    raw = f"AIRPORT_TICKET v1|{source_channel}|{source_id}|{desk_slug}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"airport-ticket-v1-{digest}"


def _dedup_key(source_channel: str, source_id: str, desk_slug: str) -> str:
    return f"airport-ticket:v1:{source_channel}:{source_id}:{desk_slug}"


def _urgency_for(arrival: EmailArrival, matched_keywords: list[str]) -> str:
    text = f"{arrival.subject} {arrival.full_body[:1000]}".lower()
    urgent_terms = ("urgent", "absolute priority", "today", "closing", "sign", "notary")
    if any(term in text for term in urgent_terms):
        return "urgent"
    if matched_keywords:
        return "high"
    return "normal"


def _originator(arrival: EmailArrival) -> str:
    name = _normalize_text(arrival.sender_name, limit=120)
    email = _normalize_text(arrival.sender_email, limit=160)
    if name and email:
        return f"{name} <{email}>"
    return name or email or "unknown"


def _is_automated_email_arrival(arrival: EmailArrival) -> bool:
    sender = (arrival.sender_email or "").strip().lower()
    if not sender:
        return False
    return any(pattern in sender for pattern in _SKIP_EMAIL_SENDER_PATTERNS)


def _classify_direction(sender_email: str) -> str:
    """'outbound' iff the sender is a Brisen-controlled address/domain, else
    'inbound'. Pure + total — NEVER raises: a bad / empty / garbage sender is
    'inbound', the safe default that preserves today's inbound routing.
    BOX5_OUTBOUND_INGEST_1."""
    try:
        s = (sender_email or "").strip().lower()
        if not s or "@" not in s:
            return "inbound"
        if s in _BRISEN_OUTBOUND_ADDRESSES:
            return "outbound"
        return (
            "outbound"
            if s.rsplit("@", 1)[1] in _BRISEN_OUTBOUND_DOMAINS
            else "inbound"
        )
    except Exception:
        return "inbound"


def _outbound_ingest_enabled() -> bool:
    """Dark flag (default OFF), orthogonal to the master gate + the fast-lane flag.
    OFF -> outbound arrivals are dropped (never board a desk). ON -> outbound is
    captured as a direction-tagged action-evidence signal. BOX5_OUTBOUND_INGEST_1."""
    raw = os.environ.get(_OUTBOUND_INGEST_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_email_ticket(
    arrival: EmailArrival,
    *,
    now: Optional[datetime] = None,
    keywords: tuple[str, ...] | None = None,
) -> Optional[AirportTicket]:
    if _is_automated_email_arrival(arrival):
        return None

    keys = keywords or active_keywords()
    matched = _match_active_keywords(arrival.subject, arrival.full_body, keys)
    if not matched and not arrival.participant_fetched:
        # No keyword AND not a registered-participant fetch -> nothing to ticket on.
        # (Automated senders already returned None above.) BOX5_GATE2_PARTICIPANT_FETCH_
        # LANE_1: a participant-lane arrival is ticket-worthy on sender identity alone, so
        # it falls through to a (safe-default desk-review) TICKET even with zero keywords —
        # it must NEVER be silently dropped now that Gate 2 fetched it. Deterministic:
        # identity comes from the registry match at fetch, no classifier involved.
        return None

    desk_slug = resolve_owner_slug(_desk_slug()) or _desk_slug()
    if not desk_slug or desk_slug in RESERVED_RECIPIENTS:
        logger.warning("airport ticketing invalid proposed desk: %s", desk_slug)
        return None

    created_at = now or _utc_now()
    ticket_id = _ticket_id("email", arrival.message_id, desk_slug)
    body_preview = _normalize_text(arrival.full_body, limit=260)
    luggage = [
        f"email subject: {arrival.subject or '(no subject)'}",
        f"transport source: {arrival.source or 'unknown'}",
        f"thread_id: {arrival.thread_id or arrival.message_id}",
    ]
    if body_preview:
        luggage.append(f"body_preview: {body_preview}")
    for att in arrival.attachments:
        filename = _normalize_text(str(att.get("filename") or "unnamed"), limit=220)
        mime_type = _normalize_text(str(att.get("mime_type") or "unknown"), limit=120)
        size = att.get("size_bytes")
        suffix = f", {size} bytes" if size is not None else ""
        luggage.append(f"attachment: {filename} ({mime_type}{suffix})")

    if matched:
        why = [f"matched active flight keyword(s): {', '.join(sorted(set(matched)))}"]
    else:
        # BOX5_GATE2_PARTICIPANT_FETCH_LANE_1: fetched on registered-participant identity
        # with no keyword match (arrival.participant_fetched is True to reach here).
        why = ["fetched by registered project-participant identity (no keyword match)"]
    if arrival.received_date:
        why.append(f"received_at: {arrival.received_date.isoformat()}")

    return AirportTicket(
        ticket_id=ticket_id,
        dedup_key=_dedup_key("email", arrival.message_id, desk_slug),
        created_at=created_at,
        source_channel="email",
        source_id=arrival.message_id,
        source_received_at=arrival.received_date,
        originator=_originator(arrival),
        suspected_matter_slug=_matter_slug(),
        suspected_flight=_flight_name(),
        proposed_desk_slug=desk_slug,
        urgency_hint=_urgency_for(arrival, matched),
        luggage=tuple(luggage),
        why_ticketed=tuple(why),
        known_limits=(
            "Ticketing Bridge did not read or interpret attachments.",
            "Ticketing Bridge did not decide condition precedent status.",
            "Owning desk must check in as VALID, FAKE, DUPLICATE, WRONG_TERMINAL, URGENT, or NEEDS_LUGGAGE_READ.",
        ),
        # Same thread identity the luggage line records, now also a queryable column
        # so a later code-less reply on this thread can inherit its routing.
        thread_id=arrival.thread_id or arrival.message_id,
    )


# ---------------------------------------------------------------------------
# BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — Plaud + WhatsApp lanes (phase 1)
# ---------------------------------------------------------------------------
_NONMAIL_KNOWN_LIMITS = (
    "Ticketing Bridge did not read or interpret the full transcript/message.",
    "Ticketing Bridge did not decide condition precedent status.",
    "Owning desk must check in as VALID, FAKE, DUPLICATE, WRONG_TERMINAL, URGENT, or NEEDS_LUGGAGE_READ.",
)


def _nonmail_originator(name: str, handle: str) -> str:
    name = _normalize_text(name, limit=120)
    handle = _normalize_text(handle, limit=160)
    if name and handle:
        return f"{name} <{handle}>"
    return name or handle or "unknown"


def _nonmail_urgency(matched: list[str]) -> str:
    # Non-mail lanes never fast-board; identity-only matches route to desk review at
    # 'normal', keyword matches at 'high' (mirrors the email lane's non-urgent default).
    return "high" if matched else "normal"


def _active_matter_slugs(conn: Any) -> set[str]:
    """DISTINCT matter_slug over ACTIVE registry rows — the Plaud matter lane's allow-set,
    built once per tick (mirrors active_participant_values for WA). Fault-tolerant: []
    on any error so a registry hiccup no-ops the lane rather than aborting the tick."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT matter_slug FROM project_registry "
                "WHERE status = 'active' AND matter_slug IS NOT NULL LIMIT 500"
            )
            rows = cur.fetchall()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("active matter slugs fetch failed: %s", e)
        return set()
    return {str(r[0]).strip().lower() for r in rows if r and r[0]}


def build_plaud_ticket(
    arrival: PlaudArrival,
    *,
    now: Optional[datetime] = None,
    keywords: tuple[str, ...] | None = None,
    conn: Any = None,
) -> Optional[AirportTicket]:
    keys = keywords or active_keywords()
    matched = _match_active_keywords(
        arrival.title, f"{arrival.summary} {arrival.full_transcript}", keys
    )
    if not matched and not arrival.matter_matched:
        # No keyword AND not an active-matter fetch -> nothing to ticket on.
        return None

    # AO_FLIGHT_PROD_TICKET_ROUTING_1: route by the arrival's registry matter (Plaud is the
    # only mint lane that knows the real matter at mint time — arrival.matter_slug). Unknown
    # / ambiguous / conn-less -> global desk (byte-identical to today). #6850.
    desk_slug = _desk_for_matter(arrival.matter_slug, conn)
    if not desk_slug or desk_slug in RESERVED_RECIPIENTS:
        logger.warning("airport nonmail invalid proposed desk (plaud): %s", desk_slug)
        return None

    created_at = now or _utc_now()
    luggage = [
        f"plaud transcript: {arrival.title or '(untitled)'}",
        f"transcript_id: {arrival.transcript_id}",
    ]
    summary_preview = _normalize_text(arrival.summary or arrival.full_transcript, limit=260)
    if summary_preview:
        luggage.append(f"summary_preview: {summary_preview}")
    if arrival.matter_slug:
        luggage.append(f"registry matter_slug: {arrival.matter_slug}")

    if matched:
        why = [f"matched active flight keyword(s): {', '.join(sorted(set(matched)))}"]
    else:
        why = [f"matched active registry matter_slug: {arrival.matter_slug}"]
    if arrival.received_at:
        why.append(f"received_at: {arrival.received_at.isoformat()}")

    return AirportTicket(
        ticket_id=_ticket_id("plaud", arrival.transcript_id, desk_slug),
        dedup_key=_dedup_key("plaud", arrival.transcript_id, desk_slug),
        created_at=created_at,
        source_channel="plaud",
        source_id=arrival.transcript_id,
        source_received_at=arrival.received_at,
        originator=_nonmail_originator(arrival.title, arrival.transcript_id),
        suspected_matter_slug=arrival.matter_slug or _matter_slug(),
        suspected_flight=_flight_name(),
        proposed_desk_slug=desk_slug,
        urgency_hint=_nonmail_urgency(matched),
        luggage=tuple(luggage),
        why_ticketed=tuple(why),
        known_limits=_NONMAIL_KNOWN_LIMITS,
    )


def build_whatsapp_ticket(
    arrival: WhatsAppArrival,
    *,
    now: Optional[datetime] = None,
    keywords: tuple[str, ...] | None = None,
    conn: Any = None,
) -> Optional[AirportTicket]:
    keys = keywords or active_keywords()
    matched = _match_active_keywords("", arrival.full_text, keys)
    if not matched and not arrival.participant_matched:
        # No keyword AND not a registered-participant fetch -> nothing to ticket on.
        return None

    # AO_FLIGHT_PROD_TICKET_ROUTING_1: `conn` is accepted for the shared _run_nonmail_lane
    # build_fn signature, but the WA lane STAYS on the global desk this brief — WhatsAppArrival
    # carries no matter_slug, so there is no per-matter attribution at mint (identity-only WA
    # is suppressed anyway, PR #482). Per-matter WA routing is a reported follow-up (#6850).
    desk_slug = resolve_owner_slug(_desk_slug()) or _desk_slug()
    if not desk_slug or desk_slug in RESERVED_RECIPIENTS:
        logger.warning("airport nonmail invalid proposed desk (whatsapp): %s", desk_slug)
        return None

    created_at = now or _utc_now()
    body_preview = _normalize_text(arrival.full_text, limit=260)
    luggage = [
        f"whatsapp from: {arrival.sender_name or arrival.sender or 'unknown'}",
        f"message_id: {arrival.message_id}",
        f"chat_id: {arrival.chat_id or 'unknown'}",
    ]
    if body_preview:
        luggage.append(f"body_preview: {body_preview}")

    if matched:
        why = [f"matched active flight keyword(s): {', '.join(sorted(set(matched)))}"]
    else:
        why = ["fetched by registered project-participant identity (no keyword match)"]
    if arrival.received_at:
        why.append(f"received_at: {arrival.received_at.isoformat()}")

    return AirportTicket(
        ticket_id=_ticket_id("whatsapp", arrival.message_id, desk_slug),
        dedup_key=_dedup_key("whatsapp", arrival.message_id, desk_slug),
        created_at=created_at,
        source_channel="whatsapp",
        source_id=arrival.message_id,
        source_received_at=arrival.received_at,
        originator=_nonmail_originator(arrival.sender_name, arrival.sender),
        suspected_matter_slug=_matter_slug(),
        suspected_flight=_flight_name(),
        proposed_desk_slug=desk_slug,
        urgency_hint=_nonmail_urgency(matched),
        luggage=tuple(luggage),
        why_ticketed=tuple(why),
        known_limits=_NONMAIL_KNOWN_LIMITS,
    )


def fetch_plaud_arrivals(
    conn: Any,
    *,
    since: datetime,
    limit: int = 50,
    keywords: tuple[str, ...] | None = None,
) -> list[PlaudArrival]:
    """meeting_transcripts WHERE source='plaud' AND (keyword ILIKE on title/summary/
    full_transcript OR matter_slug in an ACTIVE registry matter). OLDEST-FIRST for the
    contiguous-prefix watermark. Fault-tolerant: [] + rollback on any error."""
    keys = keywords or active_keywords()
    lim = max(1, min(int(limit), 200))
    active_matters = _active_matter_slugs(conn)

    kw_clauses: list[str] = []
    kw_params: list[str] = []
    for kw in keys:
        if not kw:
            continue
        pattern = f"%{kw}%"
        kw_clauses.append(
            "(title ILIKE %s OR summary ILIKE %s OR full_transcript ILIKE %s)"
        )
        kw_params.extend([pattern, pattern, pattern])
    kw_where = " OR ".join(kw_clauses) if kw_clauses else "FALSE"

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, title, summary, full_transcript, meeting_date, matter_slug
                FROM meeting_transcripts
                WHERE source = 'plaud'
                  AND meeting_date >= %s
                  AND ( ({kw_where})
                        OR (matter_slug IS NOT NULL AND matter_slug IN (
                              SELECT matter_slug FROM project_registry
                              WHERE status = 'active' AND matter_slug IS NOT NULL)) )
                ORDER BY meeting_date ASC
                LIMIT %s
                """,
                (since, *kw_params, lim),
            )
            rows = cur.fetchall()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("fetch_plaud_arrivals failed: %s", e)
        return []

    arrivals: list[PlaudArrival] = []
    for row in rows:
        received = row[4]
        if isinstance(received, datetime) and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        title = str(row[1] or "")
        summary = str(row[2] or "")
        transcript = str(row[3] or "")
        matter = str(row[5] or "")
        # matter_matched = fetched via the active-matter lane with NO keyword hit
        # (symmetric to EmailArrival.participant_fetched).
        kw_hit = bool(_match_active_keywords(title, f"{summary} {transcript}", keys))
        matter_matched = (not kw_hit) and (matter.strip().lower() in active_matters)
        arrivals.append(
            PlaudArrival(
                transcript_id=str(row[0] or ""),
                title=title,
                summary=summary,
                full_transcript=transcript,
                received_at=received if isinstance(received, datetime) else None,
                matter_slug=matter,
                matter_matched=matter_matched,
            )
        )
    return arrivals


def fetch_whatsapp_arrivals(
    conn: Any,
    *,
    since: datetime,
    limit: int = 50,
    keywords: tuple[str, ...] | None = None,
) -> list[WhatsAppArrival]:
    """whatsapp_messages WHERE keyword ILIKE on full_text OR sender/chat_id in the ACTIVE
    registry WhatsApp participant set (participant match alone -> desk review, never fast
    lane — same rule as email). @lid chat-ids accepted (Lesson #28, no format filtering).
    OLDEST-FIRST. Fault-tolerant: [] + rollback on any error."""
    keys = keywords or active_keywords()
    lim = max(1, min(int(limit), 200))
    participants = active_participant_values(conn, "whatsapp")

    kw_clauses: list[str] = []
    kw_params: list[str] = []
    for kw in keys:
        if not kw:
            continue
        kw_clauses.append("full_text ILIKE %s")
        kw_params.append(f"%{kw}%")
    kw_where = " OR ".join(kw_clauses) if kw_clauses else "FALSE"

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, sender, sender_name, chat_id, full_text, timestamp
                FROM whatsapp_messages
                WHERE timestamp >= %s
                  AND ( ({kw_where})
                        OR lower(sender) = ANY(%s)
                        OR lower(chat_id) = ANY(%s) )
                ORDER BY timestamp ASC
                LIMIT %s
                """,
                (since, *kw_params, participants, participants, lim),
            )
            rows = cur.fetchall()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("fetch_whatsapp_arrivals failed: %s", e)
        return []

    part_set = set(participants)
    arrivals: list[WhatsAppArrival] = []
    for row in rows:
        received = row[5]
        if isinstance(received, datetime) and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        sender = str(row[1] or "")
        chat_id = str(row[3] or "")
        full_text = str(row[4] or "")
        kw_hit = bool(_match_active_keywords("", full_text, keys))
        participant_matched = (not kw_hit) and (
            sender.strip().lower() in part_set or chat_id.strip().lower() in part_set
        )
        arrivals.append(
            WhatsAppArrival(
                message_id=str(row[0] or ""),
                sender=sender,
                sender_name=str(row[2] or ""),
                chat_id=chat_id,
                full_text=full_text,
                received_at=received if isinstance(received, datetime) else None,
                participant_matched=participant_matched,
            )
        )
    return arrivals


def ensure_airport_ticket_table(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS airport_tickets (
                id BIGSERIAL PRIMARY KEY,
                ticket_id TEXT NOT NULL UNIQUE,
                dedup_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'candidate',
                source_channel TEXT NOT NULL,
                source_id TEXT NOT NULL,
                source_received_at TIMESTAMPTZ,
                originator TEXT,
                suspected_matter_slug TEXT,
                suspected_flight TEXT,
                proposed_desk_slug TEXT NOT NULL,
                urgency_hint TEXT NOT NULL DEFAULT 'normal',
                ticket JSONB NOT NULL DEFAULT '{}'::jsonb,
                bus_message_id BIGINT,
                bus_thread_id TEXT,
                last_sent_at TIMESTAMPTZ,
                check_in_outcome TEXT,
                check_in_at TIMESTAMPTZ,
                check_in_by TEXT,
                failure_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT airport_tickets_status_check
                    CHECK (status IN ('candidate', 'sent', 'failed', 'checked_in', 'rejected', 'closed')),
                CONSTRAINT airport_tickets_source_channel_check
                    CHECK (source_channel IN ('email', 'whatsapp', 'plaud', 'clickup', 'calendar', 'other')),
                CONSTRAINT airport_tickets_urgency_check
                    CHECK (urgency_hint IN ('low', 'normal', 'high', 'urgent')),
                CONSTRAINT airport_tickets_check_in_outcome_check
                    CHECK (
                        check_in_outcome IS NULL OR
                        check_in_outcome IN (
                            'VALID',
                            'FAKE',
                            'DUPLICATE',
                            'WRONG_TERMINAL',
                            'URGENT',
                            'NEEDS_LUGGAGE_READ'
                        )
                    )
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_airport_tickets_source
                ON airport_tickets (source_channel, source_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_airport_tickets_desk_status
                ON airport_tickets (proposed_desk_slug, status, last_sent_at DESC)
            """
        )
        # BOX5_RECEIPT_TTL_1: nudge-state columns for the stale-ticket TTL sweep.
        # Mirrors migrations/20260630_airport_tickets_nudge_state.sql so an
        # already-bootstrapped DB (where CREATE TABLE IF NOT EXISTS no-ops) still
        # gains the columns — the documented migration-vs-bootstrap drift fix.
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS last_nudged_at TIMESTAMPTZ"
        )
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS nudge_count INTEGER NOT NULL DEFAULT 0"
        )
        # BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1 (T0): 'closed' terminal status for
        # a fully-received onward journey (source ticket flips checked_in -> closed only at
        # RECEIPT_WRITTEN). Mirrors migrations/20260704a_airport_onward_journey.sql. On an
        # already-bootstrapped DB the CREATE TABLE IF NOT EXISTS no-ops, so an idempotent
        # DROP + ADD is what amends the live constraint (migration-vs-bootstrap drift,
        # Lesson #37/#50).
        cur.execute(
            "ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_status_check"
        )
        cur.execute(
            "ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_status_check "
            "CHECK (status IN ('candidate', 'sent', 'failed', 'checked_in', 'rejected', 'closed'))"
        )
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ"
        )
        # BOX5_OUTBOUND_INGEST_1: direction axis (inbound / outbound). Mirrors
        # migrations/20260701_airport_tickets_direction.sql. NOT NULL DEFAULT
        # 'inbound' is safe on a populated table (existing rows backfill to
        # 'inbound'); inbound tickets never set it explicitly (the default carries
        # them, keeping reserve_ticket's INSERT byte-identical), only the outbound
        # capture path writes 'outbound'.
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'inbound'"
        )
        # THREAD_CONTINUITY_ROUTING_1: queryable email thread identity + its lookup
        # index. Mirrors migrations/20260701c_airport_tickets_thread_id.sql so an
        # already-bootstrapped DB (CREATE TABLE IF NOT EXISTS no-ops) still gains the
        # column + index (Lesson #50 migration-vs-bootstrap drift). Additive/nullable.
        cur.execute(
            "ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS thread_id TEXT"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_airport_tickets_thread_id "
            "ON airport_tickets (thread_id)"
        )
    # Additive terminal-classification axis (BOX5_SCHEMA_FOUNDATION_1 / BRIEF-B).
    # Mirrors migrations/20260630_airport_tickets_terminal_columns.sql. The
    # CREATE TABLE IF NOT EXISTS above never migrates an already-created prod
    # table, so we ALTER here; this also re-asserts the constraint on every
    # Render restart so the migration can't be silently reverted.
    ensure_airport_ticket_terminal_columns(conn)


def ensure_airport_ticket_terminal_columns(conn: Any) -> None:
    """Additive terminal-classification axis on airport_tickets (BRIEF-B).

    CREATE TABLE IF NOT EXISTS does NOT migrate an already-created prod table, so
    we ALTER here and mirror migrations/20260630_airport_tickets_terminal_columns.sql
    verbatim (Lesson #50 migration-vs-bootstrap drift). Re-asserted on every Render
    restart so the migration can't be silently reverted.

    terminal_status is ORTHOGONAL to the live `status` lifecycle and to
    `check_in_outcome` — new axis, new column, new CHECK. Do NOT touch those two.

    All columns nullable (or NOT NULL with a list DEFAULT) -> safe on a populated
    table; no backfill required.
    """
    try:
        with conn.cursor() as cur:
            # Terminal-result fields written later by the runner (BRIEF-C) and the
            # fast lanes (BRIEF-D/E). BRIEF-B only creates the columns.
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_status TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_reason TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS project_code TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS matter_slug TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS desk_owner TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS source_refs JSONB NOT NULL DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS confidence NUMERIC(3,2)")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS model_used TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS cost_tier TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS classification_version TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS registry_version TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS manifest_match_signals JSONB NOT NULL DEFAULT '[]'::jsonb")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_table TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS raw_source_id TEXT")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS terminal_outcome_written_at TIMESTAMPTZ")

            # terminal_status CHECK — EXACTLY 6 states. VISIBLE_HOLD is DELIBERATELY
            # EXCLUDED (locked decision #4677.7): it gets its own owner + TTL +
            # escalation + sweep brief; adding it here would make it prematurely
            # writable. Do NOT "fix" this omission. DROP-then-ADD mirrors the
            # signal_queue precedent so re-runs are clean (idempotent).
            cur.execute("ALTER TABLE airport_tickets DROP CONSTRAINT IF EXISTS airport_tickets_terminal_status_check")
            cur.execute(
                """
                ALTER TABLE airport_tickets ADD CONSTRAINT airport_tickets_terminal_status_check
                    CHECK (
                        terminal_status IS NULL OR
                        terminal_status IN (
                            'DUPLICATE',
                            'REJECT_NOISE',
                            'REJECT_LOW_RELEVANCE',
                            'FAST_TICKET',
                            'TICKET',
                            'FILE_UNSORTED'
                        )
                    )
                """
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def ensure_box5_dropped_signals_table(conn: Any) -> None:
    """BOX5_DROP_OBSERVABILITY_1 — bootstrap the per-gate drop-log table.

    Mirrors migrations/20260701d_box5_dropped_signals.sql VERBATIM so a DB that a
    migration runner has not yet reached still gains the table on the next tick
    (Lesson #50). Brand-new table -> a single identical CREATE TABLE IF NOT EXISTS in
    both places cannot drift; no ALTER / DROP-ADD churn on the hot path.

    FAULT-TOLERANT BY DESIGN: observability must never break the pipeline. If the
    bootstrap fails we roll back (keep the shared conn usable) and return WITHOUT
    raising — the drop-log is simply skipped this tick (every _write_dropped_signals
    call is itself guarded), the real ticketing journey continues untouched."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS box5_dropped_signals (
                    id               BIGSERIAL PRIMARY KEY,
                    message_id       TEXT,
                    thread_id        TEXT,
                    sender_email     TEXT,
                    subject          TEXT,
                    matched_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
                    gate             TEXT NOT NULL,
                    reason           TEXT,
                    received_date    TIMESTAMPTZ,
                    tick_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CONSTRAINT box5_dropped_signals_gate_check CHECK (
                        gate IN (
                            'keyword_prefilter',
                            'routing_unrouted',
                            'routing_conflict',
                            'other'
                        )
                    )
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_box5_dropped_signals_tick_at "
                "ON box5_dropped_signals (tick_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_box5_dropped_signals_gate "
                "ON box5_dropped_signals (gate)"
            )
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_box5_dropped_signals_msg_gate "
                "ON box5_dropped_signals (message_id, gate)"
            )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(
            "box5 dropped_signals bootstrap failed (drop-log skipped this tick): %s",
            exc,
        )


def _drop_record(
    arrival: "EmailArrival",
    *,
    gate: str,
    reason: str,
    matched_keywords: list[str] | None = None,
) -> tuple:
    """Build one box5_dropped_signals row tuple from an arrival (subject truncated,
    matched_keywords JSON-adapted). Column order matches _write_dropped_signals."""
    return (
        str(arrival.message_id or ""),
        str(arrival.thread_id or arrival.message_id or ""),
        str(arrival.sender_email or ""),
        _normalize_text(arrival.subject, limit=300),
        _json_param(list(matched_keywords or [])),
        gate,
        reason,
        arrival.received_date,
    )


def _write_dropped_signals(
    conn: Any, records: list[tuple], *, savepoint: bool = False
) -> int:
    """BOX5_DROP_OBSERVABILITY_1 — fault-tolerant drop-log writer. NEVER raises; a
    drop-log write failure must never abort or block the tick (AC3).

    ON CONFLICT (message_id, gate) DO NOTHING makes a re-fetched boundary arrival's
    re-classification idempotent (one drop per signal per gate).

    savepoint=False (Gate-2 fetch path, called on a CLEAN txn): commit the batch here
    so the rows persist even when the tick issues no per-row commit (e.g. an all-miss
    window). On error rollback so the shared conn stays usable.

    savepoint=True (Gate-3, inside run_tick's shared per-row txn with an uncommitted
    ticket reservation): wrap in a SAVEPOINT and DON'T commit — the caller's existing
    conn.commit() flushes the drop row atomically with the terminal write. On error
    ROLLBACK TO SAVEPOINT undoes ONLY the drop-log, preserving the reservation +
    terminal write (a bare conn.rollback would discard those good writes — the exact
    class the correlation-fix caught)."""
    if not records:
        return 0
    try:
        with conn.cursor() as cur:
            if savepoint:
                cur.execute(f"SAVEPOINT {_DROP_LOG_SAVEPOINT}")
            cur.executemany(
                """
                INSERT INTO box5_dropped_signals
                    (message_id, thread_id, sender_email, subject,
                     matched_keywords, gate, reason, received_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id, gate) DO NOTHING
                """,
                records,
            )
            if savepoint:
                cur.execute(f"RELEASE SAVEPOINT {_DROP_LOG_SAVEPOINT}")
        if not savepoint:
            conn.commit()
        return len(records)
    except Exception as exc:
        try:
            if savepoint:
                with conn.cursor() as cur:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {_DROP_LOG_SAVEPOINT}")
            else:
                conn.rollback()
        except Exception:
            # Savepoint unusable (e.g. the SAVEPOINT stmt itself failed) — full
            # rollback so the shared conn stays usable; the tick continues.
            try:
                conn.rollback()
            except Exception:
                pass
        logger.warning(
            "box5 drop-log write failed (%d row(s), observability best-effort): %s",
            len(records),
            exc,
        )
        return 0


def summarize_recent_drops(conn: Any, *, hours: int = 24) -> list[dict[str, Any]]:
    """Read-only observability surface (design item 4): drop counts by gate over the
    last N hours — the query lead runs to size the Gate-2 keyword-broadening off real
    data. Fault-tolerant: returns [] on any error (never raises)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gate, COUNT(*)
                  FROM box5_dropped_signals
                 WHERE tick_at >= now() - make_interval(hours => %s)
                 GROUP BY gate
                 ORDER BY COUNT(*) DESC
                """,
                (max(0, int(hours)),),
            )
            return [{"gate": r[0], "count": int(r[1])} for r in cur.fetchall()]
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("box5 drop summary read failed: %s", exc)
        return []


def _log_keyword_prefilter_misses(
    conn: Any, *, since: datetime, keys: tuple[str, ...]
) -> None:
    """BOX5_DROP_OBSERVABILITY_1 (G3 rework #4957) — Gate-2 observability, fully
    DECOUPLED from ticketing.

    A SEPARATE, independently-bounded query fetches the recent NON-matching arrivals
    (the NEGATED keyword ILIKE) and writes them to box5_dropped_signals so keyword-misses
    become visible. It shares NO state with the match fetch that decides what tickets, so
    it can NEVER change the ticketed set — parity is guaranteed by construction. (The
    G3-rejected single-superset-under-a-cap could starve real matches; two decoupled
    queries cannot.)

    Fully fault-tolerant (AC3): every failure path is caught, the shared conn is left
    usable, and the tick continues. Called on a CLEAN txn (fetch_email_arrivals runs
    before run_tick's per-row loop; ensure_* already committed, the match read is
    read-only), so the batch is committed inline (savepoint=False).
    """
    miss_cap = _miss_fetch_cap()
    where, kw_params = _keyword_ilike_where(keys)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT message_id, thread_id, sender_email, subject, received_date
                FROM email_messages
                WHERE received_date >= %s
                  AND NOT ({where})
                -- Recent-first: under the cap we keep the NEWEST misses (most useful for
                -- 'last 24h drops by gate'). Independently bounded — decoupled from the
                -- match fetch's LIMIT, so it can never affect what tickets.
                ORDER BY received_date DESC
                LIMIT %s
                """,
                (since, *kw_params, miss_cap),
            )
            rows = cur.fetchall()
    except Exception as exc:
        # Read failed — roll back so the shared conn stays usable for the per-row loop
        # (no good writes exist to lose at this call site). Drops are simply skipped.
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(
            "airport_ticketing Gate-2 miss-fetch read failed (drops unlogged this tick, "
            "ticketing unaffected): %s",
            exc,
        )
        return

    # Never a silent cut (AC4): if the miss fetch saturated its cap, some older misses
    # went unlogged this tick — log it (they re-surface as newer ones age out).
    if len(rows) >= miss_cap:
        logger.info(
            "airport_ticketing Gate-2 miss-fetch hit cap=%d; older misses beyond the cap "
            "unlogged this tick (raise %s if fuller drop coverage is needed)",
            miss_cap,
            _MISS_FETCH_CAP_ENV,
        )

    miss_records: list[tuple] = []
    for row in rows:
        received_raw = row[4]
        if isinstance(received_raw, datetime) and received_raw.tzinfo is None:
            received_raw = received_raw.replace(tzinfo=timezone.utc)
        miss_records.append(
            (
                str(row[0] or ""),
                str(row[1] or row[0] or ""),
                str(row[2] or ""),
                _normalize_text(str(row[3] or ""), limit=300),
                _json_param([]),  # keyword-miss -> matched_keywords empty (AC1)
                _GATE_KEYWORD_PREFILTER,
                "no_active_keyword_match",
                received_raw if isinstance(received_raw, datetime) else None,
            )
        )

    if miss_records:
        _write_dropped_signals(conn, miss_records, savepoint=False)


def _received_sort_key(row: tuple) -> datetime:
    """Global-ASC sort key for the unioned two-lane arrival list — received_date (index 6),
    UTC-coerced. A None / non-datetime date sorts OLDEST (datetime.min) so a null-date row
    can never leap the watermark ahead of a real dated arrival (AC4 watermark safety)."""
    dt = row[6] if len(row) > 6 else None
    if not isinstance(dt, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fetch_participant_arrivals(
    conn: Any, *, since: datetime, limit: int
) -> list[tuple]:
    """BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 — the SECOND, DECOUPLED fetch lane.

    Fetches recent ``email_messages`` whose ``sender_email`` is a REGISTERED ACTIVE project
    participant (channel=email), REGARDLESS of keyword. 100% deterministic registry match —
    NO classifier decides fetch eligibility (the reachability gate stays out of the LLM's
    hands). Returns raw rows in the SAME column shape as the keyword match fetch so the
    caller can union + globally re-sort ASC.

    Decoupling discipline (mirrors the drop-observability miss fetch): a SEPARATE bounded
    query that shares NO state with the keyword match fetch, so it can never change what the
    keyword lane fetches. ``ORDER BY received_date ASC`` mirrors the match fetch; the caller
    re-sorts the union so the runner's contiguous-prefix watermark stays safe.

    Fault-tolerant (AC5): ANY failure (registry enumerate OR the arrivals read) is caught,
    the shared conn is rolled back so it stays usable, and [] is returned — keyword
    ticketing proceeds unaffected that tick."""
    try:
        participants = active_participant_values(conn, "email")
        if not participants:
            return []
        cap = _participant_fetch_cap()
        lim = max(1, min(int(limit), cap))
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT message_id, thread_id, sender_name, sender_email,
                       subject, full_body, received_date, source
                FROM email_messages
                WHERE received_date >= %s
                  AND LOWER(sender_email) = ANY(%s)
                -- OLDEST-FIRST, same as the match fetch. The caller merges both lanes and
                -- re-sorts ASC so the runner's contiguous-prefix cursor can never advance
                -- past an un-processed participant-lane arrival (AC4).
                ORDER BY received_date ASC
                LIMIT %s
                """,
                (since, participants, lim),
            )
            return cur.fetchall()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(
            "airport_ticketing participant fetch lane read failed (ticketing unaffected "
            "this tick): %s",
            exc,
        )
        return []


# C3_GATE_RUNNER F1 (codex #6158) — synthetic-row marker, mirrored from
# scripts/c3_gate/c3_lib.py:PREFIX. The bridge lives in orchestrator/ and cannot
# import from scripts/, so the literal is redeclared here with this cross-reference;
# both MUST stay "c3-gate-". Rows carrying this message_id prefix are the C3 gate
# harness's own injected signals and are excluded from every production fetch below.
_C3_GATE_SYNTHETIC_PREFIX = "c3-gate-"


def fetch_email_arrivals(
    conn: Any,
    *,
    since: datetime,
    limit: int = 50,
    keywords: tuple[str, ...] | None = None,
    include_synthetic: bool = False,
) -> list[EmailArrival]:
    keys = keywords or active_keywords()
    if not keys:
        return []
    # BOX5_DROP_OBSERVABILITY_1 (G3 rework #4957) — Gate-2 observability is TWO DECOUPLED
    # queries:
    #   (1) MATCH FETCH (below) — the ONLY thing that decides what tickets. It is
    #       BYTE-IDENTICAL to the pre-observability keyword-ILIKE query, so parity is
    #       guaranteed BY CONSTRUCTION (nothing in the drop-log path can touch this set).
    #   (2) MISS FETCH (_log_keyword_prefilter_misses) — a SEPARATE, independently-
    #       bounded query that writes keyword-misses to box5_dropped_signals ONLY.
    # The earlier single-superset-under-a-cap approach was G3-rejected: a row cap on the
    # un-prefiltered fetch could starve real matches behind older non-matches and thereby
    # CHANGE what tickets. Two decoupled queries make that starvation impossible.
    lim = max(1, min(int(limit), 200))
    where, kw_params = _keyword_ilike_where(keys)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT message_id, thread_id, sender_name, sender_email,
                   subject, full_body, received_date, source
            FROM email_messages
            WHERE received_date >= %s
              AND ({where})
            -- BOX5_TICKETING_RUNNER_1 P1-A: OLDEST-FIRST. The runner processes the
            -- backlog in cursor order and advances the watermark only over the
            -- contiguous fully-processed prefix. Newest-first (DESC) under a per-tick
            -- cap would let the cursor jump to the newest processed row while older
            -- un-processed rows fall behind since=watermark -> permanent loss.
            ORDER BY received_date ASC
            LIMIT %s
            """,
            (since, *kw_params, lim),
        )
        rows = cur.fetchall()

    # Observability (decoupled, best-effort) — a separate bounded miss-fetch logs the
    # recent keyword-misses. It shares NO state with `rows` above, so it can never change
    # what tickets, and any failure inside is swallowed (the tick continues, AC3).
    _log_keyword_prefilter_misses(conn, since=since, keys=keys)

    # BOX5_GATE2_PARTICIPANT_FETCH_LANE_1 — union the DECOUPLED participant-identity fetch
    # lane into the keyword match set. Dark by default: flag OFF -> `rows` above is
    # returned byte-identically (pure no-op, AC6). ON -> participant-lane rows are unioned
    # (dedup by message_id; the keyword lane WINS a both-lanes row so its matched_keywords
    # survive downstream, AC3) and the WHOLE arrival list is globally re-sorted
    # received_date ASC. That global sort is the watermark-safety guarantee (AC4): a naive
    # concat of two individually-ASC lanes is NOT globally sorted, so the runner's
    # contiguous-prefix cursor could advance past an OLDER un-processed participant row and
    # strand it below the watermark -> permanent loss. Participant-ONLY rows (no keyword)
    # are tagged so build_email_ticket tickets them on identity alone (never dropped).
    #
    # MULTI-MATTER SAFETY (Director ruling, lead amend #5035): identity NEVER auto-routes.
    # This lane uses participant identity ONLY to *fetch* — routing is decided downstream by
    # project CODE (the (e.5)/(e.7)/(e.8) code/thread lanes), never by which projects a
    # sender belongs to. So a sender who is a participant in >1 active project (e.g. a
    # principal in BB-AUK-001 AND BB-MRCI-001) sending a code-less mail is AMBIGUOUS and
    # falls through to the (f) safe-default desk-review TICKET by construction — it can
    # never auto-pick one desk. The allow-set also de-dupes the sender across projects, so
    # a multi-project participant is fetched once, not once per project.
    participant_only_ids: set[str] = set()
    if participant_lane_enabled():
        keyword_ids = {str(r[0]) for r in rows if r and r[0]}
        for pr in _fetch_participant_arrivals(conn, since=since, limit=lim):
            mid = str(pr[0]) if pr and pr[0] else ""
            if mid and mid not in keyword_ids:
                keyword_ids.add(mid)
                participant_only_ids.add(mid)
                rows.append(pr)
        rows.sort(key=_received_sort_key)  # global ASC across BOTH lanes (AC4)

    # C3_GATE_RUNNER F1 (codex #6158) — defense-in-depth: the C3 gate harness injects
    # marked synthetic rows (message_id prefix `c3-gate-`) straight into the LIVE
    # email_messages table. Those rows must be INERT to the production spine — a
    # concurrent Render `airport_ticketing_tick` (AIRPORT_TICKETING_BRIDGE_ENABLED on)
    # must never fetch/ticket a harness row, regardless of whether the harness's own
    # process-local sandbox monkeypatch is active. Excluding them here — the one
    # production fetch that feeds run_tick — makes them permanently un-ticketable in
    # prod. The harness's OWN tick opts back in (include_synthetic=True) to drive its
    # rows through the real spine. Filtering the already-unioned set covers BOTH the
    # keyword and the participant lanes in one place.
    if not include_synthetic:
        rows = [
            r for r in rows
            if not str((r[0] if r else "") or "").startswith(_C3_GATE_SYNTHETIC_PREFIX)
        ]

    message_ids = [row[0] for row in rows if row and row[0]]
    attachment_map = _fetch_email_attachments(conn, message_ids)
    arrivals: list[EmailArrival] = []
    for row in rows:
        received = row[6]
        if isinstance(received, datetime) and received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        arrivals.append(
            EmailArrival(
                message_id=str(row[0] or ""),
                thread_id=str(row[1] or row[0] or ""),
                sender_name=str(row[2] or ""),
                sender_email=str(row[3] or ""),
                subject=str(row[4] or ""),
                full_body=str(row[5] or ""),
                received_date=received if isinstance(received, datetime) else None,
                source=str(row[7] or ""),
                attachments=tuple(attachment_map.get(str(row[0] or ""), ())),
                participant_fetched=str(row[0] or "") in participant_only_ids,
            )
        )
    return arrivals


def _fetch_email_attachments(conn: Any, message_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not message_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT message_id, filename, mime_type, size_bytes
            FROM email_attachments
            WHERE message_id = ANY(%s)
            ORDER BY message_id, filename
            """,
            (message_ids,),
        )
        rows = cur.fetchall()
    out: dict[str, list[dict[str, Any]]] = {}
    for message_id, filename, mime_type, size_bytes in rows:
        out.setdefault(str(message_id), []).append(
            {"filename": filename, "mime_type": mime_type, "size_bytes": size_bytes}
        )
    return out


def reserve_ticket(conn: Any, ticket: AirportTicket) -> dict[str, Any]:
    payload = ticket.payload()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, bus_message_id
            FROM airport_tickets
            WHERE dedup_key = %s
            LIMIT 1
            """,
            (ticket.dedup_key,),
        )
        existing = cur.fetchone()
        if existing:
            status = existing[1]
            bus_message_id = existing[2]
            if status == "failed" and bus_message_id is None:
                cur.execute(
                    """
                    UPDATE airport_tickets
                    SET status = 'candidate',
                        ticket = %s,
                        failure_reason = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (_json_param(payload), existing[0]),
                )
                row = cur.fetchone()
                return {"reserved": True, "id": row[0], "retry": True}
            return {
                "reserved": False,
                "id": existing[0],
                "status": status,
                "bus_message_id": bus_message_id,
            }

        cur.execute(
            """
            INSERT INTO airport_tickets
                (ticket_id, dedup_key, source_channel, source_id, source_received_at,
                 originator, suspected_matter_slug, suspected_flight,
                 proposed_desk_slug, urgency_hint, ticket, thread_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                ticket.ticket_id,
                ticket.dedup_key,
                ticket.source_channel,
                ticket.source_id,
                ticket.source_received_at,
                ticket.originator,
                ticket.suspected_matter_slug,
                ticket.suspected_flight,
                ticket.proposed_desk_slug,
                ticket.urgency_hint,
                _json_param(payload),
                # NULL when unset (non-email channels); the failed-row retry path above
                # never touches thread_id (the original INSERT already set it).
                ticket.thread_id or None,
            ),
        )
        row = cur.fetchone()
        if not row:
            return {"reserved": False, "id": None}
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                "airport_ticket.created",
                ticket.ticket_id,
                _json_param(
                    {
                        "ticket_id": ticket.ticket_id,
                        "source_channel": ticket.source_channel,
                        "source_id": ticket.source_id,
                        "proposed_desk_slug": ticket.proposed_desk_slug,
                    }
                ),
                "airport_ticketing_bridge",
            ),
        )
    return {"reserved": True, "id": row[0]}


def _bridge_key() -> str:
    return (
        os.environ.get(_KEY_ENV, "").strip()
        or os.environ.get("BRISEN_LAB_TERMINAL_KEY_TICKETING", "").strip()
        or os.environ.get("BRISEN_LAB_TERMINAL_KEY_DISPATCHER", "").strip()
        or os.environ.get("BRISEN_LAB_TERMINAL_KEY", "").strip()
    )


def _request_json(
    method: str,
    url: str,
    *,
    key: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: int = 15,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-Terminal-Key": key}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return {"ok": False, "error": f"http_{e.code}", "body": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _bus_message_id(result: dict[str, Any]) -> Optional[int]:
    for key in ("id", "message_id", "event_id"):
        value = result.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    event = result.get("event")
    if isinstance(event, dict) and event.get("id") is not None:
        try:
            return int(event["id"])
        except (TypeError, ValueError):
            return None
    message = result.get("message")
    if isinstance(message, dict) and message.get("id") is not None:
        try:
            return int(message["id"])
        except (TypeError, ValueError):
            return None
    return None


def format_ticket_for_bus(ticket: AirportTicket) -> str:
    luggage = "\n".join(f"- {item}" for item in ticket.luggage) or "- none"
    why = "\n".join(f"- {item}" for item in ticket.why_ticketed) or "- none"
    limits = "\n".join(f"- {item}" for item in ticket.known_limits) or "- none"
    return (
        f"TO: {ticket.proposed_desk_slug}\n"
        "FROM: ticketing-desk\n"
        f"RE: AIRPORT_TICKET {ticket.suspected_flight}\n\n"
        "AIRPORT_TICKET v1\n"
        f"ticket_id: {ticket.ticket_id}\n"
        f"created_at: {ticket.created_at.isoformat()}\n"
        f"source_channel: {ticket.source_channel}\n"
        f"source_id: {ticket.source_id}\n"
        f"originator: {ticket.originator}\n"
        f"suspected_matter_slug: {ticket.suspected_matter_slug}\n"
        f"suspected_flight: {ticket.suspected_flight}\n"
        f"proposed_desk_slug: {ticket.proposed_desk_slug}\n"
        f"urgency_hint: {ticket.urgency_hint}\n"
        "luggage:\n"
        f"{luggage}\n"
        "why_ticketed:\n"
        f"{why}\n"
        "known_limits:\n"
        f"{limits}\n\n"
        "Check-in required: reply with VALID, FAKE, DUPLICATE, WRONG_TERMINAL, "
        "URGENT, or NEEDS_LUGGAGE_READ."
    )


def post_ticket_to_bus(ticket: AirportTicket) -> dict[str, Any]:
    recipient = resolve_owner_slug(ticket.proposed_desk_slug)
    if not recipient or recipient in RESERVED_RECIPIENTS:
        return {"ok": False, "error": "invalid_recipient"}
    key = _bridge_key()
    if not key:
        return {"ok": False, "error": "ticketing_key_missing"}
    base = os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")
    payload = {
        "kind": "dispatch",
        "body": format_ticket_for_bus(ticket),
        "to": [recipient],
        "tier_required": "B",
        "topic": f"airport-ticketing/{ticket.suspected_flight}",
    }
    result = _request_json("POST", f"{base}/msg/{recipient}", key=key, payload=payload)
    if result.get("error"):
        return result
    result["ok"] = True
    return result


def mark_ticket_sent(
    conn: Any,
    *,
    ticket: AirportTicket,
    ticket_row_id: int,
    bus_message_id: Optional[int],
    bus_thread_id: Optional[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE airport_tickets
            SET status = 'sent',
                bus_message_id = %s,
                bus_thread_id = %s,
                last_sent_at = NOW(),
                failure_reason = NULL,
                updated_at = NOW()
            WHERE id = %s
            """,
            (bus_message_id, bus_thread_id, ticket_row_id),
        )
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES (%s, %s, %s, %s, TRUE)
            """,
            (
                "airport_ticket.bus_sent",
                ticket.ticket_id,
                _json_param(
                    {
                        "ticket_id": ticket.ticket_id,
                        "bus_message_id": bus_message_id,
                        "bus_thread_id": bus_thread_id,
                        "proposed_desk_slug": ticket.proposed_desk_slug,
                    }
                ),
                "airport_ticketing_bridge",
            ),
        )


def mark_ticket_failed(
    conn: Any,
    *,
    ticket: AirportTicket,
    ticket_row_id: int,
    error: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE airport_tickets
            SET status = 'failed',
                failure_reason = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (error[:500], ticket_row_id),
        )
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success, error_message)
            VALUES (%s, %s, %s, %s, FALSE, %s)
            """,
            (
                "airport_ticket.bus_failed",
                ticket.ticket_id,
                _json_param({"ticket_id": ticket.ticket_id, "error": error[:500]}),
                "airport_ticketing_bridge",
                error[:500],
            ),
        )


def issue_ticket(ticket: AirportTicket, conn: Any) -> dict[str, Any]:
    reserved = reserve_ticket(conn, ticket)
    if not reserved.get("reserved"):
        return {"skipped": True, "reason": "duplicate", "id": reserved.get("id")}
    ticket_row_id = int(reserved["id"])
    result = post_ticket_to_bus(ticket)
    if not result.get("ok"):
        error = str(result.get("error") or "unknown")
        mark_ticket_failed(conn, ticket=ticket, ticket_row_id=ticket_row_id, error=error)
        return {"ok": False, "reason": "bus_failed", "error": error}

    message_id = _bus_message_id(result)
    mark_ticket_sent(
        conn,
        ticket=ticket,
        ticket_row_id=ticket_row_id,
        bus_message_id=message_id,
        bus_thread_id=result.get("thread_id"),
    )
    return {"ok": True, "id": ticket_row_id, "bus_message_id": message_id}


def write_terminal_status(
    conn: Any,
    *,
    ticket_row_id: int,
    terminal_status: str,
    terminal_reason: str,
    raw_source_id: str,
    matter_slug: Optional[str] = None,               # NEW (BRIEF-E) routing columns —
    desk_owner: Optional[str] = None,                # appended to the SET clause ONLY
    manifest_match_signals: Optional[list] = None,   # when non-None (JSONB via _json_param)
    confidence: Optional[float] = None,              # NUMERIC(3,2), 0.00-1.00
) -> bool:
    """Single idempotent terminal write — the ONLY path that writes terminal_status.

    Returns True iff THIS call wrote the terminal outcome (rowcount == 1). The
    ``AND terminal_status IS NULL`` guard makes re-runs and lease-expired reclaims
    no-ops (0 rows). dedup_key UNIQUE guards duplicate ROWS; this guards duplicate
    terminal WRITES. Caller wraps in a per-row try/except + rollback.

    BRIEF-E adds four OPTIONAL routing kwargs appended to the SET clause ONLY when
    non-None, so C's and D's existing callers (which pass none) produce byte-identical
    SQL and write NO routing column. The routing columns ride INSIDE this one status-
    guarded UPDATE (never a second unguarded write), so they are never written outside
    the ``terminal_status IS NULL`` guard.
    """
    cur = conn.cursor()
    try:
        # Fixed base SET fragments (unchanged from C). With no routing kwargs the
        # generated SQL + params are byte-identical to C's original statement.
        set_parts = [
            "terminal_status = %s",
            "terminal_reason = %s",
            "processed_at = NOW()",
            "terminal_outcome_written_at = NOW()",
            "raw_source_table = 'email_messages'",
            "raw_source_id = %s",
        ]
        params: list = [terminal_status, terminal_reason, raw_source_id]
        # Each appended fragment is a fixed literal with a %s placeholder — no data
        # is interpolated into SQL text, so the dynamic clause is injection-safe.
        if matter_slug is not None:
            set_parts.append("matter_slug = %s")
            params.append(matter_slug)
        if desk_owner is not None:
            set_parts.append("desk_owner = %s")
            params.append(desk_owner)
        if manifest_match_signals is not None:
            set_parts.append("manifest_match_signals = %s")
            params.append(_json_param(manifest_match_signals))  # JSONB column
        if confidence is not None:
            set_parts.append("confidence = %s")
            params.append(confidence)  # NUMERIC(3,2) — a 0.00-1.00 float fits
        params.append(ticket_row_id)
        cur.execute(
            "UPDATE airport_tickets SET "
            + ", ".join(set_parts)
            + " WHERE id = %s AND terminal_status IS NULL RETURNING id, ticket_id",
            params,
        )
        won = cur.fetchone()
        if won is None:
            return False
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES ('airport_ticket.terminal_written', %s, %s,
                    'airport_ticketing_bridge', TRUE)
            """,
            (
                won[1],
                _json_param(
                    {
                        "ticket_id": won[1],
                        "terminal_status": terminal_status,
                        "terminal_reason": terminal_reason,
                    }
                ),
            ),
        )
        return True
    finally:
        cur.close()


def _claim_for_terminal(
    conn: Any, ticket_row_id: int
) -> Optional[tuple[int, Optional[str]]]:
    """Intra-tick row claim under FOR UPDATE SKIP LOCKED.

    Returns ``None`` when the row is held by a concurrent overlapping tick (SKIP
    LOCKED skipped it) or is missing — the caller treats that as ``lease_skipped``
    and must NOT advance the watermark past the arrival (it is not ours to finish).

    Returns ``(id, existing_terminal_status)`` when THIS tick holds the row lock:
      - ``existing_terminal_status is None`` -> we won a fresh row, proceed to write.
      - ``existing_terminal_status is not None`` -> already terminal on a prior tick;
        the arrival is idempotently DONE, no write needed, safe to advance past it.

    The terminal_status is read here (NOT filtered in the WHERE) precisely so
    already-terminal is distinguishable from locked — otherwise a re-fetched,
    already-cleared row would look identical to a concurrently-held one and pin the
    watermark forever. Single-replica is inherited from scheduler_lease 8800100 —
    this is row-level overlap safety only, NOT a process lease."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, terminal_status
              FROM airport_tickets
             WHERE id = %s
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """,
            (ticket_row_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return (int(row[0]), row[1])
    finally:
        cur.close()


def reserve_noise_row(conn: Any, arrival: EmailArrival) -> Optional[int]:
    """Shape (i): reserve a minimal airport_tickets row for a REJECT_NOISE arrival
    (build_email_ticket returned None) so the single status-guarded terminal write
    has a target. Keyed by dedup_key on the noise sentinel desk, so repeated noise
    de-dups and the terminal write stays idempotent. Returns the row id, or None if
    no id could be obtained (caller skips, never crashes)."""
    dedup = _dedup_key("email", arrival.message_id, _NOISE_DESK)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO airport_tickets
                (ticket_id, dedup_key, source_channel, source_id,
                 source_received_at, proposed_desk_slug)
            VALUES (%s, %s, 'email', %s, %s, %s)
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                f"airport-noise:{arrival.message_id}",
                dedup,
                arrival.message_id,
                arrival.received_date,
                _NOISE_DESK,
            ),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        # dedup collision (already reserved on a prior tick) -> fetch the existing id.
        cur.execute(
            "SELECT id FROM airport_tickets WHERE dedup_key = %s LIMIT 1",
            (dedup,),
        )
        existing = cur.fetchone()
        return int(existing[0]) if existing else None
    finally:
        cur.close()


def _ingest_outbound_signal(conn: Any, arrival: EmailArrival) -> bool:
    """BOX5_OUTBOUND_INGEST_1 flag-ON capture. Persist ONE direction='outbound'
    airport_tickets row (deduped by dedup_key so a re-tick is idempotent) and log
    EXACTLY ONE 'airport_ticket.outbound_signal' baker_action. Outbound NEVER boards
    a desk (no bus post / no mark_ticket_sent -> the row stays status='candidate',
    invisible to the check-in reader's status='sent' nudge + escalation sweep),
    never nudges, never enters D's / E's fast-soft lanes.

    Returns True when THIS call captured a NEW row (+ logged its single action),
    False on an idempotent re-tick (row already reserved on a prior tick -> no
    second action). Does NOT commit — the caller owns the per-row commit. Any
    exception propagates to the caller's per-row handler (rollback + failed++),
    never a silent clear."""
    dedup = _dedup_key("email", arrival.message_id, _OUTBOUND_DESK)
    ticket_id = f"airport-outbound:{arrival.message_id}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO airport_tickets
                (ticket_id, dedup_key, source_channel, source_id,
                 source_received_at, proposed_desk_slug, direction)
            VALUES (%s, %s, 'email', %s, %s, %s, 'outbound')
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                ticket_id,
                dedup,
                arrival.message_id,
                arrival.received_date,
                _OUTBOUND_DESK,
            ),
        )
        row = cur.fetchone()
        if row is None:
            # Already captured on a prior tick — idempotent, no second action.
            return False
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, payload, trigger_source, success)
            VALUES ('airport_ticket.outbound_signal', %s, %s,
                    'airport_outbound_ingest', TRUE)
            """,
            (
                ticket_id,
                _json_param(
                    {
                        "sender": (arrival.sender_email or ""),
                        "subject": (arrival.subject or "")[:200],
                        "thread_id": arrival.thread_id,
                        "message_id": arrival.message_id,
                        "received_at": (
                            arrival.received_date.isoformat()
                            if arrival.received_date
                            else None
                        ),
                        "direction": "outbound",
                    }
                ),
            ),
        )
    return True


def _count_stuck_arrivals(conn: Any) -> int:
    """Journey gauge (NOT scheduler liveness): arrivals that never reached a
    terminal disposition. source_received_at is a real existing column."""
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT COUNT(*)
              FROM airport_tickets
             WHERE terminal_status IS NULL
               -- Captured OUTBOUND rows are terminal-by-design (no desk journey, so
               -- terminal_status stays NULL forever); they are NOT stuck. Exclude
               -- them so the journey gauge counts only genuinely-stalled inbound
               -- arrivals. (BOX5_OUTBOUND_INGEST_1.)
               AND direction <> 'outbound'
               AND source_received_at < NOW() - (%s || ' minutes')::interval
            """,
            (_STUCK_ARRIVAL_MINUTES,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        cur.close()


def _advance(cur_max: Optional[datetime], candidate: Optional[datetime]) -> Optional[datetime]:
    """Track the max received_date processed this tick (UTC-coerced)."""
    if candidate is None:
        return cur_max
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    if cur_max is None or candidate > cur_max:
        return candidate
    return cur_max


def resolve_by_thread(thread_id: str) -> Optional[dict]:
    """THREAD_CONTINUITY_ROUTING_1 — strong-signal thread-continuity resolver.

    Return the single active project a prior CODE-BOUND ticket on this email thread
    was routed to, so a code-less reply on a thread already bound to a matter inherits
    that matter — restoring the recall the routing reversal (#446) removed WITHOUT
    reviving unsafe name/alias matching. Thread identity is a strong signal (this
    mirrors the outbound connector's own bus_thread_id continuity).

    Inherit ONLY from a hard/code-bound prior disposition — D's FAST_TICKET
    (``_HARD_LANE_REASON_PREFIX``) or E's explicit-code routed TICKET
    (``_CODE_ROUTED_REASON_PREFIX``). Both were driven by an explicit registered
    ACTIVE project code; neither is a soft guess. A soft / alias / participant-only
    match and the (f) safe-default desk ticket are excluded, so continuity can never
    launder a weak binding forward (the load-bearing safety rule).

    Returns None when: no thread id; no prior code-bound ticket on the thread; the
    bound project is no longer registered/active (a since-retired binding is not
    inherited — the registry is re-checked as the source of truth); OR the thread
    carries code-bound tickets to >1 distinct ACTIVE project (a legitimately
    multi-matter thread) -> CONFLICT, so the caller falls through to a full desk
    TICKET, never a silent cross-matter pick.

    Opens its OWN connection (mirrors resolve_project_number / resolve_by_participant)
    so a failure here can never abort the shared tick transaction, and reads only
    COMMITTED prior tickets — exactly what continuity needs.
    """
    if not thread_id:
        return None
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # DISTINCT reasons for code-bound terminal rows on this thread. The
                # terminal_reason prefix — NOT terminal_status — is the discriminator:
                # the (f) safe default is ALSO status='TICKET', so filtering on status
                # alone would launder it in. LIMIT bounds a pathologically long thread.
                cur.execute(
                    """
                    SELECT DISTINCT terminal_reason
                    FROM airport_tickets
                    WHERE thread_id = %s
                      AND terminal_status IN ('FAST_TICKET', 'TICKET')
                      AND (terminal_reason LIKE %s OR terminal_reason LIKE %s)
                    LIMIT 200
                    """,
                    (
                        thread_id,
                        _HARD_LANE_REASON_PREFIX + "%",
                        _CODE_ROUTED_REASON_PREFIX + "%",
                    ),
                )
                rows = cur.fetchall()
    except Exception as e:
        logger.warning("resolve_by_thread query failed: %s", e)
        return None

    # Extract the bound project number from each code-bound reason (both prefixes
    # embed the canonical PN after the final ':'; a canonical PN contains no ':').
    codes: list[str] = []
    seen: set[str] = set()
    for (reason,) in rows:
        if not reason:
            continue
        pn = reason.rsplit(":", 1)[-1].strip()
        if pn and pn not in seen:
            seen.add(pn)
            codes.append(pn)
    if not codes:
        return None

    # Re-resolve each via the registry (source of truth), keeping ONLY still-ACTIVE
    # projects. Exactly 1 distinct active project -> inherit it; 0 -> nothing to
    # inherit (all bindings since retired); >1 -> the thread spans matters -> CONFLICT.
    active: dict[str, dict] = {}
    for pn in codes:
        resolved = resolve_project_number(pn)  # registry, ACTIVE-only; None if retired/unregistered
        if resolved is not None:
            active[resolved["project_number"]] = resolved
    if len(active) != 1:
        return None
    return next(iter(active.values()))


def _run_nonmail_lane(
    conn: Any,
    *,
    source_label: str,
    fetch_fn,
    build_fn,
    watermark_source: str,
    current: datetime,
    cap: int,
    dry_run: bool,
    suppress_fn=None,
) -> dict[str, int]:
    """BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — process ONE non-mail source (plaud/whatsapp)
    into candidate desk-review tickets. Mirrors the email lane's contiguous-prefix
    watermark discipline but WITHOUT the email routing lanes: a non-mail match is always a
    candidate ticket via issue_ticket, never a fast-board (brief design pt 1 — participant
    match alone routes to desk review). Own per-source watermark (never the email cursor).
    Dry-run LOGS would-be tickets and advances NOTHING (Rule 11c preview-first).

    suppress_fn (optional, task 6): predicate (arrival, now) -> bool. When it returns
    True the arrival is intentionally NOT ticketed but IS treated as fully handled, so the
    contiguous-prefix watermark ADVANCES past it (never re-fetched/re-ticketed next tick).
    Distinct from a build_fn None, which means desk-misconfig and HOLDS the cursor."""
    issued = skipped = failed = suppressed = 0
    watermark_candidate: Optional[datetime] = None
    contiguous = True

    floor = current - timedelta(hours=nonmail_lookback_hours())
    try:
        raw_wm = trigger_state_watermark_raw(watermark_source)
    except Exception as e:
        logger.warning(
            "airport nonmail %s watermark read failed, using floor: %s", source_label, e
        )
        raw_wm = None
    since = floor if raw_wm is None else max(raw_wm, floor)

    try:
        arrivals = fetch_fn(conn, since=since, limit=cap * 4)
    except Exception as e:
        logger.warning("airport nonmail %s fetch failed: %s", source_label, e)
        return {"issued": 0, "skipped": 0, "failed": 0, "suppressed": 0}

    for arrival in arrivals:
        if issued >= cap:
            # Cap reached: this + every newer arrival stay re-fetchable (freeze cursor).
            contiguous = False
            break
        done = False
        try:
            if suppress_fn is not None and suppress_fn(arrival, current):
                # Task 6: identity-only WA arrival, config-suppressed. NOT ticketed, but
                # fully handled — advance the cursor past it so it is never re-fetched /
                # re-ticketed next tick (the stored whatsapp_messages row is untouched:
                # store-everything). Under dry-run, advance nothing (preview-first).
                if dry_run:
                    logger.info(
                        "AIRPORT_NONMAIL_DRY_RUN would suppress %s id=%s (identity-only)",
                        source_label,
                        getattr(
                            arrival,
                            "message_id",
                            getattr(arrival, "transcript_id", "?"),
                        ),
                    )
                    skipped += 1
                    done = False
                else:
                    suppressed += 1
                    done = True
            else:
                # AO_FLIGHT_PROD_TICKET_ROUTING_1: pass the tick's conn so the Plaud builder
                # can resolve the per-matter desk from project_registry on the open txn (WA
                # accepts + ignores it — stays global this brief).
                ticket = build_fn(arrival, now=current, conn=conn)
                if ticket is None:
                    # Fetch guarantees a match, so a None here is a desk misconfig only —
                    # hold the cursor, never silently advance past it.
                    skipped += 1
                    done = False
                elif dry_run:
                    logger.info(
                        "AIRPORT_NONMAIL_DRY_RUN would ticket %s dedup=%s desk=%s",
                        source_label,
                        ticket.dedup_key,
                        ticket.proposed_desk_slug,
                    )
                    skipped += 1
                    done = False  # preview-only: never advance the watermark
                else:
                    result = issue_ticket(ticket, conn)
                    if result.get("ok"):
                        issued += 1
                        conn.commit()
                        done = True
                    elif result.get("skipped") and result.get("reason") == "duplicate":
                        # Already ticketed on a prior tick — idempotent no-op, DONE.
                        conn.commit()
                        done = True
                    elif not result.get("ok") and result.get("reason") == "bus_failed":
                        # BUS-FAIL = FAILURE: mark_ticket_failed persisted, cursor frozen
                        # so issue_ticket retries it next tick (never a silent drop).
                        failed += 1
                        conn.commit()
                        done = False
                    else:
                        # Reserve race / no id — not ours to finish, hold the cursor.
                        conn.commit()
                        done = False
        except Exception as exc:  # ERROR NEVER AUTO-CLEARS
            try:
                conn.rollback()
            except Exception:
                pass
            failed += 1
            done = False
            logger.warning("airport nonmail %s row failed: %s", source_label, exc)

        if not done:
            contiguous = False
        elif contiguous:
            watermark_candidate = _advance(watermark_candidate, arrival.received_at)

    if watermark_candidate is not None and not dry_run:
        try:
            trigger_state_set_watermark(watermark_source, watermark_candidate)
        except Exception as e:
            logger.warning(
                "airport nonmail %s watermark advance failed: %s", source_label, e
            )

    return {
        "issued": issued,
        "skipped": skipped,
        "failed": failed,
        "suppressed": suppressed,
    }


def run_tick(*, now: Optional[datetime] = None) -> dict[str, Any]:
    # (a) MASTER GATE — ships dark behind AIRPORT_TICKETING_BRIDGE_ENABLED.
    if not bridge_enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    cap = max_posts_per_tick()
    if cap <= 0:
        return {"skipped": True, "reason": f"{_MAX_POSTS_ENV}=0"}

    try:
        from memory.store_back import SentinelStoreBack

        store = SentinelStoreBack._get_global_instance()
    except Exception as e:
        logger.warning("airport ticketing store unavailable: %s", e)
        return {"skipped": True, "reason": "store_unavailable"}

    conn = store._get_conn()
    if not conn:
        return {"skipped": True, "reason": "database_unavailable"}

    # existing counters + NEW journey counters
    issued = skipped = failed = 0
    claimed = terminal_written = lease_skipped = 0
    deterministic_cleared = defaulted_ticket = 0
    fast_ticket = 0  # BRIEF-D hard fast lane; not a deterministic_cleared/defaulted_ticket
    code_routed_ticket = 0  # explicit-code routed TICKET, not FAST_TICKET/defaulted
    thread_routed_ticket = 0  # thread-continuity routed TICKET (inherited code-bound thread)
    outbound_signal = 0  # BOX5_OUTBOUND_INGEST_1 flag-ON captures; never boards a desk
    fast_lane = fast_lane_enabled()  # honored now; only future-proofs D/E
    current = now or _utc_now()
    # (P1-A) CONTIGUOUS-PREFIX WATERMARK. The cursor may only advance over the
    # unbroken run of fully-processed arrivals from the oldest. `contiguous` flips
    # False at the first arrival that is NOT fully done (failure, bus-fail, lease
    # skip, reserve race, cap break); once False the watermark stops advancing so
    # every arrival at/after the gap stays re-fetchable next tick. NEVER a global
    # max — that is the P1-A/P1-B data-loss class codex flagged.
    watermark_candidate: Optional[datetime] = None
    contiguous = True
    try:
        ensure_airport_ticket_table(conn)  # idempotent; also ensures BRIEF-B terminal cols
        # BOX5_DROP_OBSERVABILITY_1 — bootstrap the drop-log (fault-tolerant: never
        # raises, so a drop-log infra hiccup can't abort the ticketing tick).
        ensure_box5_dropped_signals_table(conn)

        # (b) CURSOR — per-source watermark replaces the constant lookback. Keep the
        #     lookback as a FLOOR so a fresh/blank cursor cannot scan unbounded. The
        #     watermark uses a DISTINCT key, never the live email poll.
        #
        #     (P1 blank-cursor) On FIRST activation there is NO watermark row.
        #     trigger_state.get_watermark would return its NOW-24h fallback, and
        #     max(NOW-24h, floor=NOW-lookback) collapses to NOW-24h whenever the
        #     lookback exceeds 24h (default 48h) — so the 24h→lookback backlog is
        #     skipped before the first advance and stranded forever. Read the RAW row:
        #       - None (missing OR DB error) -> start at the full lookback FLOOR (safe
        #         over-scan; the status-guard + dedup make the re-scan idempotent).
        #       - a real cursor -> max(wm, floor) so we never rewind past the window.
        floor = current - timedelta(hours=lookback_hours())
        try:
            raw_wm = trigger_state_watermark_raw(_WATERMARK_SOURCE)
        except Exception as e:
            logger.warning("airport ticketing watermark read failed, using floor: %s", e)
            raw_wm = None
        since = floor if raw_wm is None else max(raw_wm, floor)

        arrivals = fetch_email_arrivals(conn, since=since, limit=cap * 4)

        for arrival in arrivals:
            if issued >= cap:
                # (P1-A) Cap reached: this arrival + every newer one (ASC order) are
                # UN-processed. They must stay re-fetchable, so the contiguous prefix
                # ends here — never advance the watermark past an un-processed row.
                contiguous = False
                break

            # `done` = this arrival reached a definite terminal disposition this tick
            # (cleared / ticketed / idempotent no-op). Only a done arrival at the head
            # of an unbroken run advances the cursor. Anything not done freezes it.
            done = False

            # (b.5) OUTBOUND SHORT-CIRCUIT — direction-aware ingestion
            #   (BOX5_OUTBOUND_INGEST_1, Director ruling 2026-07-01). The WHOLE block is
            #   gated behind AIRPORT_OUTBOUND_INGEST_ENABLED so a merge is a PURE no-op
            #   (lead #4837):
            #     OFF (dark) -> the block is skipped entirely (the `and` short-circuits
            #            before classify), so EVERY arrival — inbound AND outbound-sender
            #            — flows through the unchanged inbound path below, byte-identical
            #            to pre-change (no drop, cursor + lane behavior untouched). The
            #            skip + capture go live together only when the flag flips.
            #     ON   -> an outbound-sender arrival is classified out BEFORE
            #            build_email_ticket + every lane, so it NEVER boards a desk,
            #            nudges, or enters D's / E's fast-soft lanes: it captures ONE
            #            direction='outbound' row + one action-evidence signal (no bus /
            #            no desk) instead. Own fault isolation mirrors the per-row try —
            #            a throw rolls back, counts failed, and FREEZES the cursor (retry
            #            next tick), never a silent clear.
            #   The `continue` skips the inbound try + the shared (P1-A) cursor block at
            #   the end of the loop, so the two cursor-advance lines are replicated here
            #   and MUST stay in lock-step with that block.
            if (
                _outbound_ingest_enabled()
                and _classify_direction(arrival.sender_email) == "outbound"
            ):
                try:
                    if _ingest_outbound_signal(conn, arrival):
                        outbound_signal += 1
                    # (b.5-2) BOX5_OUTBOUND_INGEST_2 — drive the captured outbound
                    #   signal through the ratification connector (event state machine
                    #   -> ClickUp timetable write -> RECORD-ONLY flight progression) in
                    #   the SAME transaction as the capture, so they commit atomically.
                    #   Routine outbound stays evidence-only. A ClickUp API failure is
                    #   caught INSIDE the connector and recorded as ERROR_RETRY
                    #   (terminal=False) — never re-raised — so this row is retried next
                    #   tick and the email cursor never silently drops the event (AC10).
                    #   Lazy-imported so this whole (b.5) block stays gated behind the
                    #   flag (flag-off = byte-identical, AC1) and my bridge edits stay
                    #   inside the outbound branch (b3 owns the E lane in parallel).
                    from orchestrator import airport_outbound_connector as _obc

                    result = _obc.process_outbound_event(conn, arrival)
                    conn.commit()
                    done = bool(result.get("terminal", True))
                except Exception as exc:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    failed += 1
                    done = False
                    logger.warning(
                        "airport_ticketing outbound row failed: %s", exc
                    )
                if not done:
                    contiguous = False
                elif contiguous:
                    watermark_candidate = _advance(
                        watermark_candidate, arrival.received_date
                    )
                continue

            # (c) PER-ROW FAULT ISOLATION — one bad row never crashes the tick, and
            #     an exception NEVER auto-clears (blocker D3): it routes to `failed`,
            #     never to a deterministic clear, and never advances the cursor.
            try:
                ticket = build_email_ticket(arrival, now=current)

                if ticket is None:
                    # (d) DETERMINISTIC CLEAR — REJECT_NOISE = AUTOMATED SENDER ONLY.
                    #     (P1-C, cowork-ah1 bus #4756) build_email_ticket returns None
                    #     for an automated sender OR a no-active-keyword arrival, but a
                    #     None here is still automated-sender ONLY. The keyword lane only
                    #     fetches keyword matches; the participant lane
                    #     (BOX5_GATE2_PARTICIPANT_FETCH_LANE_1) DOES fetch no-keyword
                    #     arrivals, but build_email_ticket tickets those on participant
                    #     identity (participant_fetched=True) instead of returning None —
                    #     so a no-keyword arrival never reaches this branch. We assert that
                    #     cause explicitly rather than infer it, so REJECT_NOISE means
                    #     automated-sender ONLY. (Broader feed-widening — "every arrival
                    #     ends visible" regardless of sender — is a deferred follow-up
                    #     brief; do NOT broaden the fetch scan here.)
                    if _is_automated_email_arrival(arrival):
                        noise_id = reserve_noise_row(conn, arrival)
                        if noise_id is not None:
                            if write_terminal_status(
                                conn,
                                ticket_row_id=noise_id,
                                terminal_status="REJECT_NOISE",
                                terminal_reason="automated_sender",
                                raw_source_id=arrival.message_id,
                            ):
                                terminal_written += 1
                                deterministic_cleared += 1
                            skipped += 1
                            conn.commit()
                            done = True
                        else:
                            # No target row could be reserved (transient) — do NOT
                            # clear, do NOT advance; retry next tick.
                            conn.rollback()
                            skipped += 1
                    else:
                        # Defensive: a None that is NOT an automated sender (only the
                        # dead no-keyword path or an invalid-desk misconfig) must
                        # never auto-clear (blocker D3). Surface + hold, do NOT advance.
                        conn.rollback()
                        skipped += 1
                        logger.warning(
                            "airport_ticketing: non-automated None ticket held (not "
                            "cleared): %s",
                            arrival.message_id,
                        )
                else:
                    # (e) RESERVE — DUPLICATE deterministic clear via dedup collision.
                    result = issue_ticket(ticket, conn)
                    row_id = result.get("id")

                    if (
                        result.get("skipped")
                        and result.get("reason") == "duplicate"
                        and row_id
                    ):
                        claim = _claim_for_terminal(conn, row_id)
                        if claim is None:
                            # Held by a concurrent tick — not ours; hold the cursor.
                            lease_skipped += 1
                            conn.commit()
                        elif claim[1] is not None:
                            # Already terminal on a prior tick — idempotent no-op, DONE.
                            conn.commit()
                            done = True
                        else:
                            claimed += 1
                            if write_terminal_status(
                                conn,
                                ticket_row_id=row_id,
                                terminal_status="DUPLICATE",
                                terminal_reason="dedup_key_collision",
                                raw_source_id=arrival.message_id,
                            ):
                                terminal_written += 1
                                deterministic_cleared += 1
                            skipped += 1
                            conn.commit()
                            done = True

                    # (P1-B) BUS-FAIL = FAILURE — checked BEFORE the not-row_id branch.
                    #     issue_ticket bus_failed returns ok=False with NO id; the old
                    #     code hit `not row_id` first and mis-counted it as lease_skipped
                    #     while the watermark advanced -> silent drop. It is a FAILURE:
                    #     terminal_status stays NULL, `failed` increments, the cursor
                    #     does NOT advance past it, and reserve_ticket retries it next
                    #     tick.
                    elif not result.get("ok") and result.get("reason") == "bus_failed":
                        failed += 1
                        conn.commit()  # persist mark_ticket_failed (status='failed' + audit)

                    # (f) None row_id (reserve race: another tick won ON CONFLICT) —
                    #     no-op, never a crash, NOT ours to finish, so hold the cursor.
                    elif not row_id:
                        lease_skipped += 1
                        conn.commit()

                    else:
                        # (e.5) HARD FAST LANE — project-number fast-board (BRIEF-D).
                        #   Gated on C's precomputed `fast_lane` local (BOX5_FAST_LANE_
                        #   ENABLED, default false). FAST_TICKET requires ALL of: exactly
                        #   1 distinct code; a registered ACTIVE row; the sender bound to
                        #   THAT project's participant set. Any conflict / no-code /
                        #   no-row / no-binding / exception -> fall through to (f) TICKET
                        #   (never the deferred hold state, never FAST_TICKET on a miss).
                        #   #4679.2/.3 + #4680.1
                        #   + blocker-D3. `handled` True = D disposed of the row (a clean
                        #   FAST_TICKET, an idempotent re-tick, or a lease-skip) and
                        #   suppresses the (f) TICKET write below.
                        handled = False
                        if fast_lane and row_id:
                            try:
                                # (P1 G3-rework) SAVEPOINT FIRST — before any D work but
                                #   AFTER issue_ticket's row reservation (~L1126, still
                                #   uncommitted in this shared tick txn). A D failure must
                                #   roll back ONLY D's partial work and PRESERVE that
                                #   reservation so the (f) TICKET fallback below still finds
                                #   the row via _claim_for_terminal. The prior full
                                #   conn.rollback() in the except destroyed the reservation
                                #   -> fallback found NO row -> lease_skipped -> the arrival
                                #   was STRANDED with no terminal outcome (violates
                                #   blocker-D3 + the every-arrival-ends-visible spine).
                                with conn.cursor() as _sp:
                                    _sp.execute("SAVEPOINT airport_hard_lane")
                                hl_text = f"{arrival.subject} {arrival.full_body}"
                                codes = extract_project_codes(hl_text)
                                # >1 distinct code = cross-matter CONFLICT (F4) -> TICKET;
                                # 0 codes -> no code -> TICKET. Only exactly-1 proceeds.
                                if len(set(codes)) == 1:
                                    # Regex shape alone NEVER clears (#4679.3): the code
                                    # must resolve to a registered ACTIVE row.
                                    resolved = resolve_project_number(hl_text)
                                    if resolved is not None:
                                        pn = resolved["project_number"]
                                        # Binding mandatory (#4679.2/#4680.1): the sender
                                        # must be in THIS project's participant set.
                                        # FAST_TICKET stays code+participant only — thread
                                        # continuity is NOT folded in here: it lands a routed
                                        # TICKET (desk review) via the (e.8) lane below, never
                                        # the authoritative FAST_TICKET (THREAD_CONTINUITY_
                                        # ROUTING_1, now that thread_id is a queryable column).
                                        hits = resolve_by_participant(
                                            "email",
                                            (arrival.sender_email or "").strip().lower(),
                                        )
                                        if any(h.get("project_number") == pn for h in hits):
                                            claim = _claim_for_terminal(conn, row_id)
                                            if claim is None:
                                                # Held by a concurrent tick — hold cursor.
                                                lease_skipped += 1
                                                conn.commit()
                                                handled = True
                                            elif claim[1] is not None:
                                                # Already terminal (idempotent re-tick).
                                                if result.get("ok"):
                                                    issued += 1
                                                conn.commit()
                                                handled = True
                                                done = True
                                            else:
                                                claimed += 1
                                                if write_terminal_status(
                                                    conn,
                                                    ticket_row_id=row_id,
                                                    terminal_status="FAST_TICKET",
                                                    terminal_reason=f"{_HARD_LANE_REASON_PREFIX}{pn}",
                                                    raw_source_id=arrival.message_id,
                                                ):
                                                    terminal_written += 1
                                                    fast_ticket += 1
                                                if result.get("ok"):
                                                    issued += 1
                                                conn.commit()
                                                handled = True
                                                done = True
                            except Exception as exc:
                                # ERROR NEVER AUTO-FAST_TICKETs (#blocker D3). Roll back to
                                # the SAVEPOINT — this undoes D's partial writes but KEEPS
                                # the issue_ticket reservation — count failed, and FALL
                                # THROUGH to (f) TICKET (handled stays False) so the arrival
                                # STILL ends at a visible terminal. Distinguish threw
                                # (-> TICKET + count failed) from a row genuinely held by a
                                # concurrent tick (lease_skipped, handled inside the try).
                                try:
                                    with conn.cursor() as _sp:
                                        _sp.execute(
                                            "ROLLBACK TO SAVEPOINT airport_hard_lane"
                                        )
                                except Exception:
                                    # Savepoint unusable (e.g. the SAVEPOINT statement
                                    # itself failed) — fall back to a full rollback so conn
                                    # stays usable. The (f) claim then lease-skips and the
                                    # arrival re-fetches next tick (cursor frozen, never
                                    # silently dropped).
                                    try:
                                        conn.rollback()
                                    except Exception:
                                        pass
                                failed += 1
                                logger.warning(
                                    "airport_ticketing hard-fast-lane row failed: %s", exc
                                )

                        # (e.7) EXPLICIT-CODE ROUTED LANE — routing reversal
                        #   (BOX5_ROUTING_REVERSAL_E_1). Director ruling 2026-07-01:
                        #   name/alias matching is UNSAFE for multi-matter counterparties.
                        #   Alias is NO LONGER a routing signal. E routes ONLY on a single
                        #   registered ACTIVE project code that D's (e.5) hard lane did not
                        #   already FAST_TICKET (code present, sender not participant-bound).
                        #   Exactly 1 active code -> routed TICKET (desk review); 0 / >1 /
                        #   unregistered / retired -> fall through to (f) TICKET.
                        #   resolve_by_alias() is NOT called. Routed TICKET is NOT completion
                        #   and NOT FAST_TICKET (D's authoritative lane).
                        if fast_lane and row_id and not handled:
                            try:
                                with conn.cursor() as _sp:
                                    _sp.execute("SAVEPOINT airport_code_lane")
                                el_text = f"{arrival.subject} {arrival.full_body}"
                                # >1 distinct code = cross-matter CONFLICT -> no E route;
                                # 0 codes -> no code -> no E route. Only exactly-1 proceeds.
                                if len(set(extract_project_codes(el_text))) == 1:
                                    # Regex shape alone NEVER clears: the code must resolve
                                    # to a registered ACTIVE row (None if unregistered/retired).
                                    resolved = resolve_project_number(el_text)
                                    if resolved is not None:
                                        pn = resolved["project_number"]
                                        claim = _claim_for_terminal(conn, row_id)
                                        if claim is None:
                                            lease_skipped += 1
                                            conn.commit()
                                            handled = True
                                        elif claim[1] is not None:
                                            if result.get("ok"):
                                                issued += 1
                                            conn.commit()
                                            handled = True
                                            done = True
                                        else:
                                            claimed += 1
                                            if write_terminal_status(
                                                conn,
                                                ticket_row_id=row_id,
                                                terminal_status="TICKET",  # ROUTED, not FAST_TICKET
                                                terminal_reason=f"{_CODE_ROUTED_REASON_PREFIX}{pn}",
                                                raw_source_id=arrival.message_id,
                                                matter_slug=resolved["matter_slug"],
                                                desk_owner=resolved["desk_owner"],
                                                manifest_match_signals=[
                                                    {"signal": "project_code", "value": pn,
                                                     "binding": "registry_active"}
                                                ],
                                                confidence=0.80,
                                            ):
                                                terminal_written += 1
                                                code_routed_ticket += 1
                                            if result.get("ok"):
                                                issued += 1
                                            conn.commit()
                                            handled = True
                                            done = True
                                # 0 codes / >1 codes / unregistered / retired ->
                                #   handled stays False -> fall through to (f) TICKET.
                                #   No `failed` on a clean no-route.
                            except Exception as exc:
                                # ERROR NEVER AUTO-CLEARS. Roll back to the savepoint (undo
                                # E's partial writes, KEEP issue_ticket's reservation), count
                                # failed, fall through to (f) TICKET so the arrival still ends
                                # at a visible terminal. Never a routed clear.
                                try:
                                    with conn.cursor() as _sp:
                                        _sp.execute("ROLLBACK TO SAVEPOINT airport_code_lane")
                                except Exception:
                                    try:
                                        conn.rollback()
                                    except Exception:
                                        pass
                                failed += 1
                                logger.warning(
                                    "airport_ticketing explicit-code lane row failed: %s", exc
                                )

                        # (e.8) THREAD-CONTINUITY LANE — routing reversal recall repair
                        #   (THREAD_CONTINUITY_ROUTING_1). A code-less reply on a thread
                        #   whose prior ticket was already CODE-BOUND to an active project
                        #   inherits that project, restoring the recall #446 removed WITHOUT
                        #   reviving name/alias matching (thread identity is a strong signal;
                        #   fuzzy names are not). Sits AFTER the explicit-code lanes and
                        #   BEFORE (f), guarded `if fast_lane and row_id and not handled:` so
                        #   it runs ONLY when D/E did not route. It fires ONLY when the reply
                        #   carries NO explicit project code — an explicit or conflicting code
                        #   is left to (e.5)/(e.7) or (f); thread continuity never overrides an
                        #   explicit code signal. resolve_by_thread inherits ONLY a hard/
                        #   code-bound prior disposition (never a soft/alias/participant guess),
                        #   returns None on a since-retired binding, and returns None when the
                        #   thread spans >1 active project (CONFLICT) -> those fall through to
                        #   (f), never a silent cross-matter pick. Routed TICKET (desk review),
                        #   confidence 0.75 (an inherited binding, below E's direct-code 0.80),
                        #   NEVER FAST_TICKET (D's authoritative lane).
                        if fast_lane and row_id and not handled:
                            try:
                                with conn.cursor() as _sp:
                                    _sp.execute("SAVEPOINT airport_thread_lane")
                                tc_text = f"{arrival.subject} {arrival.full_body}"
                                # Code-less replies ONLY (AC1). Any explicit code shape is
                                # left to the code lanes / (f) — continuity never overrides it.
                                if not extract_project_codes(tc_text):
                                    resolved = resolve_by_thread(
                                        arrival.thread_id or arrival.message_id
                                    )
                                    if resolved is not None:
                                        pn = resolved["project_number"]
                                        claim = _claim_for_terminal(conn, row_id)
                                        if claim is None:
                                            lease_skipped += 1
                                            conn.commit()
                                            handled = True
                                        elif claim[1] is not None:
                                            if result.get("ok"):
                                                issued += 1
                                            conn.commit()
                                            handled = True
                                            done = True
                                        else:
                                            claimed += 1
                                            if write_terminal_status(
                                                conn,
                                                ticket_row_id=row_id,
                                                terminal_status="TICKET",  # ROUTED via thread, not FAST_TICKET
                                                terminal_reason=f"{_THREAD_CONTINUITY_REASON_PREFIX}{pn}",
                                                raw_source_id=arrival.message_id,
                                                matter_slug=resolved["matter_slug"],
                                                desk_owner=resolved["desk_owner"],
                                                manifest_match_signals=[
                                                    {"signal": "thread_continuity", "value": pn,
                                                     "binding": "prior_code_bound_ticket"}
                                                ],
                                                confidence=0.75,
                                            ):
                                                terminal_written += 1
                                                thread_routed_ticket += 1
                                            if result.get("ok"):
                                                issued += 1
                                            conn.commit()
                                            handled = True
                                            done = True
                                # code present / no code-bound thread / retired / conflict ->
                                #   handled stays False -> fall through to (f) TICKET. No
                                #   `failed` on a clean no-route.
                            except Exception as exc:
                                # ERROR NEVER AUTO-CLEARS. Roll back to the savepoint (undo
                                # this lane's partial writes, KEEP issue_ticket's reservation),
                                # count failed, fall through to (f) TICKET so the arrival still
                                # ends at a visible terminal. Never a routed clear.
                                try:
                                    with conn.cursor() as _sp:
                                        _sp.execute("ROLLBACK TO SAVEPOINT airport_thread_lane")
                                except Exception:
                                    try:
                                        conn.rollback()
                                    except Exception:
                                        pass
                                failed += 1
                                logger.warning(
                                    "airport_ticketing thread-continuity lane row failed: %s", exc
                                )

                        if not handled:
                            # (f) SAFE DEFAULT — TICKET (full desk review). [BRIEF-C,
                            #     unchanged] Conflict / no-code / no-row / no-binding /
                            #     hard-lane error / soft-lane no->=2-signal-match /
                            #     soft-lane error / flag-off all land here; result is
                            #     ok=True with a row_id.
                            claim = _claim_for_terminal(conn, row_id)
                            if claim is None:
                                lease_skipped += 1
                                conn.commit()
                            elif claim[1] is not None:
                                # Already terminal (idempotent re-tick) — DONE, no rewrite.
                                if result.get("ok"):
                                    issued += 1
                                conn.commit()
                                done = True
                            else:
                                claimed += 1
                                if write_terminal_status(
                                    conn,
                                    ticket_row_id=row_id,
                                    terminal_status="TICKET",
                                    terminal_reason="safe_default_desk_review",
                                    raw_source_id=arrival.message_id,
                                ):
                                    terminal_written += 1
                                    defaulted_ticket += 1
                                # BOX5_DROP_OBSERVABILITY_1 — Gate 3 drop-log. Reaching
                                # (f) with the fast lane ON means D/E/thread routing was
                                # ATTEMPTED and did NOT confidently assign a desk (the
                                # arrival still tickets, unchanged — this only records
                                # WHY it fell to generic desk review). >1 distinct code =
                                # cross-matter conflict; else no confident route. Guarded
                                # by fast_lane so we don't label every ticket "unrouted"
                                # when routing isn't even running. Savepoint-guarded +
                                # committed atomically with the terminal write above.
                                if fast_lane:
                                    _codes = set(
                                        extract_project_codes(
                                            f"{arrival.subject} {arrival.full_body}"
                                        )
                                    )
                                    if len(_codes) > 1:
                                        _g3_gate = _GATE_ROUTING_CONFLICT
                                        _g3_reason = (
                                            "cross_matter_conflict:"
                                            + ",".join(sorted(_codes))
                                        )
                                    else:
                                        _g3_gate = _GATE_ROUTING_UNROUTED
                                        _g3_reason = "no_confident_route"
                                    _write_dropped_signals(
                                        conn,
                                        [
                                            _drop_record(
                                                arrival,
                                                gate=_g3_gate,
                                                reason=_g3_reason,
                                                matched_keywords=_match_active_keywords(
                                                    arrival.subject,
                                                    arrival.full_body,
                                                    active_keywords(),
                                                ),
                                            )
                                        ],
                                        savepoint=True,
                                    )
                                if result.get("ok"):
                                    issued += 1
                                conn.commit()
                                done = True

            except Exception as exc:  # ERROR NEVER AUTO-CLEARS (blocker D3)
                try:
                    conn.rollback()
                except Exception:
                    pass
                failed += 1
                done = False
                logger.warning("airport_ticketing run_tick row failed: %s", exc)

            # (P1-A) Contiguous-prefix advance: extend the cursor only while every
            # arrival so far is done; the first not-done arrival freezes it for the
            # rest of the tick so the gap stays re-fetchable next tick.
            if not done:
                contiguous = False
            elif contiguous:
                watermark_candidate = _advance(
                    watermark_candidate, arrival.received_date
                )

        # (h) ADVANCE CURSOR to the end of the contiguous fully-processed prefix.
        #     A failed/held/un-processed arrival earlier in the batch keeps the
        #     watermark behind it so it is re-fetched next tick (no silent drop).
        if watermark_candidate is not None:
            try:
                trigger_state_set_watermark(_WATERMARK_SOURCE, watermark_candidate)
            except Exception as e:
                logger.warning("airport ticketing watermark advance failed: %s", e)

        # BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — non-mail lanes (Plaud + WhatsApp). Dark by
        # default. Runs AFTER the email lane's cursor already advanced, and each lane has
        # its OWN watermark + fetcher, so a non-mail failure never affects email ticketing.
        # Each lane issues candidate desk-review tickets through the SAME issue_ticket
        # spine (never checked_in, never a lounge-writer claim path). Phase 2 news feeds
        # are Director-gated and intentionally absent.
        nonmail_plaud = {"issued": 0, "skipped": 0, "failed": 0, "suppressed": 0}
        nonmail_whatsapp = {"issued": 0, "skipped": 0, "failed": 0, "suppressed": 0}
        nonmail_dry = False
        if nonmail_sources_enabled():
            nonmail_dry = nonmail_dry_run()
            nonmail_plaud = _run_nonmail_lane(
                conn,
                source_label="plaud",
                fetch_fn=fetch_plaud_arrivals,
                build_fn=build_plaud_ticket,
                watermark_source=_WATERMARK_SOURCE_PLAUD,
                current=current,
                cap=cap,
                dry_run=nonmail_dry,
            )
            nonmail_whatsapp = _run_nonmail_lane(
                conn,
                source_label="whatsapp",
                fetch_fn=fetch_whatsapp_arrivals,
                build_fn=build_whatsapp_ticket,
                watermark_source=_WATERMARK_SOURCE_WHATSAPP,
                current=current,
                cap=cap,
                dry_run=nonmail_dry,
                # Task 6: suppress identity-only WA ticket minting (config-driven), while
                # still advancing the watermark past suppressed arrivals.
                suppress_fn=_wa_identity_suppressed,
            )

        stuck_arrivals = _count_stuck_arrivals(conn)
        stats = {
            "ok": True,
            "issued": issued,
            "skipped": skipped,
            "failed": failed,
            "claimed": claimed,
            "terminal_written": terminal_written,
            "lease_skipped": lease_skipped,
            "deterministic_cleared": deterministic_cleared,
            "defaulted_ticket": defaulted_ticket,
            "fast_ticket": fast_ticket,
            "code_routed_ticket": code_routed_ticket,
            "thread_routed_ticket": thread_routed_ticket,
            "outbound_signal": outbound_signal,
            "stuck_arrivals": stuck_arrivals,
            # BAKER_OS_V2_C5_NONMAIL_SIGNALS_1 — non-mail lane counters (all 0 when the
            # AIRPORT_NONMAIL_SOURCES_ENABLED flag is off).
            "nonmail_enabled": nonmail_sources_enabled(),
            "nonmail_dry_run": nonmail_dry,
            "plaud_issued": nonmail_plaud["issued"],
            "plaud_skipped": nonmail_plaud["skipped"],
            "plaud_failed": nonmail_plaud["failed"],
            "whatsapp_issued": nonmail_whatsapp["issued"],
            "whatsapp_skipped": nonmail_whatsapp["skipped"],
            "whatsapp_failed": nonmail_whatsapp["failed"],
            # Task 6: identity-only WA arrivals suppressed (not ticketed) this tick.
            "whatsapp_suppressed": nonmail_whatsapp.get("suppressed", 0),
            # Read + surfaced for observability. In BRIEF-C the fast lane is not
            # built, so this flag has NO behavioral branch yet — it only gates the
            # future D/E lanes (project-number / manifest). Deterministic clears
            # (DUPLICATE / REJECT_NOISE) and the safe-default TICKET run regardless.
            "fast_lane": fast_lane,
        }
        logger.info("airport_ticketing run_tick stats: %s", stats)
        return stats
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("airport ticketing tick failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        store._put_conn(conn)
