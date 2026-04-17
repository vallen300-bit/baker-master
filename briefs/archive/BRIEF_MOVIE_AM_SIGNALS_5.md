# BRIEF: MOVIE-AM-SIGNALS-5 — Generic PM Signal Detection + MOVIE AM Activation

## Context
MOVIE AM Steps 1-3 deployed (PM Factory, registration, HMA extraction). Step 4 (debrief) in progress.
Step 5: wire signal detection so Baker catches MOVIE-relevant emails, WhatsApp messages, and meetings in real time.

Currently, `ao_signal_detector.py` is hardcoded for AO PM only. Following the PM Factory pattern (Step 1),
we generalize signal detection so it's PM_REGISTRY-driven — config only for new PMs.

## Estimated time: ~2h
## Complexity: Medium
## Prerequisites: PM Factory (Step 1) deployed, MOVIE AM registered (Step 2)

### Cowork Refinements Applied (cowork_84615fdc7cfe)
| # | Refinement | Where Applied |
|---|-----------|---------------|
| Q1 | Add `rg7\|riemergasse` to MOVIE AM keywords (building shared by both PMs) | Feature 1, movie_am signal_keyword_patterns |
| Q3 | Outbound detection: orbit patterns only (not keywords) — avoids false positives | Feature 2 new `detect_relevant_pms_outbound()`, Feature 3c |
| Q4 | Meeting detection: BOTH orbit AND keyword required (short titles = low context) | Feature 2 `detect_relevant_pms_meeting()` |
| Q5 | No new signal_extractions table — use pm_state_history filtered by mutation_source | No change needed (already correct) |

---

## Feature 1: Add Signal Config to PM_REGISTRY

### Problem
Signal detection patterns (orbit people, keywords) are hardcoded in `ao_signal_detector.py`.
No way to add MOVIE signals without creating a new file.

### Current State
`orchestrator/capability_runner.py` lines 45-115: PM_REGISTRY has `contact_keywords` and
`briefing_email_patterns` but no signal detection patterns.

### Implementation

**File:** `orchestrator/capability_runner.py`

Add two new fields to each PM_REGISTRY entry: `signal_orbit_patterns` and `signal_keyword_patterns`.

**In the `ao_pm` entry (after `soul_md_keywords`, before `extraction_view_files`):**

```python
        "signal_orbit_patterns": [
            r"buchwalder|gantey",
            r"pohanis|constantinos",
            r"ofenheimer|alric",
            r"@aelio\.",
            r"aukera",
        ],
        "signal_keyword_patterns": [
            r"capital.call",
            r"rg7|riemergasse",
            r"aelio|lcg",
            r"oskolkov|andrey",
            r"participation.agreement",
            r"shareholder.loan",
        ],
        "signal_whatsapp_senders": [
            r"oskolkov|andrey\s*o",
        ],
```

**In the `movie_am` entry (after `soul_md_keywords`, before `extraction_view_files`):**

```python
        "signal_orbit_patterns": [
            r"mario\s*habicher",
            r"francesco|cefalu",
            r"robin\s*chalier",
            r"rolf\s*h[uü]bner",
            r"balazs|czepregi",
            r"@mohg\.",
            r"@mandarinoriental\.",
        ],
        "signal_keyword_patterns": [
            r"mandarin\s*oriental",
            r"\bmovie\b",
            r"rg7|riemergasse",
            r"\boccupancy\b.*\b(hotel|vienna)\b",
            r"\brevpar\b",
            r"\bgop\b.*\b(hotel|report|monthly)\b",
            r"\bff&?e\b",
            r"operating\s*budget",
            r"owner.?s?\s*approval",
            r"recovery\s*lab",
            r"warranty|gew[äa]hrleistung",
        ],
        "signal_whatsapp_senders": [
            r"rolf",
            r"henri\s*movie",
            r"victor\s*rodriguez",
        ],
```

### Key Constraints
- Patterns are Python regex (compiled at import time for performance)
- Keep patterns specific enough to avoid false positives (e.g., `\bmovie\b` not just `movie`)
- `@mandarin` already in AO orbit patterns — remove from AO, add to MOVIE only

### Verification
```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"
python3 -c "
from orchestrator.capability_runner import PM_REGISTRY
for slug, cfg in PM_REGISTRY.items():
    assert 'signal_orbit_patterns' in cfg, f'{slug} missing signal_orbit_patterns'
    assert 'signal_keyword_patterns' in cfg, f'{slug} missing signal_keyword_patterns'
    assert 'signal_whatsapp_senders' in cfg, f'{slug} missing signal_whatsapp_senders'
    print(f'{slug}: {len(cfg[\"signal_orbit_patterns\"])} orbit, {len(cfg[\"signal_keyword_patterns\"])} kw, {len(cfg[\"signal_whatsapp_senders\"])} wa')
"
```

---

## Feature 2: Create Generic PM Signal Detector

### Problem
`orchestrator/ao_signal_detector.py` (85 lines) has hardcoded AO patterns and calls
`store.update_ao_project_state()`. Cannot detect MOVIE signals.

### Implementation

**Create:** `orchestrator/pm_signal_detector.py`

```python
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


def detect_relevant_pms_text(sender: str, text: str) -> list[str]:
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


def detect_relevant_pms_whatsapp(sender_name: str, text: str) -> list[str]:
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


def detect_relevant_pms_meeting(title: str, participants: str) -> list[str]:
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


def detect_relevant_pms_outbound(text: str) -> list[str]:
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


def flag_pm_signal(pm_slug: str, channel: str, source: str, summary: str, timestamp=None):
    """Update pm_project_state with an inbound signal. Non-fatal."""
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
    except Exception as e:
        logger.warning(f"PM signal flag failed [{pm_slug}]: {e}")
```

### Key Constraints
- All functions are **non-fatal** (try/except in flag, empty list return in detect)
- Patterns compiled lazily and cached — no import-time DB calls
- `detect_relevant_pms_*` returns a **list** — one message can match multiple PMs
- Uses `re.IGNORECASE` flag (not inline `(?i)` — Lesson from MEMORY.md)

### Verification
```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/pm_signal_detector.py', doraise=True)"
python3 -c "
from orchestrator.pm_signal_detector import detect_relevant_pms_text, detect_relevant_pms_whatsapp
# Test MOVIE detection
assert 'movie_am' in detect_relevant_pms_text('mario.habicher@mohg.com', 'Monthly P&L report')
assert 'movie_am' in detect_relevant_pms_text('unknown@test.com', 'Mandarin Oriental Vienna occupancy report')
assert 'movie_am' in detect_relevant_pms_whatsapp('Rolf', 'Hotel update')
# Test AO detection
assert 'ao_pm' in detect_relevant_pms_text('buchwalder@test.com', 'Meeting update')
assert 'ao_pm' in detect_relevant_pms_text('unknown@test.com', 'capital call notice for RG7')
# Test no false positives
assert detect_relevant_pms_text('random@gmail.com', 'Hello world') == []
print('All signal detection tests passed')
"
```

---

## Feature 3: Update Trigger Wiring

### Problem
`email_trigger.py` (line 845) and `waha_webhook.py` (lines 845, 957) import directly from
`ao_signal_detector`. Must iterate over all PMs via the generic detector.

### Implementation

#### 3a. Email Trigger

**File:** `triggers/email_trigger.py`

**Replace lines 843-850** (the AO-specific block):

```python
        # PM-SIGNAL: Detect PM-relevant emails (generic, PM_REGISTRY-driven)
        try:
            from orchestrator.pm_signal_detector import detect_relevant_pms_text, flag_pm_signal
            _pm_sender = metadata.get("primary_sender", "") + " " + metadata.get("primary_sender_email", "")
            _pm_text = f"{metadata.get('subject', '')} {thread['text'][:500]}"
            for _pm_slug in detect_relevant_pms_text(_pm_sender, _pm_text):
                flag_pm_signal(_pm_slug, "email", metadata.get("primary_sender", "unknown"), metadata.get("subject", "")[:200])
        except Exception:
            pass  # Non-fatal
```

#### 3b. WhatsApp Webhook — Inbound

**File:** `triggers/waha_webhook.py`

**Replace lines 842-849** (the AO-specific inbound block):

```python
    # PM-SIGNAL: Detect PM-relevant WhatsApp signals (generic, PM_REGISTRY-driven)
    if sender != DIRECTOR_WHATSAPP:
        try:
            from orchestrator.pm_signal_detector import detect_relevant_pms_whatsapp, flag_pm_signal
            for _pm_slug in detect_relevant_pms_whatsapp(sender_name, combined_body):
                flag_pm_signal(_pm_slug, "whatsapp", sender_name or sender, combined_body[:200])
        except Exception:
            pass  # Non-fatal
```

#### 3c. WhatsApp Webhook — Outbound (ORBIT ONLY — Cowork refinement Q3)

**Replace lines 954-960** (the AO-specific outbound block):

```python
    # PM-SIGNAL: Detect PM-relevant outbound WhatsApp (Director messaging PM contacts)
    # Outbound uses ORBIT ONLY (not keywords) to avoid false positives —
    # e.g., Director texting "hotel" to anyone shouldn't wake MOVIE AM.
    # If Director messages Francesco/Mario/Rolf → MOVIE signal. Cowork Q3.
    if sender == DIRECTOR_WHATSAPP and combined_body:
        try:
            from orchestrator.pm_signal_detector import detect_relevant_pms_outbound, flag_pm_signal
            for _pm_slug in detect_relevant_pms_outbound(combined_body):
                flag_pm_signal(_pm_slug, "whatsapp_outbound", "Director outbound", combined_body[:200])
        except Exception:
            pass
```

### Key Constraints
- All blocks remain `try/except pass` — signal detection must NEVER break email/WA processing
- Use lazy imports (inside the try block) — no import-time side effects
- **Outbound uses orbit patterns only** (not keywords) — avoids false positives when Director mentions generic terms like "hotel" or "budget" in unrelated conversations (Cowork refinement Q3)

### Verification
```bash
python3 -c "import py_compile; py_compile.compile('triggers/email_trigger.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"
```

---

## Feature 4: Backward Compatibility Wrapper

### Problem
Other code may import from `ao_signal_detector`. Must not break.

### Implementation

**File:** `orchestrator/ao_signal_detector.py`

Replace the entire file with a thin wrapper:

```python
"""
AO Signal Detector — DEPRECATED wrapper.
All signal detection now handled by pm_signal_detector.py (PM_REGISTRY-driven).
This file kept for backward compatibility only.
"""
from orchestrator.pm_signal_detector import (
    detect_relevant_pms_text,
    detect_relevant_pms_whatsapp,
    flag_pm_signal,
)


def is_ao_relevant_text(sender: str, text: str) -> bool:
    """DEPRECATED: Use pm_signal_detector.detect_relevant_pms_text()."""
    return "ao_pm" in detect_relevant_pms_text(sender, text)


def is_ao_relevant_meeting(title: str, participants: str) -> bool:
    """DEPRECATED: Use pm_signal_detector.detect_relevant_pms_meeting()."""
    from orchestrator.pm_signal_detector import detect_relevant_pms_meeting
    return "ao_pm" in detect_relevant_pms_meeting(title, participants)


def is_ao_whatsapp_message(sender_name: str, text: str) -> bool:
    """DEPRECATED: Use pm_signal_detector.detect_relevant_pms_whatsapp()."""
    return "ao_pm" in detect_relevant_pms_whatsapp(sender_name, text)


def flag_ao_signal(channel: str, source: str, summary: str, timestamp=None):
    """DEPRECATED: Use pm_signal_detector.flag_pm_signal('ao_pm', ...)."""
    flag_pm_signal("ao_pm", channel, source, summary, timestamp)
```

### Key Constraints
- All 4 original functions preserved with identical signatures
- Any code importing `from orchestrator.ao_signal_detector import ...` continues to work
- Meeting pipeline or other callers are unaffected

### Verification
```bash
python3 -c "import py_compile; py_compile.compile('orchestrator/ao_signal_detector.py', doraise=True)"
python3 -c "
from orchestrator.ao_signal_detector import is_ao_relevant_text, flag_ao_signal
assert is_ao_relevant_text('buchwalder@test.com', 'hello')
assert not is_ao_relevant_text('random@gmail.com', 'hello world')
print('Backward compat OK')
"
```

---

## Feature 5: Remove `@mandarin` from AO Orbit

### Problem
The original `ao_signal_detector.py` had `r'@mandarin'` in `_AO_ORBIT_PATTERNS`.
This pattern belongs to MOVIE AM, not AO PM. Having it in AO creates false positives.

### Implementation
Do NOT include `@mandarin` in AO's `signal_orbit_patterns` (Feature 1 already handles this correctly — `@mandarin` patterns are only in MOVIE AM's config).

### Verification
```python
python3 -c "
from orchestrator.pm_signal_detector import detect_relevant_pms_text
hits = detect_relevant_pms_text('info@mandarinoriental.com', 'Budget review')
assert 'movie_am' in hits
assert 'ao_pm' not in hits
print('Mandarin routes to MOVIE only: OK')
"
```

---

## Files Modified
- `orchestrator/capability_runner.py` — add signal_orbit_patterns, signal_keyword_patterns, signal_whatsapp_senders to both PM_REGISTRY entries
- `orchestrator/pm_signal_detector.py` — **NEW** — generic PM signal detector (config-driven)
- `orchestrator/ao_signal_detector.py` — replaced with backward-compat wrapper
- `triggers/email_trigger.py` — lines 843-850: generic PM signal detection
- `triggers/waha_webhook.py` — lines 842-849, 954-960: generic PM signal detection

## Do NOT Touch
- `memory/store_back.py` — already has generic `update_pm_project_state()`, no changes needed
- `triggers/briefing_trigger.py` — already has generic PM briefing loop, no changes needed
- `data/movie_am/*.md` — view files updated separately in Step 4 debrief
- `orchestrator/agent.py` — tool handlers already generic from PM Factory

## Quality Checkpoints
1. AO PM regression: `is_ao_relevant_text('buchwalder@test.com', 'meeting')` returns True
2. MOVIE signal: `detect_relevant_pms_text('mario.habicher@mohg.com', 'P&L report')` returns `['movie_am']`
3. No false positives: random email returns `[]`
4. Backward compat: `from orchestrator.ao_signal_detector import flag_ao_signal` works
5. Email trigger processes emails without error (check Render logs)
6. WhatsApp webhook processes messages without error (check Render logs)
7. Signal flags appear in `pm_project_state` for both `ao_pm` and `movie_am`
8. `@mandarin` emails route to MOVIE AM only, not AO PM

## Verification SQL
```sql
-- Check MOVIE AM signals are being captured
SELECT pm_slug, version, state_json->'relationship_state'->>'last_inbound_channel' as channel,
       state_json->'relationship_state'->>'last_inbound_from' as source,
       updated_at
FROM pm_project_state
WHERE pm_slug = 'movie_am' LIMIT 1;

-- Check AO PM still working
SELECT pm_slug, version, state_json->'relationship_state'->>'last_inbound_channel' as channel,
       updated_at
FROM pm_project_state
WHERE pm_slug = 'ao_pm' LIMIT 1;

-- Check signal history
SELECT pm_slug, mutation_source, mutation_summary, created_at
FROM pm_state_history
WHERE pm_slug IN ('ao_pm', 'movie_am')
ORDER BY created_at DESC LIMIT 10;
```
