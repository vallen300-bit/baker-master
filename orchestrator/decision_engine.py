"""
DECISION-ENGINE-1A: Baker Decision Engine — scoring and routing layer.

Runs BEFORE retrieval in the pipeline. Produces scored metadata:
domain, urgency_score, tier, channel, mode, overrides.

Three insertion points:
  - pipeline.py (background triggers)
  - waha_webhook.py (Director WhatsApp)
  - dashboard.py (Scan queries)

## TIER CONVENTION (IMPORTANT — read before touching tier logic)
##
## Tier numbering is CONSISTENT across the entire codebase:
##   Tier 1 = MOST URGENT  → channel: whatsapp  (matches pipeline.py _normalize_tier)
##   Tier 2 = IMPORTANT    → channel: slack
##   Tier 3 = INFORMATIONAL → channel: dashboard (least urgent)
##
## This matches:
##   - pipeline.py _normalize_tier(): {"urgent": 1, "important": 2, "info": 3}
##   - vip_contacts.tier: 1 = most important VIP, 2 = standard VIP
##   - Slack alert tiers: tier <= 2 → post to Slack
##
## Do NOT invert this. Score 7-9 → Tier 1. Score 1-3 → Tier 3.
"""
import logging
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from config.settings import config

logger = logging.getLogger("sentinel.decision_engine")

# ============================================================
# VIP Cache (in-process, 5-min TTL, ~11 rows)
# Thread-safe: lock protects write path (M1 fix)
# ============================================================

_vip_lock = threading.Lock()
_vip_cache: dict = {"data": [], "expires": 0}


def _get_vips() -> list:
    """Return cached VIP contacts. Refreshes from DB every 5 min."""
    now = time.time()
    if now < _vip_cache["expires"] and _vip_cache["data"]:
        return _vip_cache["data"]
    with _vip_lock:
        # Double-check after acquiring lock (another thread may have refreshed)
        if now < _vip_cache["expires"] and _vip_cache["data"]:
            return _vip_cache["data"]
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            conn = store._get_conn()
            if not conn:
                return _vip_cache["data"]  # stale is better than empty
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT name, email, role, whatsapp_id,
                           COALESCE(tier, 2) AS tier,
                           COALESCE(domain, 'network') AS domain
                    FROM vip_contacts
                """)
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
                vips = [dict(zip(cols, row)) for row in rows]
                cur.close()
                _vip_cache["data"] = vips
                _vip_cache["expires"] = time.time() + 300  # 5 min TTL
                logger.debug(f"VIP cache refreshed: {len(vips)} contacts")
                return vips
            finally:
                store._put_conn(conn)
        except Exception as e:
            logger.warning(f"VIP cache refresh failed: {e}")
            return _vip_cache["data"]


# ============================================================
# Deadline Cache (in-process, 5-min TTL — M3 fix)
# ============================================================

_deadline_lock = threading.Lock()
_deadline_cache: dict = {"data": [], "expires": 0}


def _get_cached_deadlines() -> list:
    """Return cached active deadlines. Refreshes from DB every 5 min."""
    now = time.time()
    if now < _deadline_cache["expires"]:
        return _deadline_cache["data"]
    with _deadline_lock:
        if now < _deadline_cache["expires"]:
            return _deadline_cache["data"]
        try:
            from models.deadlines import get_active_deadlines
            deadlines = get_active_deadlines(limit=50)
            _deadline_cache["data"] = deadlines or []
            _deadline_cache["expires"] = time.time() + 300
            return _deadline_cache["data"]
        except Exception:
            return _deadline_cache["data"]


# ============================================================
# Domain Classifier
# ============================================================

# Compiled regex patterns per domain (case-insensitive)
_DOMAIN_PATTERNS = {
    "chairman": re.compile(
        r"\b(board|compliance|regulatory|governance|fiduciary|shareholder|"
        r"agm|annual.general|supervisory|audit.committee)\b", re.IGNORECASE
    ),
    "projects": re.compile(
        r"\b(hagenauer|rg\s?7|mandarin|mo\s?vie|salzburg|kitz|"
        r"invoice|payment|milestone|permit|contractor|subcontractor|"
        r"construction|handover|gew.hrleistung|cupial|scorpio|"
        r"baubewilligung|baurecht|sonderwunsch|claim)\b", re.IGNORECASE
    ),
    "network": re.compile(
        r"\b(mrci|lilienmat|investor|lp\b|fund|oskolkov|pipeline|deal.?flow|"
        r"capital|placement|allocation|co-invest|brisen)\b", re.IGNORECASE
    ),
    "private": re.compile(
        r"\b(personal|property|passport|tax.return|family|health|"
        r"doctor|appointment|school)\b", re.IGNORECASE
    ),
    "travel": re.compile(
        r"\b(flight|hotel|reservation|visa|airport|boarding|check.in|"
        r"mipim|berlin|travel|luggage|lounge)\b", re.IGNORECASE
    ),
}

# Source-type default domain mapping
_SOURCE_DOMAIN_MAP = {
    "whoop": "private",
    "todoist": "projects",
    "clickup": "projects",
    "clickup_handoff_note": "projects",
    "clickup_status_change": "projects",
}


def _vip_name_matches(vip_name: str, sender_lower: str) -> bool:
    """Check if VIP name matches sender using word-boundary logic (L1 fix).
    Matches full name or all words of the VIP name appear in sender."""
    if not vip_name or not sender_lower:
        return False
    # Exact full-name match
    if vip_name == sender_lower:
        return True
    # All words of VIP name appear as whole words in sender
    vip_words = vip_name.split()
    if len(vip_words) >= 2:
        return all(w in sender_lower.split() for w in vip_words)
    # Single-word VIP name: must match a whole word in sender
    return vip_name in sender_lower.split()


def _classify_domain(content: str, sender: str, source: str,
                     vips: list, allow_llm: bool = True) -> tuple:
    """
    Classify domain. Returns (domain, confidence, method).
    4-step cascade: VIP → keyword regex → source mapping → Haiku fallback.
    """
    sender_lower = (sender or "").lower().strip()

    # Step 1: Check sender against VIP cache for domain tag (L1: word-boundary match)
    for vip in vips:
        vip_name = (vip.get("name") or "").lower()
        if _vip_name_matches(vip_name, sender_lower):
            domain = vip.get("domain", "network")
            return (domain, "high", "vip_match")

    # Step 2: Compiled regex patterns
    matches = {}
    for domain, pattern in _DOMAIN_PATTERNS.items():
        hits = pattern.findall(content)
        if hits:
            matches[domain] = len(hits)

    if matches:
        best = max(matches, key=matches.get)
        confidence = "high" if matches[best] >= 2 else "medium"
        return (best, confidence, "keyword_regex")

    # Step 3: Source-type mapping
    for prefix, domain in _SOURCE_DOMAIN_MAP.items():
        if source and source.startswith(prefix):
            return (domain, "low", "source_mapping")

    # Step 4: Haiku fallback (only if allowed)
    if allow_llm:
        try:
            return _classify_domain_haiku(content)
        except Exception as e:
            logger.warning(f"Haiku domain classification failed: {e}")

    return ("projects", "low", "default")


def _classify_domain_haiku(content: str) -> tuple:
    """Use Claude Haiku for domain classification when rule-based is inconclusive."""
    import anthropic
    client = anthropic.Anthropic(api_key=config.claude.api_key)

    prompt = (
        "Classify this message into exactly one domain. "
        "Reply with ONLY the domain name, nothing else.\n"
        "Domains: chairman, projects, network, private, travel\n\n"
        f"Message: {content[:500]}"
    )

    response = client.messages.create(
        model=config.decision_engine.haiku_model,
        max_tokens=10,
        messages=[{"role": "user", "content": prompt}],
    )
    domain = response.content[0].text.strip().lower()
    if domain in _DOMAIN_PATTERNS:
        return (domain, "medium", "haiku_llm")
    return ("projects", "low", "haiku_fallback")


# ============================================================
# Urgency Scorer
# ============================================================

_TIME_KEYWORDS_URGENT = re.compile(
    r"\b(today|tonight|now|asap|urgent|immediately|sofort|dringend)\b", re.IGNORECASE
)
_TIME_KEYWORDS_SOON = re.compile(
    r"\b(tomorrow|this week|deadline|morgen|diese woche|frist)\b", re.IGNORECASE
)
_FINANCIAL_KEYWORDS = re.compile(
    r"(€|EUR|euro|invoice|payment|penalty|contract.value|zahlung|rechnung|"
    r"strafe|vertragsstrafe|forderung|claim)", re.IGNORECASE
)

# C1 fix: Use finditer with named groups to get correct match positions for k-suffix
_AMOUNT_PATTERN = re.compile(
    r'(?P<currency>[€$])?\s?(?P<digits>[\d.,]+)\s*(?P<suffix>k|K|EUR|€)',
)


def _score_time_sensitivity(content: str) -> int:
    """Score 1-3: time pressure from keywords + deadline proximity."""
    score = 1  # default: no urgency

    if _TIME_KEYWORDS_URGENT.search(content):
        score = 3
    elif _TIME_KEYWORDS_SOON.search(content):
        score = 2

    # Cross-ref deadlines (M3 fix: cached, not queried per call)
    deadlines = _get_cached_deadlines()
    if deadlines:
        now = datetime.now(timezone.utc)
        content_lower = content.lower()
        for dl in deadlines:
            due = dl.get("due_date")
            if not due:
                continue
            if hasattr(due, 'tzinfo') and due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            delta = due - now
            if delta < timedelta(hours=24):
                desc = (dl.get("description") or "").lower()
                if any(w in content_lower for w in desc.split()[:5] if len(w) > 3):
                    score = max(score, 3)
                    break
            elif delta < timedelta(days=7):
                desc = (dl.get("description") or "").lower()
                if any(w in content_lower for w in desc.split()[:5] if len(w) > 3):
                    score = max(score, 2)

    return score


def _score_financial_exposure(content: str, domain: str) -> int:
    """Score 1-3: financial signals from keywords + amount patterns."""
    score = 1
    has_financial_keywords = bool(_FINANCIAL_KEYWORDS.search(content))

    if has_financial_keywords:
        score = 2

    # C1 fix: Use finditer to get correct match span for k-suffix detection
    for m in _AMOUNT_PATTERN.finditer(content):
        try:
            raw = m.group("digits")
            suffix = m.group("suffix")
            num = float(raw.replace(",", "").replace(".", ""))
            # k/K suffix means thousands — use the actual matched suffix
            if suffix in ("k", "K"):
                num *= 1000
            if num >= config.decision_engine.financial_threshold_high:
                score = 3
                break
            elif num >= config.decision_engine.financial_threshold_medium:
                score = max(score, 2)
        except (ValueError, IndexError):
            pass

    # L4 fix: Projects domain boost ONLY when financial keywords are present
    if domain == "projects" and has_financial_keywords and score < 3:
        score = max(score, 2)

    return score


def _score_relationship(sender: str, vips: list) -> int:
    """Score 1-3: relationship weight from VIP tier."""
    sender_lower = (sender or "").lower().strip()
    for vip in vips:
        vip_name = (vip.get("name") or "").lower()
        if _vip_name_matches(vip_name, sender_lower):
            tier = vip.get("tier", 2)
            if tier == 1:
                return 3
            return 2
    return 1


# ============================================================
# Override Detector (2 overrides)
# ============================================================

_EMERGENCY_KEYWORDS = re.compile(
    r"\b(emergency|accident|hospital|police|notfall|unfall|krankenhaus|"
    r"help me|hilfe|urgent personal|sick|ill|hurt)\b", re.IGNORECASE
)

_TRAVEL_URGENT_KEYWORDS = re.compile(
    r"\b(flight cancelled|delayed|missed|gate.change|"
    r"boarding.now|check.in.closes|flug.gestrichen|versp.tung)\b", re.IGNORECASE
)


def _detect_overrides(content: str, sender: str, domain: str,
                      urgency_score: int) -> tuple:
    """
    Check for emotional + travel_urgent overrides.
    Returns (override_name_or_None, adjusted_domain, adjusted_score, adjusted_tier).
    Tier convention: 1 = most urgent (see module docstring).
    """
    de_config = config.decision_engine
    sender_lower = (sender or "").lower()

    # Override 1: Emotional urgency — family contact + emergency keywords
    is_family = any(name in sender_lower for name in de_config.family_contacts)
    if is_family and _EMERGENCY_KEYWORDS.search(content):
        return ("emotional_urgency", "private", 9, 1)  # C3 fix: tier 1 = most urgent

    # Override 2: Travel urgent — travel keywords + immediate time reference
    if _TRAVEL_URGENT_KEYWORDS.search(content):
        return ("travel_urgent", "travel", max(urgency_score, 8), 1)  # C3 fix: tier 1

    return (None, domain, urgency_score, None)


# ============================================================
# Tier Assigner
# ============================================================

def _assign_tier(score: int) -> tuple:
    """Map urgency score to tier + channel.
    Returns (tier, channel).

    C3 fix: Tier 1 = most urgent (whatsapp), Tier 3 = least urgent (dashboard).
    Matches pipeline.py _normalize_tier and vip_contacts.tier convention.
    """
    if score >= 7:
        return (1, "whatsapp")   # Tier 1 = most urgent
    elif score >= 4:
        return (2, "slack")      # Tier 2 = important
    else:
        return (3, "dashboard")  # Tier 3 = informational


# ============================================================
# Mode Tagger
# ============================================================

_DELEGATE_KEYWORDS = re.compile(
    r"\b(negotiate|analyze|regulatory|strategy|board|restructure|"
    r"assessment|due.diligence|legal.review|audit)\b", re.IGNORECASE
)


def _tag_mode(content: str, domain: str, vips: list, sender: str) -> str:
    """
    Tag handle/delegate/escalate based on content signals.
    Tagging only — no routing logic.
    """
    if _DELEGATE_KEYWORDS.search(content):
        return "delegate"

    # Escalate: no domain match AND no VIP match AND short/ambiguous content
    sender_lower = (sender or "").lower()
    has_vip = any(
        _vip_name_matches((vip.get("name") or "").lower(), sender_lower)
        for vip in vips
    )
    if domain == "projects" and not has_vip and len(content.strip()) < 30:
        return "escalate"

    return "handle"


# ============================================================
# Main Entry Point
# ============================================================

def score_trigger(content: str, sender: str = "", source: str = "",
                  metadata: dict = None, allow_llm: bool = True) -> dict:
    """
    Score an incoming trigger. Returns dict with all scored fields.
    Called from pipeline.py, waha_webhook.py, dashboard.py.

    Args:
        content: Message/trigger text
        sender: Sender name or identifier
        source: Trigger source type (email, whatsapp, scan, etc.)
        metadata: Optional carrier dict
        allow_llm: If False, skip Haiku fallback (for webhook latency)

    Returns dict:
        domain, urgency_score, tier (1=urgent, 3=low), channel, mode,
        override_applied, reasoning,
        time_score, financial_score, relationship_score
    """
    metadata = metadata or {}
    vips = _get_vips()

    # 1. Domain classification
    domain, domain_confidence, domain_method = _classify_domain(
        content, sender, source, vips, allow_llm=allow_llm,
    )

    # 2. Urgency sub-scores
    time_score = _score_time_sensitivity(content)
    financial_score = _score_financial_exposure(content, domain)
    relationship_score = _score_relationship(sender, vips)
    urgency_score = time_score + financial_score + relationship_score

    # 3. Tier assignment (1=urgent, 3=low)
    tier, channel = _assign_tier(urgency_score)

    # 4. Override detection
    override_name, domain, urgency_score, override_tier = _detect_overrides(
        content, sender, domain, urgency_score,
    )
    if override_tier is not None:
        tier = override_tier
        _, channel = _assign_tier(urgency_score)  # recalc channel from adjusted score

    # 5. Mode tagging
    mode = _tag_mode(content, domain, vips, sender)

    # Build reasoning string
    reasoning = (
        f"domain={domain}({domain_method},{domain_confidence}) "
        f"scores=T{time_score}+F{financial_score}+R{relationship_score}={urgency_score} "
        f"tier={tier} channel={channel} mode={mode}"
    )
    if override_name:
        reasoning += f" override={override_name}"

    return {
        "domain": domain,
        "urgency_score": urgency_score,
        "tier": tier,
        "channel": channel,
        "mode": mode,
        "override_applied": override_name,
        "reasoning": reasoning,
        "time_score": time_score,
        "financial_score": financial_score,
        "relationship_score": relationship_score,
    }


# ============================================================
# VIP SLA Monitoring (scheduled job)
# ============================================================

# Track last SLA alert per sender to prevent alert storms (M2 fix: pruned each run)
_sla_lock = threading.Lock()
_sla_alert_cache: dict = {}  # sender -> timestamp of last alert


def run_vip_sla_check():
    """
    Scheduled job (every 5 min): check for unanswered VIP messages.
    Tier 1 VIP unanswered >15 min → WhatsApp alert to Director.
    Tier 2 VIP unanswered >4 hours → Slack alert.
    """
    de_config = config.decision_engine
    vips = _get_vips()
    if not vips:
        return

    # Build lookup: sender_name_lower -> vip
    vip_lookup = {}
    for vip in vips:
        name = (vip.get("name") or "").lower()
        if name:
            vip_lookup[name] = vip

    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()

    # M2 fix: Prune stale entries (older than 24h) to prevent unbounded growth
    with _sla_lock:
        stale_keys = [k for k, v in _sla_alert_cache.items() if now_ts - v > 86400]
        for k in stale_keys:
            del _sla_alert_cache[k]

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            # L2 fix: ORDER BY received_at DESC to get the MOST RECENT unanswered msg
            # (SLA timer starts from latest message, not oldest)
            cur.execute("""
                SELECT DISTINCT ON (wm.sender_name)
                    wm.sender_name,
                    wm.sender,
                    wm.received_at,
                    wm.full_text
                FROM whatsapp_messages wm
                WHERE wm.is_director = FALSE
                  AND wm.received_at > NOW() - INTERVAL '24 hours'
                  AND NOT EXISTS (
                      SELECT 1 FROM whatsapp_messages reply
                      WHERE reply.chat_id = wm.chat_id
                        AND reply.is_director = TRUE
                        AND reply.received_at > wm.received_at
                  )
                ORDER BY wm.sender_name, wm.received_at DESC
            """)
            unanswered = cur.fetchall()
            cols = [d[0] for d in cur.description]
            unanswered = [dict(zip(cols, row)) for row in unanswered]
            cur.close()
        finally:
            store._put_conn(conn)

        for msg in unanswered:
            sender_name = (msg.get("sender_name") or "").strip()
            sender_lower = sender_name.lower()
            received_at = msg.get("received_at")

            if not received_at or not sender_lower:
                continue

            # Ensure timezone-aware
            if hasattr(received_at, 'tzinfo') and received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)

            wait_minutes = (now - received_at).total_seconds() / 60

            # Match against VIP list (L1: word-boundary match)
            vip = None
            for vip_name, vip_data in vip_lookup.items():
                if _vip_name_matches(vip_name, sender_lower):
                    vip = vip_data
                    break

            if not vip:
                continue

            vip_tier = vip.get("tier", 2)

            # Check SLA breach
            sla_breached = False
            if vip_tier == 1 and wait_minutes > de_config.vip_sla_tier1_minutes:
                sla_breached = True
            elif vip_tier == 2 and wait_minutes > de_config.vip_sla_tier2_minutes:
                sla_breached = True

            if not sla_breached:
                continue

            # Check alert storm prevention (1 alert per sender per hour)
            cache_key = sender_lower
            with _sla_lock:
                last_alert = _sla_alert_cache.get(cache_key, 0)
                if now_ts - last_alert < 3600:
                    continue
                # Reserve the slot immediately to prevent races
                _sla_alert_cache[cache_key] = now_ts

            # Fire alert
            preview = (msg.get("full_text") or "")[:100]
            wait_str = f"{int(wait_minutes)}min"
            alert_text = (
                f"[VIP SLA] {sender_name} (Tier {vip_tier}) — "
                f"unanswered for {wait_str}.\n"
                f"Preview: {preview}"
            )

            if vip_tier == 1:
                # WhatsApp alert to Director
                try:
                    from outputs.whatsapp_sender import send_whatsapp
                    send_whatsapp(alert_text)
                    logger.info(f"VIP SLA alert (WhatsApp): {sender_name} — {wait_str}")
                except Exception as e:
                    logger.warning(f"VIP SLA WhatsApp alert failed: {e}")
            else:
                # Slack alert
                try:
                    from outputs.slack_notifier import SlackNotifier
                    notifier = SlackNotifier()
                    notifier.post_alert({
                        "tier": 2,
                        "title": f"VIP SLA: {sender_name} unanswered ({wait_str})",
                        "body": preview,
                        "action_required": True,
                        "contact_name": sender_name,
                    })
                    logger.info(f"VIP SLA alert (Slack): {sender_name} — {wait_str}")
                except Exception as e:
                    logger.warning(f"VIP SLA Slack alert failed: {e}")

            # Phase 3B: For Tier 2+ breaches (>4h), create DB alert + auto-draft
            if wait_minutes >= 240:
                try:
                    alert_title = f"VIP SLA: {sender_name} unanswered ({wait_str})"
                    alert_body = (
                        f"{sender_name} (Tier {vip_tier}) sent a message {wait_str} ago "
                        f"with no reply.\n\nMessage: {preview}"
                    )
                    alert_id = store.create_alert(
                        tier=2,
                        title=alert_title,
                        body=alert_body,
                        action_required=True,
                        tags=["vip-sla"],
                    )
                    if alert_id:
                        draft = _generate_vip_draft(vip, msg, sender_name, wait_minutes)
                        if draft:
                            store.update_alert_structured_actions(alert_id, draft)
                            logger.info(f"VIP auto-draft attached to alert #{alert_id}")
                except Exception as e:
                    logger.warning(f"VIP auto-draft failed for {sender_name}: {e}")

    except Exception as e:
        logger.error(f"VIP SLA check failed: {e}")


# ============================================================
# Phase 3B: VIP Auto-Draft (Haiku)
# ============================================================

_VIP_DRAFT_PROMPT = """You are Baker, AI Chief of Staff for Dimitry Vallen (Chairman, Brisen Group).

A VIP contact has sent a message that hasn't been responded to. Generate action proposals.

Rules:
- Match the Director's tone: warm but direct, like a trusted advisor
- Keep it concise — VIP messages deserve quick, substantive replies
- If the message requires a decision the Director hasn't made, acknowledge receipt and set expectations
- Always offer at least 2 options: a substantive draft and a quick acknowledgment

Return ONLY valid JSON:
{
  "problem": "VIP waiting for response — relationship risk",
  "cause": "Message received [time] ago, no reply detected",
  "solution": "Send response to maintain VIP relationship",
  "parts": [
    {
      "label": "Respond to [VIP name]",
      "actions": [
        {
          "label": "Send draft reply",
          "description": "Review and send Baker's draft response",
          "type": "draft",
          "prompt": "Draft a reply to [VIP name] regarding: [topic]. Tone: warm, direct."
        },
        {
          "label": "Acknowledge and defer",
          "description": "Quick acknowledgment — will reply in detail later",
          "type": "draft",
          "prompt": "Draft a short acknowledgment to [VIP name] saying you received their message and will reply in detail soon."
        }
      ]
    }
  ]
}
"""


def _generate_vip_draft(vip: dict, msg: dict, sender_name: str, wait_minutes: float) -> dict:
    """Generate auto-draft proposals for an unanswered VIP message using Haiku."""
    try:
        import json
        import anthropic
        from config.settings import config as _config

        vip_role = vip.get("role") or vip.get("role_context") or ""
        vip_tier = vip.get("tier", 2)
        message_text = (msg.get("full_text") or "")[:500]
        wait_str = f"{int(wait_minutes)} minutes"

        context = (
            f"VIP: {sender_name}\n"
            f"Role: {vip_role}\n"
            f"Tier: {vip_tier}\n"
            f"Wait time: {wait_str}\n"
            f"Message: {message_text}\n"
        )

        client = anthropic.Anthropic(api_key=_config.claude.api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_VIP_DRAFT_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        parsed = json.loads(raw)
        if "parts" in parsed and isinstance(parsed["parts"], list):
            logger.info(f"Generated VIP auto-draft for {sender_name}: {len(parsed['parts'])} parts")
            return parsed
        logger.warning("VIP draft missing 'parts' key — discarding")
        return None
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"VIP draft generation failed for {sender_name}: {e}")
        return None
