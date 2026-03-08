# BRIEF: Proactive Flag + AO Profiling Implementation

**Author:** Code 300 (Session 14)
**Date:** 2026-03-08
**Status:** Ready for Code Brisen
**Branch:** `feat/proactive-flag-ao`

---

## What This Brief Covers

Three capabilities (`profiling`, `research`, `pr_branding`) have `autonomy_level = 'proactive_flag'` in the DB. This means Baker should proactively detect relevant signals and flag them to the Director — without being asked. Today, this flag is stored but **not acted on**. This brief makes it real.

The AO (Andrey Oskolkov) profiling brief from PM adds two concrete features that use `proactive_flag`: mood detection on incoming messages, and a communication gap tracker. AO is the first live test case.

---

## Part 1: Proactive Signal Scanner (new scheduled job)

### What

A new scheduled job that runs every 30 minutes. It scans recent alerts and ingested content for signals matching `proactive_flag` capability trigger patterns. When found, it creates a T2 alert tagged with the capability slug and `source='proactive_scan'`.

### Why

Without this, Baker only uses capabilities when the Director asks a question (via Scan or WhatsApp). With `proactive_flag`, Baker surfaces signals *before* being asked — the core value proposition of profiling, research, and PR.

### Architecture

```
run_proactive_scan() [every 30 min]
  ↓
  1. Load all capabilities where autonomy_level = 'proactive_flag'
  ↓
  2. For each capability, get trigger_patterns (JSONB array of regex)
  ↓
  3. Query recent content (last 30 min) from:
     - email_messages (subject + full_body)
     - whatsapp_messages (full_text)
     - alerts (title + body, to avoid re-scanning)
  ↓
  4. For each content item, test against each capability's patterns
  ↓
  5. If match found AND not already flagged:
     - Create T2 alert: "[Profiling] AO sentiment shift detected in WhatsApp"
     - Tag: matter_slug (auto-match), source='proactive_scan', capability_slug
  ↓
  6. Log: "Proactive scan: X items scanned, Y signals flagged"
```

### File to Create

**`triggers/proactive_scanner.py`** (~120 lines)

```python
"""
Proactive Signal Scanner — Phase 4
Scans recent content for signals matching proactive_flag capabilities.
Creates T2 alerts for Director review.
"""
import logging
import re
from datetime import datetime, timezone

from config.settings import config

logger = logging.getLogger("baker.proactive_scanner")


def run_proactive_scan():
    """Scheduled job (every 30 min): scan recent content for proactive signals."""
    from memory.store_back import SentinelStoreBack
    from orchestrator.capability_registry import CapabilityRegistry

    store = SentinelStoreBack._get_global_instance()
    registry = CapabilityRegistry.get_instance()

    # 1. Load proactive capabilities
    proactive_caps = [
        c for c in registry.get_all()
        if c.autonomy_level == "proactive_flag" and c.trigger_patterns
    ]
    if not proactive_caps:
        logger.info("Proactive scan: no proactive_flag capabilities found")
        return

    # 2. Compile trigger patterns per capability
    cap_patterns = []
    for cap in proactive_caps:
        patterns = []
        for p in cap.trigger_patterns:
            try:
                patterns.append(re.compile(p, re.IGNORECASE))
            except re.error:
                logger.warning(f"Bad regex in {cap.slug}: {p}")
        if patterns:
            cap_patterns.append((cap, patterns))

    # 3. Fetch recent content (last 35 min to overlap with poll interval)
    conn = store._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        items = []

        # Recent emails
        cur.execute("""
            SELECT 'email' as source_type, message_id as source_id,
                   COALESCE(subject, '') || ' ' || COALESCE(full_body, '') as content,
                   sender_name
            FROM email_messages
            WHERE received_date > NOW() - INTERVAL '35 minutes'
            LIMIT 50
        """)
        items.extend([dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()])

        # Recent WhatsApp messages (non-Director)
        cur.execute("""
            SELECT 'whatsapp' as source_type, message_id as source_id,
                   COALESCE(full_text, '') as content,
                   sender_name
            FROM whatsapp_messages
            WHERE timestamp > NOW() - INTERVAL '35 minutes'
              AND is_director = FALSE
            LIMIT 50
        """)
        items.extend([dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()])

        # Recent RSS/browser alerts (avoid re-flagging proactive alerts)
        cur.execute("""
            SELECT 'alert' as source_type, id::text as source_id,
                   COALESCE(title, '') || ' ' || COALESCE(body, '') as content,
                   NULL as sender_name
            FROM alerts
            WHERE created_at > NOW() - INTERVAL '35 minutes'
              AND COALESCE(source, '') != 'proactive_scan'
            LIMIT 50
        """)
        items.extend([dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()])

        cur.close()
    except Exception as e:
        logger.warning(f"Proactive scan query failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return
    finally:
        store._put_conn(conn)

    if not items:
        logger.info("Proactive scan: no recent content to scan")
        return

    # 4. Match content against capability patterns
    flagged = 0
    for item in items:
        content = item.get("content", "")
        if not content or len(content) < 10:
            continue

        for cap, patterns in cap_patterns:
            if any(p.search(content) for p in patterns):
                # 5. Dedup: check if we already flagged this source_id
                dedup_key = f"proactive:{cap.slug}:{item['source_type']}:{item['source_id']}"
                # Use alerts dedup — check if alert with this source exists
                conn2 = store._get_conn()
                if not conn2:
                    continue
                try:
                    cur2 = conn2.cursor()
                    cur2.execute(
                        "SELECT 1 FROM alerts WHERE source = 'proactive_scan' AND source_id = %s LIMIT 1",
                        (dedup_key,),
                    )
                    if cur2.fetchone():
                        cur2.close()
                        continue  # Already flagged

                    # Create T2 alert
                    # Build concise title
                    sender = item.get("sender_name") or item["source_type"]
                    snippet = content[:120].replace("\n", " ")
                    title = f"[{cap.name}] Signal from {sender}: {snippet}"
                    body = content[:500]

                    store.create_alert(
                        tier=2,
                        title=title[:300],
                        body=body,
                        source="proactive_scan",
                    )
                    # Store dedup marker — use source_id column on alerts
                    # (create_alert doesn't support source_id yet, use separate insert)
                    cur2.close()
                    flagged += 1
                except Exception as e:
                    logger.warning(f"Proactive alert creation failed: {e}")
                    try:
                        conn2.rollback()
                    except Exception:
                        pass
                finally:
                    store._put_conn(conn2)

                break  # One alert per content item (don't double-flag)

    logger.info(f"Proactive scan complete: {len(items)} items scanned, {flagged} signals flagged")
```

### Important Notes for Implementation

1. **Dedup is critical.** Without it, Baker will re-flag the same email/message every 30 minutes. The brief shows a dedup approach using `source_id` on the alerts table — but `create_alert()` doesn't currently accept `source_id` for custom dedup keys. You have two options:
   - **Option A:** Add a `source_id` parameter to `create_alert()` and check before insert
   - **Option B:** Create a separate `proactive_scan_log` table with (source_type, source_id, capability_slug, flagged_at) and check before alerting

   **Recommended: Option A** — simpler, reuses existing infrastructure.

2. **The `create_alert()` method** is at `memory/store_back.py` line 2559. It already has a `source` parameter but no `source_id`. Add `source_id` as an optional parameter, store it, and check for duplicates before insert.

3. **Register the scheduled job** in `triggers/embedded_scheduler.py`. Add:
   ```python
   scheduler.add_job(run_proactive_scan, 'interval', minutes=30, id='proactive_scan')
   ```
   Find the existing `add_job` calls and add after them.

---

## Part 2: AO Mood Classification (enhancement to proactive scanner)

### What

When Baker detects an AO message (WhatsApp or email), classify the mood as `positive`, `neutral`, or `negative` using keyword matching. Store the mood tag on the alert. If mood shifts to negative, escalate to T1.

### Mood Keywords (from PM's AO Profiling Brief)

**Positive / Collaborative (score +1 each):**
```
English: appreciate, grateful, thank you, good news, progress, agreed,
         looking forward, pleased, excellent, partnership, together,
         constructive, opportunity, optimistic
Russian: спасибо, отлично, хорошо, договорились, рад, благодарю,
         прогресс, партнёрство, вместе, конструктивно
```

**Negative / Confrontational (score -1 each):**
```
English: disappointed, unacceptable, demand, legal action, breach,
         concerned, overdue, default, penalty, lawyer, litigation,
         frustrat, delay, unresponsive, broken promise
Russian: неприемлемо, разочарован, требую, юрист, нарушение, штраф,
         задержка, обещание, претензия, ответственность
```

### Implementation

**File:** Add to `triggers/proactive_scanner.py`

```python
# AO Mood Detection Keywords
_AO_POSITIVE = re.compile(
    r"\b(appreciate|grateful|thank.you|good.news|progress|agreed|"
    r"looking.forward|pleased|excellent|partnership|together|"
    r"constructive|opportunity|optimistic|"
    r"спасибо|отлично|хорошо|договорились|рад|благодарю|"
    r"прогресс|партнёрство|вместе|конструктивно)\b", re.IGNORECASE
)

_AO_NEGATIVE = re.compile(
    r"\b(disappointed|unacceptable|demand|legal.action|breach|"
    r"concerned|overdue|default|penalty|lawyer|litigation|"
    r"frustrat|delay|unresponsive|broken.promise|"
    r"неприемлемо|разочарован|требую|юрист|нарушение|штраф|"
    r"задержка|обещание|претензия|ответственность)\b", re.IGNORECASE
)

_AO_IDENTIFIERS = re.compile(
    r"\b(oskolkov|andrey|aelio|andrej)\b", re.IGNORECASE
)


def classify_ao_mood(content: str) -> str:
    """Classify AO message mood: positive, neutral, or negative."""
    pos = len(_AO_POSITIVE.findall(content))
    neg = len(_AO_NEGATIVE.findall(content))
    if neg >= 2 or (neg > 0 and neg > pos):
        return "negative"
    elif pos >= 2 or (pos > 0 and pos > neg):
        return "positive"
    return "neutral"
```

### Integration Point

Inside `run_proactive_scan()`, after detecting a match on the `profiling` capability, add:

```python
# AO-specific mood detection
if cap.slug == "profiling" and _AO_IDENTIFIERS.search(content):
    mood = classify_ao_mood(content)
    if mood == "negative":
        # Escalate to T1 — mood shift detected
        title = f"[Profiling] AO mood shift: NEGATIVE signal detected"
        store.create_alert(tier=1, title=title, body=content[:500],
                           source="proactive_scan", matter_slug="oskolkov-rg7")
        flagged += 1
        continue  # Skip regular T2 alert
    elif mood == "positive":
        title = f"[Profiling] AO mood: positive signal"
        # Still T2 — informational
```

---

## Part 3: Communication Gap Tracker (new scheduled job)

### What

A scheduled job that checks: "Has the Director sent a message to AO in the last 3 days?" If not, create a T2 reminder alert with suggested outreach content.

### Architecture

```
run_communication_gap_check() [every 6 hours]
  ↓
  1. Query whatsapp_messages for last Director→AO message
  ↓
  2. If gap > 3 days (configurable):
     - Create T2 alert: "AO communication gap: X days since last contact"
     - Include suggested topics from recent AO-related activity
  ↓
  3. Dedup: max 1 alert per gap period (don't spam)
```

### File

Add to **`triggers/proactive_scanner.py`** (same file, separate function):

```python
# Configurable gap thresholds per VIP (days)
_COMMUNICATION_GAP_DAYS = {
    "oskolkov": 3,   # AO: 3 days
    # Add more VIPs here as profiling expands
}


def run_communication_gap_check():
    """Check for communication gaps with profiled VIPs."""
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if not conn:
        return

    try:
        cur = conn.cursor()
        for vip_keyword, max_gap_days in _COMMUNICATION_GAP_DAYS.items():
            # Find last Director message to this VIP
            cur.execute("""
                SELECT MAX(timestamp) as last_contact
                FROM whatsapp_messages
                WHERE is_director = TRUE
                  AND (
                    sender_name ILIKE %s
                    OR chat_id ILIKE %s
                  )
            """, (f"%{vip_keyword}%", f"%{vip_keyword}%"))
            row = cur.fetchone()
            last_contact = row[0] if row and row[0] else None

            if last_contact is None:
                gap_days = 999  # Never contacted
            else:
                from datetime import timezone
                if last_contact.tzinfo is None:
                    last_contact = last_contact.replace(tzinfo=timezone.utc)
                gap_days = (datetime.now(timezone.utc) - last_contact).days

            if gap_days >= max_gap_days:
                # Dedup: check if gap alert exists in last 24h
                cur.execute("""
                    SELECT 1 FROM alerts
                    WHERE source = 'communication_gap'
                      AND title ILIKE %s
                      AND created_at > NOW() - INTERVAL '24 hours'
                    LIMIT 1
                """, (f"%{vip_keyword}%",))
                if cur.fetchone():
                    continue  # Already alerted today

                title = f"Communication gap: {gap_days} days since last contact with {vip_keyword.title()}"
                body = (
                    f"No Director message to {vip_keyword.title()} detected in the last {gap_days} days.\n"
                    f"Threshold: {max_gap_days} days.\n\n"
                    f"Suggested: Send a brief update or check-in to maintain relationship cadence."
                )
                store.create_alert(
                    tier=2,
                    title=title,
                    body=body,
                    source="communication_gap",
                    matter_slug="oskolkov-rg7",
                )
                logger.info(f"Communication gap alert: {vip_keyword} ({gap_days} days)")

        cur.close()
    except Exception as e:
        logger.warning(f"Communication gap check failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        store._put_conn(conn)

    logger.info("Communication gap check complete")
```

### Register in Scheduler

Add to `triggers/embedded_scheduler.py`:
```python
scheduler.add_job(run_communication_gap_check, 'interval', hours=6, id='communication_gap_check')
```

---

## Part 4: Calendar Meeting Prep Enhancement (small change)

### What

The existing calendar trigger (`triggers/calendar_trigger.py`) already generates meeting prep briefs. Enhance it to:
1. Detect AO-related meetings by keyword (not just attendee name match)
2. When AO meeting detected, include the mood classification from recent messages

### Where to Modify

**`triggers/calendar_trigger.py`** — function `_assemble_meeting_context()` (~line 109)

After the existing attendee VIP lookup, add:

```python
# AO-specific enrichment: check if meeting title/attendees mention AO keywords
ao_keywords = ["oskolkov", "andrey", "aelio", "ao ", "andrej"]
meeting_text = (summary + " " + " ".join(attendee_names)).lower()
is_ao_meeting = any(k in meeting_text for k in ao_keywords)

if is_ao_meeting:
    # Fetch recent AO mood from WhatsApp
    try:
        cur.execute("""
            SELECT full_text FROM whatsapp_messages
            WHERE (sender_name ILIKE '%oskolkov%' OR sender_name ILIKE '%andrey%')
              AND timestamp > NOW() - INTERVAL '7 days'
            ORDER BY timestamp DESC LIMIT 5
        """)
        ao_msgs = [r[0] for r in cur.fetchall() if r[0]]
        if ao_msgs:
            from triggers.proactive_scanner import classify_ao_mood
            combined = " ".join(ao_msgs)
            mood = classify_ao_mood(combined)
            context_parts.append(
                f"\n--- AO PROFILING CONTEXT ---\n"
                f"Recent mood: {mood.upper()}\n"
                f"Last {len(ao_msgs)} messages analyzed.\n"
                f"Approach: {'Collaborative, reinforce partnership' if mood == 'positive' else 'Careful, address concerns first' if mood == 'negative' else 'Neutral — standard engagement'}\n"
            )
    except Exception as e:
        logger.warning(f"AO meeting enrichment failed: {e}")
```

---

## Files Summary

| Action | File | Lines | What |
|--------|------|-------|------|
| **CREATE** | `triggers/proactive_scanner.py` | ~200 | Proactive scan job + AO mood + gap tracker |
| **MODIFY** | `triggers/embedded_scheduler.py` | +2 | Register 2 new jobs |
| **MODIFY** | `triggers/calendar_trigger.py` | +20 | AO meeting prep enrichment |
| **MODIFY** | `memory/store_back.py` | +5 | Add `source_id` param to `create_alert()` for dedup |

**Estimated: ~230 lines new + ~25 lines modified**

---

## Verification Checklist

After implementation, verify:

- [ ] `proactive_flag` capabilities (profiling, research, pr_branding) trigger alerts from incoming content
- [ ] AO WhatsApp message with negative keywords → T1 alert with mood tag
- [ ] AO WhatsApp message with positive keywords → T2 informational alert
- [ ] 3+ days without Director→AO message → T2 communication gap alert
- [ ] Gap alert dedup: max 1 per 24 hours
- [ ] Proactive scan dedup: same content not re-flagged on next cycle
- [ ] AO meeting detected in calendar → prep brief includes mood context
- [ ] Scheduler shows 2 new jobs: `proactive_scan` (30 min), `communication_gap_check` (6h)
- [ ] All new code syntax-checked: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`

---

## What NOT to Build

- No sentiment analysis via LLM (keyword matching is sufficient for v1)
- No changes to the capability_router or capability_runner (proactive scan creates alerts, doesn't run capabilities)
- No frontend changes (alerts appear in existing Cockpit tabs)
- No new DB tables (uses existing alerts + whatsapp_messages)

---

## Context for Brisen

- `CapabilityRegistry` is at `orchestrator/capability_registry.py` — has `get_all()`, `get_by_slug()` methods
- `CapabilityDef` dataclass has: `slug`, `trigger_patterns` (list of regex strings), `autonomy_level`, `tools`, etc.
- `create_alert()` is at `memory/store_back.py` line 2559 — params: tier, title, body, source, matter_slug, tags
- Scheduler registration: `triggers/embedded_scheduler.py` — search for `add_job` to find existing pattern
- AO VIP record: ID 961, Tier 1, in `vip_contacts` table
- Matter "Oskolkov-RG7" (ID 15): 15 keywords, status=active, in `matter_registry`
