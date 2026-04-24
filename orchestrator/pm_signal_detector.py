"""
PM Signal Detector — generic, PM_REGISTRY-driven signal detection.
Replaces ao_signal_detector.py with config-driven detection for all PMs.

For each PM in PM_REGISTRY, checks:
  - signal_orbit_patterns (sender/participant matching)
  - signal_keyword_patterns (content matching)
  - signal_whatsapp_senders (WhatsApp sender name matching)

Flags signals to pm_project_state via store.update_pm_project_state().
"""
import logging
import re

logger = logging.getLogger("baker.pm_signal")

# Lazy-compiled pattern cache: {pm_slug: {"orbit": [...], "keyword": [...], "wa": [...]}}
_COMPILED_CACHE = {}


def _get_compiled(pm_slug: str) -> dict:
    """Lazy-compile regex patterns from PM_REGISTRY. Cached after first call."""
    if pm_slug in _COMPILED_CACHE:
        return _COMPILED_CACHE[pm_slug]

    from orchestrator.capability_runner import PM_REGISTRY
    cfg = PM_REGISTRY.get(pm_slug)
    if not cfg:
        return {"orbit": [], "keyword": [], "wa": []}

    compiled = {
        "orbit": [re.compile(p, re.IGNORECASE) for p in cfg.get("signal_orbit_patterns", [])],
        "keyword": [re.compile(p, re.IGNORECASE) for p in cfg.get("signal_keyword_patterns", [])],
        "wa": [re.compile(p, re.IGNORECASE) for p in cfg.get("signal_whatsapp_senders", [])],
    }
    _COMPILED_CACHE[pm_slug] = compiled
    return compiled


def detect_relevant_pms_text(sender: str, text: str) -> list:
    """Return list of pm_slugs whose orbit/keyword patterns match sender or text."""
    from orchestrator.capability_runner import PM_REGISTRY

    sender_lower = (sender or "").lower()
    text_lower = (text or "").lower()
    hits = []

    for slug in PM_REGISTRY:
        patterns = _get_compiled(slug)
        if any(p.search(sender_lower) for p in patterns["orbit"]):
            hits.append(slug)
            continue
        if any(p.search(text_lower) for p in patterns["keyword"]):
            hits.append(slug)

    return hits


def detect_relevant_pms_whatsapp(sender_name: str, text: str) -> list:
    """Return list of pm_slugs matching WhatsApp sender or keyword patterns."""
    from orchestrator.capability_runner import PM_REGISTRY

    name_lower = (sender_name or "").lower()
    text_lower = (text or "").lower()
    hits = []

    for slug in PM_REGISTRY:
        patterns = _get_compiled(slug)
        # Check WhatsApp sender patterns
        if any(p.search(name_lower) for p in patterns["wa"]):
            hits.append(slug)
            continue
        # Fall back to keyword patterns
        if any(p.search(text_lower) for p in patterns["keyword"]):
            hits.append(slug)

    return hits


def detect_relevant_pms_meeting(title: str, participants: str) -> list:
    """Return list of pm_slugs matching meeting title/participants.
    Meetings require BOTH orbit AND keyword (short titles = low context,
    need high-confidence matching). Cowork refinement Q4.
    """
    combined = f"{title} {participants}".lower()
    from orchestrator.capability_runner import PM_REGISTRY

    hits = []
    for slug in PM_REGISTRY:
        patterns = _get_compiled(slug)
        has_orbit = any(p.search(combined) for p in patterns["orbit"])
        has_keyword = any(p.search(combined) for p in patterns["keyword"])
        # Meetings: BOTH orbit AND keyword required (high-confidence only)
        if has_orbit and has_keyword:
            hits.append(slug)

    return hits


def detect_relevant_pms_outbound(text: str) -> list:
    """Return list of pm_slugs matching outbound text against ORBIT patterns only.
    Outbound = Director sending. Use orbit (people names) not keywords to avoid
    false positives on generic terms like 'hotel' or 'budget'. Cowork Q3.
    """
    from orchestrator.capability_runner import PM_REGISTRY

    text_lower = (text or "").lower()
    hits = []

    for slug in PM_REGISTRY:
        patterns = _get_compiled(slug)
        if any(p.search(text_lower) for p in patterns["orbit"]):
            hits.append(slug)

    return hits


def flag_pm_signal(
    pm_slug: str,
    channel: str,
    source: str,
    summary: str,
    timestamp=None,
    push_slack: bool = False,
):
    """Update pm_project_state with an inbound signal. Non-fatal.

    BRIEF_PM_SIDEBAR_STATE_WRITE_1 D6: accepts ``push_slack`` to optionally
    DM the Director (channel D0AFY28N030) when the signal fires. Defaults to
    False to preserve existing email/WhatsApp signal flow volume; only new
    meeting-ingest wiring passes True.
    """
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()

        signal_data = {
            "relationship_state": {
                "last_inbound_channel": channel,
                "last_inbound_from": source[:200],
                "last_inbound_summary": summary[:300],
            }
        }
        if timestamp:
            signal_data["relationship_state"]["last_inbound_at"] = (
                timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)
            )

        store.update_pm_project_state(
            pm_slug,
            updates=signal_data,
            summary=f"PM signal [{channel}]: {source} — {summary[:100]}",
            mutation_source=f"pm_signal_{channel}",
        )
        logger.info(f"PM signal flagged [{pm_slug}][{channel}]: {source}")

        # BRIEF_CAPABILITY_THREADS_1: attribute the signal to its thread.
        # Known partial attribution (Part H §H2): signal turn carries thread_id,
        # but pm_state_history.thread_id stays NULL for this surface — full
        # closure would require refactoring flag_pm_signal's call sequence and
        # is deliberately out of scope (documented in brief §H2 table).
        try:
            from orchestrator.capability_threads import (
                stitch_or_create_thread, persist_turn,
            )
            _q = f"[signal {channel}] {source}"
            thread_id, stitch_decision = stitch_or_create_thread(
                pm_slug=pm_slug,
                question=_q,
                answer=summary,
                topic_summary_hint=f"{channel}: {source} — {summary[:200]}",
                surface="signal",
            )
            persist_turn(
                pm_slug=pm_slug, thread_id=thread_id, surface="signal",
                mutation_source=f"pm_signal_{channel}",
                question=_q, answer=summary,
                state_updates=signal_data, stitch_decision=stitch_decision,
            )
        except Exception as _thread_e:
            logger.warning(
                f"Thread attribution for signal [{pm_slug}][{channel}] failed "
                f"(non-fatal): {_thread_e}"
            )

        if push_slack:
            try:
                from outputs.slack_notifier import post_to_channel
                label = pm_slug.upper().replace("_", " ")
                text = (
                    f"*{label}*: new {channel} ingest relevant to active thread.\n"
                    f"Source: {source[:160]}\n"
                    f"Summary: {summary[:280]}"
                )
                post_to_channel(channel_id="D0AFY28N030", text=text)
            except Exception as _slack_e:
                logger.warning(
                    f"PM signal Slack push failed [{pm_slug}][{channel}]: {_slack_e}"
                )
    except Exception as e:
        logger.warning(f"PM signal flag failed [{pm_slug}]: {e}")
