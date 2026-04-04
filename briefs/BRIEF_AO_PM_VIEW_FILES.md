# BRIEF: AO-PM-VIEW — View Files Architecture for AO Project Manager

## Context
The AO PM capability exists and works (capability_sets, ao_project_state, tools). But ALL knowledge — psychology, investment channels, agenda, communication rules — lives in a single SQL JSONB blob. This makes it unreadable, uneditable, and opaque.

Director and AI Head designed a new architecture: **View → Data → Reasoning → Thoughts → Actions.** The "view" is 5-6 small `.md` files that Baker reads in full at every AO PM invocation. These files are the lens through which Baker interprets all AO data. They replace the JSONB-stored stable knowledge while SQL keeps the dynamic state.

Additionally: AO PM is not in the daily briefing pipeline (reactive only), and inbound AO emails don't trigger AO PM awareness.

Full architecture document: `Desktop/AO_PM_ARCHITECTURE_V2.md`

## Estimated time: ~4h
## Complexity: Medium
## Prerequisites: None — all infrastructure exists

---

## Fix 1: Create View Files Directory and Files

### Problem
AO PM's compiled intelligence (psychology, investment channels, sensitive issues, communication rules) is buried in `ao_project_state.state_json` JSONB. Director cannot read or edit it without SQL queries. LLM must parse JSON instead of reading native markdown.

### Current State
- `ao_project_state` table exists with `state_key='current'`, `state_json` JSONB containing `ao_psychology`, `investment_channels`, `sensitive_issues`, `communication_rules`, `pending_discussion_with_ao`, `sub_matters`, etc.
- No `data/` directory exists in the repo.

### Implementation

**Step 1:** Create directory structure:
```bash
mkdir -p data/ao_pm
```

**Step 2:** Create `data/ao_pm/SCHEMA.md`:
```markdown
# AO PM — View Files

These files are Baker's compiled view on Andrey Oskolkov.
Read ALL files at every AO PM invocation. No exceptions.

| File | Contains | Owner |
|------|----------|-------|
| psychology.md | Hunter archetype, 11 drivers, loyalty algorithm, vulnerability | Director |
| investment_channels.md | Channel 1 (Hayford), Channel 2 (Cyprus), total position | Director + Constantinos |
| agenda.md | Active matters (3-5) + parked matters | Director + Baker |
| sensitive_issues.md | Minefields and dance instructions | Director only |
| communication_rules.md | Rule Zero, hunting cycle, framing principles | Director |

## Rules
- Director edits are gospel.
- If data contradicts the view, flag it — don't override autonomously.
- When Director says "update the view" — edit the file and commit.
```

**Step 3:** Create `data/ao_pm/psychology.md`:

Content source: current `ao_project_state.state_json -> ao_psychology` JSONB. Convert to readable markdown. The full content is already defined — extract from DB and format as markdown with these sections:
- Core Archetype (The Hunter)
- Core Relationship (22 years since 2004)
- Critical Vulnerability (AO quote: "You only call me when you need money")
- 11 Return Drivers (ranked list with descriptions)
- Loyalty Algorithm (Ettore case study with 4 triggers)

**Step 4:** Create `data/ao_pm/investment_channels.md`:

Content source: `ao_project_state.state_json -> investment_channels` JSONB. Format as markdown with:

**CRITICAL: The file MUST open with the total, not the channel breakdown. This prevents the most dangerous recurring error — quoting Channel 2 (EUR 50.4M) as AO's total investment.**

Structure must be:
```markdown
# AO Investment in RG7

## TOTAL
AO's total investment = BOTH channels combined. Always.
For the current confirmed figure, check LIVE STATE (financial_summary.total).
NEVER quote Channel 2 alone as the total. NEVER use a stale number from this file.

Approximate total as of last view file update (Apr 2026): ~EUR 67.3M.
But LIVE STATE is authoritative — capital calls change this number.

If LIVE STATE total seems wrong (e.g., drops below EUR 60M or jumps above EUR 80M
without a known capital event), flag to Director immediately — data may be corrupted.

## Channel 1 — Hayford (Pre-Constantinos)
~EUR 19.3M ... (historical, unlikely to change)

## Channel 2 — Cyprus (Constantinos-managed)
EUR 50.4M as of Apr 2026 ... (grows with each capital call)

## Total Position
45-48% quasi-equity ...
```

**Key design: the view file holds the STRUCTURE (two channels, warnings, sanity checks). SQL live state holds the CURRENT NUMBER.** When a capital call lands:
1. New Source of Truth document saved to Dropbox
2. SQL `financial_summary.total` updated with confirmed figure
3. View file does NOT need updating — structure hasn't changed
4. AO PM reads both: view for the lens, SQL for the current figure

The approximate figure in the view file serves as a **sanity check** — if SQL suddenly shows EUR 20M, something is wrong. But the authoritative current number lives in SQL where it updates without a git commit.

Sections:
- TOTAL at the top with warning + pointer to LIVE STATE (most important — read first by LLM)
- Channel 1 — Hayford (pre-Constantinos): ~EUR 19.3M, vehicle, equity entitlement, 3% dispute
- Channel 2 — Cyprus (Constantinos-managed): current figure in SQL, components table, confirmed by Constantinos
- Total Position: 45-48% quasi-equity, where the dispute sits
- Source of Truth references (Dropbox paths)
- Sanity check ranges (flag if total outside EUR 60-80M without known cause)

**Step 5:** Create `data/ao_pm/sensitive_issues.md`:

Content source: `ao_project_state.state_json -> ao_psychology -> sensitive_issues` JSONB. Format as:
- Issue 1: The 3% question (48 vs 45) — detail + dance instruction
- Issue 2: Lender/equity contradiction — detail + dance instruction
- Issue 3: Co-ownership bitter taste — detail + dance instruction
- Note: institutional pivot is NOT stored anywhere in Baker. Director is the firewall.

**Step 6:** Create `data/ao_pm/communication_rules.md`:

Content source: `ao_project_state.state_json -> ao_psychology -> communication_rules` array. Format as markdown with:
- Rule Zero (with full explanation)
- Hunting Cycle Framework (6 phases with descriptions)
- Framing Table (Don't say X → Say Y)
- Quiet Period Playbook
- Ettore Principle
- Number Safety section:
  ```markdown
  ## Number Safety
  - AO's total investment = BOTH channels combined. Always check LIVE STATE for current figure.
  - As of Apr 2026: ~EUR 67.3M. This number GROWS with each capital call.
  - NEVER quote EUR 50.4M as the total — that is Channel 2 (Cyprus) only.
  - NEVER quote EUR 19.3M as the total — that is Channel 1 (Hayford) only.
  - NEVER use the approximate figure from this file if LIVE STATE has a more recent confirmed total.
  - If in doubt, say "approximately EUR 67 million across all instruments" (update this floor as capital calls land).
  - This is the most common error in Baker's history on AO matters.
  ```

**Step 7:** Create `data/ao_pm/agenda.md`:

Content source: `memory/monaco-debrief-state.md` session notes. Structure as:

```markdown
# AO Agenda

## Active Matters
(3-5 items with full context: description, hunting phase, status, Director's position)

## Parked Matters
(Everything else: one-line status, date parked)
```

Active matters (initial):
1. Capital Call EUR 6M — wounded_animal→reframe, locked
2. Hagenauer Acquisition — reframe (sausage→hunt), locked
3. Apartment Completion / Sales Unlock — wounded_animal, locked

Parked (initial — from debrief):
- AlpenGold Davos: not discussed, pending
- Kempinski Kitzbühel: not discussed, pending
- FX Mayr: pending
- Tuscany/La Piana: DEAD (Ettore killed it)
- Participation Agreement 48/45: deferred to exit
- Lilienmatt/Aukera: not discussed
- Private Loans: pending
- Russian Tax: pending
- KYC/Sparkasse: pending
- Francesca/MO Working Capital: pending
- Robb Report/YCM: pending
- Woosley Brand: pending
- Sellers Meeting: pending
- MO on Kitzbühel: pending
- Update Doc (stale): pending

### Key Constraints
- Do NOT include any "blind" items (institutional pivot) in agenda.md. Ever.
- Agenda file uses hunting cycle tags but ONLY for active matters.
- Parked items get minimal state — one line each.

### Verification
```bash
ls -la data/ao_pm/
# Should show: SCHEMA.md, psychology.md, investment_channels.md, sensitive_issues.md, communication_rules.md, agenda.md
cat data/ao_pm/SCHEMA.md
# Should show the schema table
```

---

## Fix 2: Update Capability Runner to Load View Files

### Problem
`capability_runner.py` currently injects AO state from SQL JSONB into the system prompt via `_get_ao_project_state_context()` (line 1107). It doesn't know about view files.

### Current State
File: `orchestrator/capability_runner.py`
- Line 704: `if capability.slug == "ao_pm":`
- Line 705: `ao_ctx = self._get_ao_project_state_context()`
- Line 706-707: Injects JSONB summary into prompt as `## CURRENT AO STATE`
- `_get_ao_project_state_context()` at line 1107: reads `ao_project_state`, formats relationship_state, open_actions, red_flags as text

### Implementation

**Step 1:** Add a new method `_load_ao_view_files()` to the `CapabilityRunner` class (near line 1107, alongside `_get_ao_project_state_context`):

```python
def _load_ao_view_files(self) -> str:
    """Load AO PM view files from data/ao_pm/ directory."""
    import os
    view_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "ao_pm")
    if not os.path.isdir(view_dir):
        logger.warning("AO PM view directory not found: %s", view_dir)
        return ""

    parts = []
    # Read in defined order: schema first, then knowledge files
    file_order = [
        "SCHEMA.md",
        "psychology.md",
        "investment_channels.md",
        "sensitive_issues.md",
        "communication_rules.md",
        "agenda.md",
    ]
    for fname in file_order:
        fpath = os.path.join(view_dir, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                parts.append(f"## VIEW FILE: {fname}\n{content}")
            except Exception as e:
                logger.warning("Failed to read AO view file %s: %s", fname, e)

    return "\n\n---\n\n".join(parts) if parts else ""
```

**Step 2:** Modify the AO PM block in `_build_system_prompt()` (line 704-707). Replace the current JSONB-only injection with view files + live state:

```python
if capability.slug == "ao_pm":
    # View files: stable compiled intelligence (psychology, channels, rules)
    view_ctx = self._load_ao_view_files()
    if view_ctx:
        prompt += f"\n\n# AO PM VIEW (from data/ao_pm/)\n{view_ctx}\n"

    # Live state: dynamic data (last contact, actions, flags, pending items)
    ao_ctx = self._get_ao_project_state_context()
    if ao_ctx:
        prompt += f"\n\n# LIVE STATE (from PostgreSQL)\n{ao_ctx}\n"
```

**Step 3:** Update `_get_ao_project_state_context()` (line 1107) to EXCLUDE fields that are now in view files. Only return dynamic state:

The function currently returns: relationship_state, open_actions, red_flags, sub-matters summaries.

Keep: `relationship_state` (last contact date, mood), `open_actions`, `red_flags`, `pending_discussion_with_ao`, `financial_summary`, `decisions_log`

Remove from this function: `ao_psychology` (now in psychology.md), `investment_channels` (now in investment_channels.md), `communication_rules` (now in communication_rules.md)

The current function only outputs relationship_state, open_actions, and red_flags — so no removal needed. Just verify it doesn't also dump the full JSONB.

### Key Constraints
- Do NOT remove `_get_ao_project_state_context()` — it still provides live state.
- View files are READ-ONLY from capability_runner. Baker never writes to them at runtime.
- File reading is synchronous and fast (~1ms for 5 small files). No async needed.
- If `data/ao_pm/` directory doesn't exist, fall back gracefully to current JSONB-only behavior.

### Verification
```python
# Syntax check
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"

# Verify files load
python3 -c "
import os
view_dir = 'data/ao_pm'
for f in os.listdir(view_dir):
    print(f'{f}: {os.path.getsize(os.path.join(view_dir, f))} bytes')
"
```

---

## Fix 3: Add AO PM to Daily Briefing Pipeline

### Problem
AO PM is reactive — only invoked when someone asks about AO. Rule Zero ("never let silence precede an ask") and the 14-day communication gap alert only fire if AO PM happens to be invoked. Baker has no proactive AO awareness.

### Current State
File: `triggers/briefing_trigger.py`
- `gather_briefing_context()` (line 26): Gathers priorities, overnight queue, pending alerts, active deals, Owner's Lens
- `generate_morning_briefing()` (line 189): Calls `gather_briefing_context()`, builds prompt, runs `pipeline.run(trigger)`
- Owner's Lens query (line 132): Searches alerts for strategic keywords — does NOT include Oskolkov/AO/Aelio/RG7
- AO PM is NOT mentioned anywhere in this file

### Implementation

**Step 1:** Add a new function `_gather_ao_pm_context()` in `briefing_trigger.py` (after `gather_briefing_context`, around line 163):

```python
def _gather_ao_pm_context() -> str:
    """
    Gather AO-specific context for the daily briefing.
    Checks: communication gap, pending discussion items, approaching deadlines.
    This gives Opus the raw material to reason through the AO psychology lens.
    """
    parts = []
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return ""
        try:
            cur = conn.cursor()

            # 1. Last AO-directed communication (email + WhatsApp)
            cur.execute("""
                SELECT 'email' as channel, MAX(sent_at) as last_contact
                FROM sent_emails
                WHERE to_address ILIKE '%%oskolkov%%' OR to_address ILIKE '%%aelio%%'
                UNION ALL
                SELECT 'whatsapp', MAX(created_at)
                FROM whatsapp_messages
                WHERE direction = 'outbound'
                  AND (chat_id LIKE '%%oskolkov%%' OR full_text ILIKE '%%andrey%%')
                LIMIT 5
            """)
            contacts = cur.fetchall()
            last_contact = None
            for row in contacts:
                if row[1] and (last_contact is None or row[1] > last_contact):
                    last_contact = row[1]

            if last_contact:
                from datetime import datetime, timezone
                gap_days = (datetime.now(timezone.utc) - last_contact).days
                parts.append(f"AO COMMUNICATION GAP: {gap_days} days since last outbound")
                if gap_days >= 10:
                    parts.append("  ** WARNING: Approaching Rule Zero threshold (14 days) **")
                if gap_days >= 14:
                    parts.append("  ** CRITICAL: Rule Zero violated — silence preceding ask **")
            else:
                parts.append("AO COMMUNICATION GAP: Unknown — no outbound records found")

            # 2. Pending discussion items count
            cur.execute("""
                SELECT jsonb_array_length(state_json->'pending_discussion_with_ao')
                FROM ao_project_state
                WHERE state_key = 'current'
                LIMIT 1
            """)
            row = cur.fetchone()
            pending_count = row[0] if row and row[0] else 0
            if pending_count > 0:
                parts.append(f"AO PENDING ITEMS: {pending_count} items awaiting discussion with AO")

            # 3. AO-related deadlines approaching
            cur.execute("""
                SELECT description, due_date
                FROM deadlines
                WHERE status = 'active'
                  AND due_date <= NOW() + INTERVAL '14 days'
                  AND (description ILIKE '%%oskolkov%%' OR description ILIKE '%%aelio%%'
                       OR description ILIKE '%%aukera%%' OR description ILIKE '%%rg7%%'
                       OR description ILIKE '%%capital call%%')
                ORDER BY due_date
                LIMIT 5
            """)
            deadlines = cur.fetchall()
            if deadlines:
                dl_lines = [f"  - {d[0]}: {d[1].strftime('%Y-%m-%d')}" for d in deadlines]
                parts.append(f"AO DEADLINES (next 14 days):\n" + "\n".join(dl_lines))

            cur.close()
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning(f"AO PM briefing context failed: {e}")
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning(f"AO PM briefing context outer error: {e}")

    return "\n".join(parts) if parts else ""
```

**Step 2:** Wire it into `gather_briefing_context()`. Add after the Owner's Lens section (around line 161), before the `return`:

```python
    # 5. AO PM — Investor relationship health check
    ao_ctx = _gather_ao_pm_context()
    if ao_ctx:
        sections.append(f"AO INVESTOR RELATIONSHIP STATUS:\n{ao_ctx}")
```

**Step 3:** Update the Owner's Lens regex (line 137) to include AO-related keywords:

Current regex (line 137):
```
'(Mandarin.Oriental|MOHG|MO.Vienna|MORV|branded.residence|luxury.hotel|sovereign.wealth|family.office|joint.venture|co.invest|strategic.partner)'
```

Add to this regex: `|Oskolkov|Aelio|capital.call|Hagenauer`

And in the names regex (line 140):
```
'(Soulier|Yurkovich|UBM|Wertheimer|Kulibayev|Strothotte|CITIC|Al.Thani)'
```

Add: `|Oskolkov|Buchwalder|Pohanis`

### Key Constraints
- Do NOT invoke AO PM capability in the briefing pipeline (too expensive — full Opus agent loop). Just gather raw context that the briefing LLM can reason about.
- All SQL queries MUST have LIMIT clauses.
- All except blocks MUST call `conn.rollback()`.
- The briefing prompt already goes through `pipeline.run()` which uses Opus — the AO context section gives Opus the data to reason with.
- Column names: verify `sent_emails.sent_at`, `whatsapp_messages.created_at`, `whatsapp_messages.direction`, `whatsapp_messages.chat_id` exist before deploying.

### Verification
```sql
-- Check column names exist
SELECT column_name FROM information_schema.columns WHERE table_name = 'sent_emails' AND column_name IN ('sent_at', 'to_address') LIMIT 5;
SELECT column_name FROM information_schema.columns WHERE table_name = 'whatsapp_messages' AND column_name IN ('created_at', 'direction', 'chat_id', 'full_text') LIMIT 5;

-- Test the gap query manually
SELECT 'email' as channel, MAX(sent_at) as last_contact
FROM sent_emails
WHERE to_address ILIKE '%oskolkov%' OR to_address ILIKE '%aelio%'
LIMIT 1;
```

---

## Fix 4: Add AO Signal Detection Across All Three Channels

### Problem
AO PM has no real-time awareness of AO-related signals between daily briefings. The three primary intelligence sources for AO PM are:

1. **WhatsApp (DV↔AO direct)** — highest value, real-time, AO actually replies here
2. **Fireflies (meeting transcripts)** — highest context, post-meeting
3. **Director debrief sessions** — compiled intelligence (handled by Director, not automated)

Email from AO's orbit (Buchwalder, Constantinos, etc.) is secondary — operational signals.

**AO himself never sends emails. WhatsApp and meetings are where AO communicates.**

### Current State

**WhatsApp:** `triggers/waha_webhook.py`
- Line 34: `DIRECTOR_WHATSAPP = "41799605092@c.us"`
- Line 946: When sender is Director, routes to `_handle_director_message()`
- Line 876: For non-Director senders, stores interaction in contacts
- Messages stored to `whatsapp_messages` table
- No AO-specific detection exists — WhatsApp from AO (replies to DV) is stored but not flagged to ao_project_state

**Meetings:** `orchestrator/meeting_pipeline.py`
- Line 266: `process_meeting(transcript_id, title, participants, meeting_date, full_transcript)`
- Called as background thread from `fireflies_trigger.py`
- Runs extraction engine, generates summary, stores to DB
- No AO-specific detection — a meeting with AO is processed generically

**Email:** `triggers/email_trigger.py`
- Standard pipeline: fetch → store → `pipeline.run(trigger)`
- No AO-orbit detection

### Implementation

**Step 1:** Create a shared AO signal detection module. New file `orchestrator/ao_signal_detector.py`:

```python
"""
AO Signal Detector — flags AO-relevant events across all channels.
Updates ao_project_state.relationship_state so AO PM has real-time awareness.

Three channels (ranked by importance):
1. WhatsApp (DV↔AO direct) — AO actually replies here
2. Fireflies (meeting transcripts) — post-meeting intelligence
3. Email (AO orbit: Buchwalder, Constantinos, Aelio, etc.) — operational signals
"""
import logging
import re

logger = logging.getLogger("baker.ao_signal")

# AO's WhatsApp ID — the PRIMARY channel
AO_WHATSAPP_ID = "79166641468@c.us"  # Verify this from vip_contacts

# People in AO's orbit (for email/meeting detection)
_AO_ORBIT_PATTERNS = [
    r'buchwalder|gantey',       # AO's Swiss lawyer
    r'pohanis|constantinos',    # Cyprus coordinator
    r'ofenheimer|alric',        # Hagenauer lawyer (RG7-relevant)
    r'@aelio\.',                # Aelio Holding domain
    r'@mandarin',               # MO hotel operations
    r'aukera',                   # Financing team
]

_AO_KEYWORD_PATTERNS = [
    r'capital.call',
    r'rg7|riemergasse',
    r'aelio|lcg',
    r'oskolkov|andrey',
    r'participation.agreement',
    r'shareholder.loan',
]


def is_ao_whatsapp(sender_id: str) -> bool:
    """Check if a WhatsApp message is from AO himself."""
    return sender_id == AO_WHATSAPP_ID


def is_ao_relevant_text(sender: str, text: str) -> bool:
    """Check if sender is in AO orbit or text contains AO keywords."""
    sender_lower = (sender or "").lower()
    text_lower = (text or "").lower()
    if any(re.search(p, sender_lower) for p in _AO_ORBIT_PATTERNS):
        return True
    return any(re.search(p, text_lower) for p in _AO_KEYWORD_PATTERNS)


def is_ao_relevant_meeting(title: str, participants: str) -> bool:
    """Check if a meeting involves AO or AO-orbit people."""
    text = f"{title} {participants}".lower()
    # Direct AO involvement
    if re.search(r'oskolkov|andrey|ao\b', text):
        return True
    # AO orbit involvement on AO-related topic
    has_orbit = any(re.search(p, text) for p in _AO_ORBIT_PATTERNS)
    has_keyword = any(re.search(p, text) for p in _AO_KEYWORD_PATTERNS)
    return has_orbit and has_keyword


def flag_ao_signal(channel: str, source: str, summary: str, timestamp=None):
    """Update ao_project_state with an inbound AO signal."""
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
                timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp)
            )

        store.update_ao_project_state(
            updates=signal_data,
            summary=f"AO signal [{channel}]: {source} — {summary[:100]}",
            mutation_source=f"ao_signal_{channel}",
        )
        logger.info(f"AO signal flagged [{channel}]: {source}")
    except Exception as e:
        logger.warning(f"AO signal flag failed: {e}")
```

**Step 2:** Wire into WhatsApp webhook (`triggers/waha_webhook.py`).

Find the message storage section (around line 837, after `whatsapp_messages` INSERT). Add:

```python
# AO-PM-VIEW: Detect AO WhatsApp signals
try:
    from orchestrator.ao_signal_detector import is_ao_whatsapp, flag_ao_signal
    if is_ao_whatsapp(sender):
        # AO himself replied — highest value signal
        flag_ao_signal("whatsapp", "AO direct", combined_body[:200])
except Exception:
    pass  # Non-fatal
```

Also: when Director sends TO AO (outbound), update the communication gap tracker. Find the Director message handling (line 946) and add:

```python
# AO-PM-VIEW: Track outbound to AO (for Rule Zero gap monitoring)
if "oskolkov" in combined_body.lower() or "andrey" in combined_body.lower():
    try:
        from orchestrator.ao_signal_detector import flag_ao_signal
        flag_ao_signal("whatsapp_outbound", "DV to AO", combined_body[:200])
    except Exception:
        pass
```

**Step 3:** Wire into meeting pipeline (`orchestrator/meeting_pipeline.py`).

In `process_meeting()` (line 266), after meeting type classification (line 285), add:

```python
# AO-PM-VIEW: Detect AO-relevant meetings
try:
    from orchestrator.ao_signal_detector import is_ao_relevant_meeting, flag_ao_signal
    if is_ao_relevant_meeting(title, participants):
        flag_ao_signal("meeting", f"{title} ({participants[:100]})",
                       f"Meeting with AO-orbit participants", meeting_date)
        logger.info(f"AO-relevant meeting detected: {title}")
except Exception:
    pass  # Non-fatal
```

**Step 4:** Wire into email processing (`triggers/email_trigger.py`).

Find where emails are processed after storage (before `pipeline.run(trigger)` call), add:

```python
# AO-PM-VIEW: Detect AO-orbit emails
try:
    from orchestrator.ao_signal_detector import is_ao_relevant_text, flag_ao_signal
    if is_ao_relevant_text(sender, f"{subject} {body[:500]}"):
        flag_ao_signal("email", sender, subject[:200])
except Exception:
    pass  # Non-fatal
```

### Key Constraints
- **WhatsApp is the primary channel.** AO replies to DV on WhatsApp. This is the highest-value signal.
- **Fireflies meetings are the second channel.** A meeting with AO or AO-orbit people on AO topics should flag.
- **Email is tertiary.** AO never emails. His orbit does.
- All detection is **non-fatal** — wrapped in try/except, never breaks the parent pipeline.
- All detection **only updates state** — does NOT invoke AO PM capability (too expensive per-message).
- `AO_WHATSAPP_ID` must be verified from `vip_contacts` table before deployment.
- The `flag_ao_signal` function uses `update_ao_project_state` which does deep merge — safe for concurrent updates.

### Verification
```sql
-- Verify AO's WhatsApp ID
SELECT whatsapp_id FROM vip_contacts WHERE name ILIKE '%oskolkov%' LIMIT 1;

-- After an AO WhatsApp reply, check state was updated
SELECT state_json->'relationship_state'->'last_inbound_channel',
       state_json->'relationship_state'->'last_inbound_from',
       state_json->'relationship_state'->'last_inbound_summary'
FROM ao_project_state WHERE state_key = 'current' LIMIT 1;

-- Syntax check new module
python3 -c "import py_compile; py_compile.compile('orchestrator/ao_signal_detector.py', doraise=True)"
```

---

## Fix 5: Clean SQL — Remove Migrated Stable Data

### Problem
After view files are live and capability_runner loads them, the stable knowledge in `ao_project_state.state_json` JSONB is duplicated. Remove to prevent contradictions.

### Current State
`ao_project_state.state_json` contains both:
- Stable: `ao_psychology`, `investment_channels`, `sensitive_issues` (migrated to files)
- Dynamic: `relationship_state`, `open_actions`, `pending_discussion_with_ao`, `red_flags`, `financial_summary`, `decisions_log` (stays in SQL)

### Implementation

**Run AFTER confirming Fix 1 and Fix 2 are deployed and working.**

```sql
-- Remove migrated stable knowledge from JSONB
-- Keep: relationship_state, open_actions, pending_discussion_with_ao,
--        red_flags, financial_summary, decisions_log, sub_matters, document_inventory
UPDATE ao_project_state
SET state_json = state_json
    - 'ao_psychology'
    - 'investment_channels'
WHERE state_key = 'current';
```

### Key Constraints
- Do NOT run this until Fix 1 (files created) and Fix 2 (runner loads files) are both verified working.
- Take a backup of current state_json first: `SELECT state_json FROM ao_project_state WHERE state_key = 'current'` — save output.
- `communication_rules` is inside `ao_psychology`, so removing `ao_psychology` removes both.

### Verification
```sql
-- Confirm stable keys are gone
SELECT state_json ? 'ao_psychology' as has_psych,
       state_json ? 'investment_channels' as has_channels
FROM ao_project_state WHERE state_key = 'current';
-- Should return: false, false

-- Confirm dynamic keys still present
SELECT state_json ? 'relationship_state' as has_rel,
       state_json ? 'open_actions' as has_actions,
       state_json ? 'pending_discussion_with_ao' as has_pending
FROM ao_project_state WHERE state_key = 'current';
-- Should return: true, true, true
```

---

## Files Modified
- `data/ao_pm/SCHEMA.md` — NEW (schema definition)
- `data/ao_pm/psychology.md` — NEW (psychology profile)
- `data/ao_pm/investment_channels.md` — NEW (two-channel architecture)
- `data/ao_pm/sensitive_issues.md` — NEW (minefields + dance instructions)
- `data/ao_pm/communication_rules.md` — NEW (Rule Zero, hunting cycle, framing)
- `data/ao_pm/agenda.md` — NEW (active + parked matters)
- `orchestrator/capability_runner.py` — modified (add `_load_ao_view_files()`, update `_build_system_prompt()`)
- `triggers/briefing_trigger.py` — modified (add `_gather_ao_pm_context()`, wire into briefing, expand Owner's Lens regex)
- `orchestrator/ao_signal_detector.py` — NEW (shared AO signal detection across all 3 channels)
- `triggers/waha_webhook.py` — modified (add AO WhatsApp signal detection + outbound tracking)
- `orchestrator/meeting_pipeline.py` — modified (add AO-relevant meeting detection)
- `triggers/email_trigger.py` — modified (add AO-orbit email detection)

## Do NOT Touch
- `orchestrator/agent.py` — tool implementations are fine as-is
- `orchestrator/context_selector.py` — ao_pm source weights already correct
- `orchestrator/capability_registry.py` — no changes needed
- `memory/store_back.py` — ao_project_state functions stay as-is
- `orchestrator/capability_router.py` — routing works, trigger patterns unchanged
- `capability_sets.system_prompt` (ao_pm soul) — keep as-is, soul defines WHO, files define WHAT
- `triggers/waha_client.py` — no changes, only waha_webhook.py modified

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('triggers/briefing_trigger.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('triggers/email_trigger.py', doraise=True)"`
4. All 6 view files exist in `data/ao_pm/` and are non-empty
5. AO PM invocation via dashboard loads view files (check logs for "VIEW FILE:" in prompt)
6. Daily briefing includes "AO INVESTOR RELATIONSHIP STATUS" section
7. AO signal detection doesn't crash any pipeline (test each channel with non-AO message first)
8. `python3 -c "import py_compile; py_compile.compile('orchestrator/ao_signal_detector.py', doraise=True)"`

## Verification SQL
```sql
-- Confirm view files are being read (check after first invocation)
SELECT last_run_at, run_count, last_answer_summary
FROM ao_project_state WHERE state_key = 'current' LIMIT 1;

-- Confirm briefing includes AO context (check briefing_queue after morning run)
SELECT * FROM briefing_queue ORDER BY created_at DESC LIMIT 5;

-- Confirm inbound email detection works
SELECT state_json->'relationship_state'->'last_inbound_signal'
FROM ao_project_state WHERE state_key = 'current' LIMIT 1;
```

## Deployment Order
1. Fix 1 (create view files) — deploy first, harmless
2. Fix 2 (capability runner loads files) — deploy second, view files now loaded alongside soul
3. Fix 3 (daily briefing) — deploy third, AO section in briefing
4. Fix 4 (signal detector) — deploy fourth: ao_signal_detector.py first, then wire into waha_webhook, meeting_pipeline, email_trigger
5. Fix 5 (clean SQL) — deploy LAST, only after confirming 1-4 work

Each fix is independently deployable. If any fails, the others still work.
Soul stays untouched throughout — it defines WHO AO PM is. Files define WHAT it knows. Both load into context.
