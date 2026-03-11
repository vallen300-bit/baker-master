# BRIEF: CHANNEL-TRUST-1 — Source-Based Routing (WhatsApp all-equal, Email filtered)

**Author:** AI Head (Session 20)
**For:** Code 300 (fresh instance)
**Priority:** HIGH
**Estimated scope:** 3 files, ~100 lines changed

---

## Problem

Baker treats contacts as VIP vs non-VIP. Director decision (Session 19+20): **all people are equal**. The real trust signal is the **channel**, not the person:

- **WhatsApp** = trusted channel. No spam ever. Every message matters.
- **Email** = noisy channel. Spam, marketing, newsletters pollute the feed.

Currently Baker skips non-VIP senders in SLA checks and gives them lower scores. This means real business contacts on WhatsApp get ignored if they're not in the VIP list.

## Solution

Replace VIP-based gatekeeping with **source-based routing**:

1. **WhatsApp path**: All senders get equal treatment, no VIP check
2. **SLA monitoring**: Track ALL WhatsApp conversations, not just VIP contacts
3. **Email path**: Keep contact-based filtering (known contacts bypass, unknown senders stay lower priority)

## Changes Required

### File 1: `orchestrator/decision_engine.py`

#### Change 1A: `_score_relationship()` (line 323)
Currently returns 1 for non-VIPs. Add source-awareness:

```python
def _score_relationship(sender: str, vips: list, source: str = "") -> int:
    """Score 1-3: relationship weight. WhatsApp senders always score 2+."""
    # WhatsApp = trusted channel — everyone matters
    if source == "whatsapp":
        # Still check VIP for tier 1 boost, but floor is 2
        sender_lower = (sender or "").lower().strip()
        for vip in vips:
            vip_name = (vip.get("name") or "").lower()
            if _vip_name_matches(vip_name, sender_lower):
                tier = vip.get("tier", 2)
                if tier == 1:
                    return 3
                return 2
        return 2  # WhatsApp non-VIP still gets score 2 (not 1)

    # Email/other sources: keep existing VIP-based scoring
    sender_lower = (sender or "").lower().strip()
    for vip in vips:
        vip_name = (vip.get("name") or "").lower()
        if _vip_name_matches(vip_name, sender_lower):
            tier = vip.get("tier", 2)
            if tier == 1:
                return 3
            return 2
    return 1
```

#### Change 1B: `score_trigger()` (line 538)
Pass `source` to `_score_relationship`:

```python
# Line 538 — change:
relationship_score = _score_relationship(sender, vips)
# To:
relationship_score = _score_relationship(sender, vips, source=source)
```

#### Change 1C: `run_vip_sla_check()` (line 599)
Rewrite to check ALL WhatsApp conversations, not just VIP contacts:

The current logic:
1. Fetch unanswered WhatsApp messages
2. Match each sender against VIP list
3. Skip if not VIP (`if not vip: continue`)
4. Check SLA based on VIP tier

New logic:
1. Fetch unanswered WhatsApp messages (same query)
2. For each unanswered message:
   - Look up sender in contacts table → get tier (default tier 2 if not found)
   - **Remove the `if not vip: continue` gate** — ALL unanswered WA messages are checked
   - Use tier from contacts table if found, otherwise default tier 2
3. SLA thresholds:
   - Tier 1 contacts: >15 min → WhatsApp alert
   - All others (tier 2 or unknown): >4 hours → Slack alert
4. Keep alert storm prevention (4h cooldown) and auto-draft generation

Key change at line 696:
```python
# REMOVE this gate:
# if not vip:
#     continue

# REPLACE with: default to tier 2 if sender not in contacts
if not vip:
    vip = {"name": sender_name, "tier": 2}  # treat as standard contact
```

Also update all the log messages and alert text to say "SLA" instead of "VIP SLA":
- Line 728: `"[SLA] {sender_name} (Tier {vip_tier})"` (was `"[VIP SLA]"`)
- Line 738: `"SLA alert (WhatsApp):"` (was `"VIP SLA alert"`)
- Line 748: `"SLA: {sender_name} unanswered"` (was `"VIP SLA:"`)
- Line 753: `"SLA alert (Slack):"` (was `"VIP SLA alert"`)
- Line 761: source_id stays `f"vip-sla-{sender_lower}"` (internal, no rename needed)
- Line 776: tags stay `["vip-sla"]` (internal, no rename needed)
- Line 788: `"SLA check complete:"` (was `"VIP SLA check complete"`)
- Update the docstring at line 600-603

### File 2: `triggers/embedded_scheduler.py`

#### Change 2A: Re-enable SLA check (line 182-191)
The SLA check was disabled because it only checked VIPs. Now that it checks everyone on WhatsApp, re-enable it:

```python
# Uncomment the scheduler registration:
from orchestrator.decision_engine import run_vip_sla_check
scheduler.add_job(
    run_vip_sla_check,
    "interval", minutes=5,
    id="vip_sla_check", name="WhatsApp SLA monitoring",
    misfire_grace_time=120,
)
```

Remove the "DISABLED" log line.

### File 3: `orchestrator/deadline_manager.py`

#### Change 3A: Priority classification (line 195-213)
The `_classify_priority_from_speaker()` function checks VIP contacts. This is used for deadline priority. No change needed here — it's fine to give known contacts higher deadline priority.

**No changes to this file.**

## What NOT to Change

- **Table name**: Keep `vip_contacts` as-is (DB migration is a separate task)
- **Function names**: Keep `_get_vips()`, `add_vip_contact()` etc as internal names
- **Email scoring**: Keep VIP-based scoring for emails — they need the filter
- **Domain classification**: `_classify_domain()` uses VIP cache for domain tagging — keep this
- **Mode tagging**: `_tag_mode()` uses VIP list — keep this

## Testing

After changes, verify:
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/decision_engine.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"`
3. Check that `score_trigger("hello", "Unknown Person", "whatsapp")` returns `relationship_score >= 2`
4. Check that `score_trigger("hello", "Unknown Person", "email")` returns `relationship_score == 1`

## Summary

| What | Before | After |
|------|--------|-------|
| WhatsApp unknown sender score | 1 (ignored) | 2 (important) |
| WhatsApp SLA monitoring | VIP-only | ALL conversations |
| Email unknown sender score | 1 | 1 (unchanged) |
| SLA check scheduler | DISABLED | RE-ENABLED |
