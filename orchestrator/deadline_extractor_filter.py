"""DEADLINE_EXTRACTOR_QUALITY_1 — two-layer noise filter for email deadlines.

Cat 6 audit (2026-04-26): 25 of 42 email-extracted deadlines were promotional
noise (Loro Piana, Mother's Day, Bloomberg, golf events, Botanic, Foxtons …).

Two layers, both deterministic — no LLM call (Director Q2 default):

  L1  Sender domain blocklist + email-prefix patterns. Cheapest reject.
  L2  Subject/body promotional-keyword scorer with two thresholds:
        score >= DROP_THRESHOLD     → drop
        score >= DOWNGRADE_THRESHOLD → keep but mark priority='low' for review
        score <  DOWNGRADE_THRESHOLD → allow normally

Whitelist (domain-level) overrides BOTH layers — bank/legal/internal
counterparties always extract regardless of keyword density.

Every drop and downgrade is recorded in `deadline_extractor_suppressions`
audit table; failures here are non-fatal (logged then swallowed) so an
audit-log error never blocks deadline extraction.

V1: deterministic. Revisit if precision <90% after 30 days.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("baker.deadline_extractor_filter")

# ---------------------------------------------------------------------------
# Whitelist (domain-level) — overrides L1 + L2.
# Curated from the existing VIP register + core counterparties as of 2026-04-26.
# ---------------------------------------------------------------------------
WHITELIST_DOMAINS = frozenset({
    # Internal / Brisen
    "brisengroup.com",
    "mohg.com",
    # Legal counterparties
    "eh.at",                # Ofenheimer & Hochenburger
    "gantey.ch",            # Gantey
    "merz-recht.de",        # Merz Recht
    "peakside.com",
    # Banks / lenders
    "aukera.ag",            # Aukera (Bonnewitz)
    # Aggregator / vendor with legit deadlines
    "notion.com",
    "slack.com",
    "dropbox.com",       # File-transfer notifications are real-signal
    "anthropic.com",     # System / API change notices
    "claude.com",        # Model retirement, beta-window reminders
})

# ---------------------------------------------------------------------------
# L1 — sender blocklist.
# Two structures:
#   BLOCK_DOMAIN_PATTERNS  — regex against the @-suffix domain, full match.
#   BLOCK_SENDER_PREFIXES  — exact email-local-part (case-insensitive).
# Patterns harvested from 25 dismissed Cat 6 deadlines + general newsletter
# subdomain conventions (news., newsletter., e., crm., em., …).
# Director pre-deploy review of harvest list at
# `_01_INBOX_FROM_CLAUDE/2026-04-26-l1-harvest-review.html`.
# ---------------------------------------------------------------------------
BLOCK_DOMAIN_PATTERNS = (
    # Newsletter / marketing subdomain conventions (across vendors)
    re.compile(r"^news\..+", re.IGNORECASE),
    re.compile(r"^newsletter\..+", re.IGNORECASE),
    re.compile(r"^email\..+", re.IGNORECASE),
    re.compile(r"^e\..+", re.IGNORECASE),
    re.compile(r"^em\..+", re.IGNORECASE),
    re.compile(r"^crm\..+", re.IGNORECASE),
    re.compile(r"^read\..+", re.IGNORECASE),
    re.compile(r"^digital\..+", re.IGNORECASE),
    re.compile(r"^message\..+", re.IGNORECASE),
    re.compile(r"^mailing\..+", re.IGNORECASE),
    re.compile(r"^marketing\..+", re.IGNORECASE),
    re.compile(r"^promo\..+", re.IGNORECASE),
    re.compile(r"^offers?\..+", re.IGNORECASE),
    re.compile(r"^informations?\..+", re.IGNORECASE),
    # ESP / mass-mailer infrastructure (these usually leak through "via" headers)
    re.compile(r".*\.mcsv\.net$", re.IGNORECASE),
    re.compile(r".*\.mailpro\.net$", re.IGNORECASE),
    re.compile(r".*\.mandrillapp\.com$", re.IGNORECASE),
    re.compile(r".*mailjet\.com$", re.IGNORECASE),
    re.compile(r".*\.sparkpost(mail)?(\..+)?$", re.IGNORECASE),
    re.compile(r".*\.marketo\.org$", re.IGNORECASE),
    # Concrete sender domains harvested from the 25 dismissed Cat 6 items
    re.compile(r"^crm\.ba\.com$", re.IGNORECASE),
    re.compile(r"^emirates\.email$", re.IGNORECASE),
    re.compile(r"^observer\.at$", re.IGNORECASE),
    re.compile(r"^golfbossey\.com$", re.IGNORECASE),
    re.compile(r"^academyfinance\.ch$", re.IGNORECASE),
    re.compile(r"^bagherawines\.com$", re.IGNORECASE),
    re.compile(r"^contact\.tcs\.ch$", re.IGNORECASE),
    re.compile(r"^info\.foxtons\.co\.uk$", re.IGNORECASE),
    re.compile(r"^eosrv\.net$", re.IGNORECASE),
    re.compile(r"^brack\.ch$", re.IGNORECASE),
)

# Local-part prefixes that almost always indicate machine/bulk mail.
BLOCK_SENDER_PREFIXES = frozenset({
    "noreply", "no-reply", "do-not-reply", "donotreply",
    "newsletter", "newsletters",
    "marketing", "promotions", "promo", "offers",
    "subscriptions", "subscribe",
    "notifications", "alerts",
    "info",  # generic — only blocks when domain isn't whitelisted (whitelist runs first)
})

# ---------------------------------------------------------------------------
# L2 — promotional keyword scorer.
# Each keyword pattern in the table contributes +N to the score. The full
# subject + first 800 chars of body are scanned (case-insensitive). Two
# thresholds — DROP and DOWNGRADE — produce one of three actions.
# ---------------------------------------------------------------------------
DROP_THRESHOLD = 5
DOWNGRADE_THRESHOLD = 3

# (regex, weight) — patterns are roughly ordered most-noisy first.
L2_KEYWORDS: tuple[tuple[re.Pattern, int], ...] = (
    # Hard-promo cues — single hit usually sufficient with a partner cue.
    (re.compile(r"\b\d{1,3}\s?%\s?(off|discount|rabatt)\b", re.IGNORECASE), 4),
    (re.compile(r"\bsave (up to )?(£|\$|€|chf|usd|eur|gbp)?\s?\d", re.IGNORECASE), 3),
    (re.compile(r"\b(special|exclusive)\s+(offer|discount|sale|deal|promotion)\b", re.IGNORECASE), 4),
    (re.compile(r"\b(holiday|black\s?friday|cyber\s?monday|spring|summer|winter)\s+(sale|promotion|offer|deal)\b", re.IGNORECASE), 4),
    (re.compile(r"\bgift\s+guide\b", re.IGNORECASE), 4),
    (re.compile(r"\b(mother|father|valentine|christmas|easter)['’]?s?\s+day\b", re.IGNORECASE), 3),
    (re.compile(r"\bsubscription\s+(offer|deal|expires)\b", re.IGNORECASE), 4),
    (re.compile(r"\bsubscribe (to|now)\b", re.IGNORECASE), 3),
    # Event-y but often promotional
    (re.compile(r"\b(webinar|webcast|seminar|conference|symposium)\b", re.IGNORECASE), 2),
    (re.compile(r"\b(soir[ée]e|d[ée]gustation|tasting)\b", re.IGNORECASE), 2),
    (re.compile(r"\bauction\b", re.IGNORECASE), 2),
    (re.compile(r"\bgolf\b.*\b(event|tournament|classic)\b", re.IGNORECASE), 3),
    (re.compile(r"\b(rsvp|register now|register today|sign up now)\b", re.IGNORECASE), 2),
    # Anniversaries / celebrations / promotional adjectives
    (re.compile(r"\b\d{1,3}(th|st|nd|rd)?\s+anniversary\b", re.IGNORECASE), 3),
    (re.compile(r"\bcelebrate\b", re.IGNORECASE), 1),
    # Travel / loyalty
    (re.compile(r"\b(holiday\s+package|book\s+a\s+(holiday|trip|stay))\b", re.IGNORECASE), 3),
    (re.compile(r"\b(loyalty|members[-\s]?only|club\s+benefit)\b", re.IGNORECASE), 2),
    # Bloomberg / Forbes / FT-style "subscribe to … pay off" patterns
    (re.compile(r"\b(get|enjoy)\s+\d{1,3}\s?%\s+off\b", re.IGNORECASE), 4),
)

# Real-signal cues that suppress score (each match subtracts from total — small).
L2_SIGNAL_NEGATORS: tuple[tuple[re.Pattern, int], ...] = (
    (re.compile(r"\b(payment\s+due|invoice|due\s+date|overdue)\b", re.IGNORECASE), 3),
    (re.compile(r"\b(contract|agreement|signature|notarisation|escrow)\b", re.IGNORECASE), 2),
    (re.compile(r"\b(closing|completion|exchange)\s+date\b", re.IGNORECASE), 3),
    (re.compile(r"\b(court|hearing|deadline|filing|deposition)\b", re.IGNORECASE), 2),
    (re.compile(r"\b(capital\s+call|drawdown|loan\s+repayment)\b", re.IGNORECASE), 3),
)


@dataclass
class ClassifyResult:
    """Outcome of running both filter layers on one extracted-deadline candidate."""
    action: str           # "allow" | "drop" | "downgrade"
    layer: str            # "whitelist" | "L1" | "L2" | "none"
    reason: str           # short human-readable explanation
    score: int = 0        # L2 numeric score (0 if not L2-evaluated)


def _extract_domain(sender_email: str) -> str:
    if not sender_email or "@" not in sender_email:
        return ""
    return sender_email.split("@", 1)[1].strip().lower()


def _extract_local_part(sender_email: str) -> str:
    if not sender_email or "@" not in sender_email:
        return ""
    return sender_email.split("@", 1)[0].strip().lower()


def _is_whitelisted(domain: str) -> bool:
    """A domain is whitelisted if it equals or ends with a whitelisted root.

    e.g. `info@a.bonnewitz@aukera.ag` → domain `aukera.ag` is in whitelist;
    `paralegal@buchwalder.gantey.ch` → ends with `gantey.ch`.
    """
    if not domain:
        return False
    if domain in WHITELIST_DOMAINS:
        return True
    return any(domain.endswith("." + w) for w in WHITELIST_DOMAINS)


def _l1_blocks(sender_email: str) -> Optional[str]:
    """Return reason string if L1 blocks; None otherwise."""
    domain = _extract_domain(sender_email)
    if not domain:
        return None  # Don't L1-block missing senders — let L2 decide.
    for pat in BLOCK_DOMAIN_PATTERNS:
        if pat.match(domain):
            return f"L1 domain pattern {pat.pattern!r} matched {domain!r}"
    local = _extract_local_part(sender_email)
    if local in BLOCK_SENDER_PREFIXES:
        return f"L1 prefix-blocklist matched local-part {local!r}"
    return None


def _l2_score(subject: str, body: str) -> tuple[int, list[str]]:
    """Compute the L2 score and return (score, hit_descriptions)."""
    text = f"{subject or ''}\n{(body or '')[:800]}"
    score = 0
    hits: list[str] = []
    for pat, weight in L2_KEYWORDS:
        if pat.search(text):
            score += weight
            hits.append(f"+{weight} {pat.pattern}")
    for pat, weight in L2_SIGNAL_NEGATORS:
        if pat.search(text):
            score -= weight
            hits.append(f"-{weight} (signal) {pat.pattern}")
    if score < 0:
        score = 0
    return score, hits


def classify(sender_email: str, subject: str, body: str) -> ClassifyResult:
    """Run whitelist → L1 → L2 in order and return one ClassifyResult.

    `sender_email`, `subject`, `body` may be empty / None — the function never
    raises on bad inputs; uncertain cases default to action='allow' so the
    extractor still runs (downstream dedup + 7-day-past filter still apply).
    """
    domain = _extract_domain(sender_email or "")

    if domain and _is_whitelisted(domain):
        return ClassifyResult(
            action="allow",
            layer="whitelist",
            reason=f"whitelisted domain {domain!r}",
        )

    l1_reason = _l1_blocks(sender_email or "")
    if l1_reason:
        return ClassifyResult(action="drop", layer="L1", reason=l1_reason)

    score, hits = _l2_score(subject or "", body or "")
    if score >= DROP_THRESHOLD:
        return ClassifyResult(
            action="drop", layer="L2",
            reason=f"L2 score {score} ≥ DROP_THRESHOLD={DROP_THRESHOLD} :: {'; '.join(hits)[:200]}",
            score=score,
        )
    if score >= DOWNGRADE_THRESHOLD:
        return ClassifyResult(
            action="downgrade", layer="L2",
            reason=f"L2 score {score} ≥ DOWNGRADE_THRESHOLD={DOWNGRADE_THRESHOLD} :: {'; '.join(hits)[:200]}",
            score=score,
        )
    return ClassifyResult(action="allow", layer="none", reason="below thresholds", score=score)


# ---------------------------------------------------------------------------
# Audit-log persistence (fire-and-forget; never raises).
# ---------------------------------------------------------------------------

_TABLE_BOOTSTRAPPED = False


def _ensure_suppressions_table() -> None:
    """Create `deadline_extractor_suppressions` if missing. Idempotent.

    Fault-tolerant per CLAUDE.md — wraps DB ops in try/except and never raises.
    """
    global _TABLE_BOOTSTRAPPED
    if _TABLE_BOOTSTRAPPED:
        return
    try:
        from models.deadlines import get_conn, put_conn  # type: ignore
    except Exception as e:
        logger.debug(f"deadline_extractor_filter: cannot import deadlines model ({e})")
        return
    conn = None
    try:
        conn = get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS deadline_extractor_suppressions (
                id SERIAL PRIMARY KEY,
                sender_email TEXT,
                subject TEXT,
                layer VARCHAR(16) NOT NULL,
                reason TEXT NOT NULL,
                score INTEGER,
                action VARCHAR(16) NOT NULL,
                source_id TEXT,
                source_type VARCHAR(50),
                dropped_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_dxs_dropped_at "
            "ON deadline_extractor_suppressions (dropped_at DESC)"
        )
        conn.commit()
        cur.close()
        _TABLE_BOOTSTRAPPED = True
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning(f"deadline_extractor_filter: ensure_table failed (non-fatal): {e}")
    finally:
        try:
            if conn is not None:
                put_conn(conn)
        except Exception:
            pass


def log_suppression(
    *,
    sender_email: str,
    subject: str,
    result: ClassifyResult,
    source_id: str = "",
    source_type: str = "email",
) -> None:
    """Insert one row into `deadline_extractor_suppressions`. Never raises."""
    if result.action == "allow":
        return  # Only drop / downgrade are recorded.
    _ensure_suppressions_table()
    try:
        from models.deadlines import get_conn, put_conn  # type: ignore
    except Exception:
        return
    conn = None
    try:
        conn = get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO deadline_extractor_suppressions
                (sender_email, subject, layer, reason, score, action, source_id, source_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                (sender_email or "")[:512],
                (subject or "")[:1024],
                result.layer[:16],
                result.reason[:2048],
                result.score,
                result.action[:16],
                (source_id or "")[:512],
                (source_type or "email")[:50],
            ),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning(f"deadline_extractor_filter: log_suppression failed (non-fatal): {e}")
    finally:
        try:
            if conn is not None:
                put_conn(conn)
        except Exception:
            pass
