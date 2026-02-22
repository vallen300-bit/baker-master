# BRIEF 7 — Gmail Live Polling + Tier Mapping Fix

**Date:** 2026-02-20
**Layer:** Sentinel (triggers) + Baker (pipeline)
**Priority:** HIGH — Evok EWS phase-out Oct 2026, migration window is ticking
**Predecessor:** Brief 6 (Integration Test) — 29/31 PASS

---

## OBJECTIVE

Bring Baker's Gmail email trigger live: authenticate against Dimitry's real Gmail
(`vallen300@gmail.com`, which also receives `dvallen@brisengroup.com` via redirect),
backfill historical email context into Qdrant, validate the full pipeline chain with
a real email, and fix the tier mapping defect discovered during Brief 6.

**End state:** Scheduler starts → polls Gmail every 5 min → new substantive emails
fire the pipeline → Baker classifies, retrieves context, generates analysis → alerts
land in PostgreSQL + Slack → email vectors stored in Qdrant for future retrieval.

---

## PHASE 0 — Tier Mapping Fix (Pre-requisite)

**Problem:** During Brief 6, Claude returned `tier_raw=1` (integer) but the pipeline
mapping code expected strings like `"urgent"`. The integration test applied a workaround
("accepts both"). This must be a proper fix, not a workaround.

**Facts:**
- The system prompt at `prompt_builder.py:60` already says `"tier": 1|2|3` (integers)
- The pipeline at `pipeline.py:203` and `pipeline.py:222` maps strings → integers:
  `{"urgent": 1, "important": 2, "info": 3}.get(alert.get("tier", "info"), 3)`
- If Claude returns `1` (int), `.get(1, 3)` returns `3` (default) — **silent downgrade**

**Fix required (3 steps):**

### 0a. Fix pipeline.py tier handling
Replace BOTH tier mapping blocks (lines ~203 and ~222) with:

```python
def _normalize_tier(raw_tier) -> int:
    """Normalize alert tier to integer 1/2/3. Defaults to 3 if invalid."""
    if isinstance(raw_tier, int) and raw_tier in (1, 2, 3):
        return raw_tier
    # Fallback: string mapping (defensive, prompt says integers)
    str_map = {"urgent": 1, "important": 2, "info": 3}
    if isinstance(raw_tier, str):
        mapped = str_map.get(raw_tier.lower())
        if mapped:
            logger.warning(f"Tier received as string '{raw_tier}', expected integer. Mapped to {mapped}.")
            return mapped
    logger.warning(f"Invalid tier value: {raw_tier!r}. Defaulting to 3.")
    return 3
```

Place this as a module-level helper in `pipeline.py`. Then replace both `.get()` calls:

```python
# Line ~203:
tier = _normalize_tier(alert.get("tier"))

# Line ~222:
alert_tier = _normalize_tier(alert.get("tier"))
```

### 0b. Verify prompt already enforces integers
Read `prompt_builder.py` line 60. It should say `"tier": 1|2|3`. If it says anything
else (e.g., `"tier": "urgent"|"important"|"info"`), change it to integers.

### 0c. Add unit test
Create `tests/test_tier_normalization.py`:

```python
"""Unit tests for tier normalization."""
import pytest
from orchestrator.pipeline import _normalize_tier

def test_integer_tiers():
    assert _normalize_tier(1) == 1
    assert _normalize_tier(2) == 2
    assert _normalize_tier(3) == 3

def test_string_tiers_fallback():
    assert _normalize_tier("urgent") == 1
    assert _normalize_tier("important") == 2
    assert _normalize_tier("info") == 3
    assert _normalize_tier("Urgent") == 1  # case insensitive

def test_invalid_tiers_default_to_3():
    assert _normalize_tier(0) == 3
    assert _normalize_tier(4) == 3
    assert _normalize_tier("banana") == 3
    assert _normalize_tier(None) == 3
    assert _normalize_tier("") == 3
```

### Phase 0 success criteria
- [ ] `_normalize_tier(1)` returns `1` (not `3`)
- [ ] `_normalize_tier("urgent")` returns `1` with a warning log
- [ ] All 9 unit tests pass
- [ ] No more string-to-int mapping as primary path

---

## PHASE 1 — Gmail OAuth2 Setup

Baker needs to authenticate to the Gmail API using OAuth2 (not the Cowork MCP connector —
Baker runs as its own service).

### 1a. Check Google Cloud project
Verify project exists at console.cloud.google.com with Gmail API enabled.
If `config/gmail_credentials.json` already exists, skip to 1c.

### 1b. Create OAuth2 client (if needed)
- Project: `Baker-Gmail` (or existing)
- API: Gmail API (readonly)
- Client type: Desktop application
- Download JSON → save as `config/gmail_credentials.json`

**IMPORTANT:** This step requires human action (Dimitry). If credentials file doesn't
exist, output clear instructions and STOP. Don't proceed without real credentials.

### 1c. First OAuth2 consent flow
```bash
cd 01_build
python scripts/extract_gmail.py --mode poll --dry-run
```
This will open a browser for OAuth consent (if no `gmail_token.json` yet).
After consent, the token is saved to `config/gmail_token.json`.

**IMPORTANT:** This also requires human action (browser consent). If running headless
(Claude Code), output instructions for Dimitry to run this manually.

### Phase 1 success criteria
- [ ] `config/gmail_credentials.json` exists
- [ ] `config/gmail_token.json` exists and contains valid refresh token
- [ ] `python scripts/extract_gmail.py --mode poll` connects without error

---

## PHASE 2 — Historical Backfill

Before live polling works well, Baker needs email context in Qdrant. Otherwise, when
a new email arrives, retrieval finds nothing.

### Email Filtering Rules (apply to BOTH backfill and live polling)

**Exclude:**
- Emails with `List-Unsubscribe` header or `Precedence: bulk` header
- `noreply@` senders (any domain)
- Known newsletter senders (already in `config/settings.py` → `GmailConfig.noise_senders`)
- Automated notifications: ClickUp, Slack, calendar invites (`*.ics` attachments), system alerts
- Marketing/transactional from: Google, Apple, Microsoft, Amazon, banking alerts

**Include:**
- Emails from/to real human contacts
- Prioritize VIP contacts from onboarding briefing (Christophe Buchwalder, Andrey Oskolkov, etc.)
- Business correspondence with identifiable senders

**Implementation:** Extend `noise_senders` patterns in `config/settings.py` and ensure `extract_gmail.py`
checks `List-Unsubscribe` and `Precedence` headers in addition to sender patterns. Both historical
and poll modes must use the same filter pipeline.

### 2a. Dry-run historical extraction
```bash
cd 01_build
python scripts/extract_gmail.py --mode historical --since 2025-08-20 --dry-run
```
Report: thread count, sample subjects, estimated token count.

### 2b. Full extraction
```bash
python scripts/extract_gmail.py --mode historical --since 2025-08-20
```
Output: `03_data/gmail/gmail_threads.json`

### 2c. Ingest to Qdrant
```bash
python scripts/bulk_ingest.py \
    --source "../03_data/gmail/gmail_threads.json" \
    --collection baker-conversations
```
Report: vectors created, collection point count before/after.

### 2d. Verify retrieval
Test that email context is now retrievable:
```python
from memory.retriever import SentinelRetriever
r = SentinelRetriever()
results = r.search("email from Christophe Buchwalder about AO agreement")
print(f"Found {len(results)} results")
for res in results[:3]:
    print(f"  - {res.get('metadata', {}).get('subject', 'no subject')}")
```

### Phase 2 success criteria
- [ ] Historical extraction completes without error
- [ ] `gmail_threads.json` contains > 50 substantive threads
- [ ] Qdrant `baker-conversations` collection has new email vectors
- [ ] Semantic search for known contacts returns relevant email threads

---

## PHASE 3 — Live Polling Smoke Test

### 3a. Single poll run
```bash
cd 01_build
python triggers/scheduler.py --run-once email
```
This runs `check_new_emails()` once. Expected behavior:
1. Polls Gmail for threads since yesterday
2. Classifies each by priority
3. Runs pipeline for high/medium
4. Queues low-priority for daily briefing
5. Logs results

### 3b. Verify pipeline execution
After 3a, check:
- PostgreSQL `trigger_log` has new email entries
- PostgreSQL `alerts` table has new rows (if any email was high/medium)
- Qdrant has new vectors from store-back
- Poll state file updated: `config/gmail_poll_state.json`

```sql
-- Check trigger log
SELECT type, source_id, processed, received_at
FROM trigger_log
WHERE type = 'email'
ORDER BY received_at DESC
LIMIT 5;

-- Check alerts
SELECT tier, title, status, created_at
FROM alerts
ORDER BY created_at DESC
LIMIT 5;
```

### 3c. Verify tier mapping (regression test)
Confirm any alerts created use integer tiers (not defaulted to 3):
```sql
SELECT tier, title FROM alerts
WHERE created_at > NOW() - INTERVAL '10 minutes'
ORDER BY tier;
```
If an email was genuinely urgent, tier should be 1, not 3.

### Phase 3 success criteria
- [ ] `--run-once email` completes without error
- [ ] trigger_log has email entries with `processed = true`
- [ ] Poll state file updated with new high-water mark
- [ ] If alerts created, tiers are correct integers (not all defaulted to 3)

---

## PHASE 4 — Slack Output Verification

### 4a. Run with Slack enabled
If Phase 3 produced T1/T2 alerts, they should have been posted to Slack.
If not, create a test condition:

```bash
# Forward a test email to vallen300@gmail.com with subject containing
# "URGENT: [test] Baker pipeline validation" and wait 30 seconds,
# then re-run:
python triggers/scheduler.py --run-once email
```

### 4b. Manual Slack check
Check Slack #cockpit channel (C0AF4FVN3FB) for the alert post.
Verify: tier badge color, contact name, action required flag.

### Phase 4 success criteria
- [ ] T1/T2 email alerts appear in Slack #cockpit
- [ ] Alert format matches Slack Block Kit template (tier badge, title, body)

---

## PHASE 5 — Scheduler Continuous Run

### 5a. Start scheduler
```bash
cd 01_build
python triggers/scheduler.py
```
Verify all 4 jobs registered:
- `email_poll` (every 300s)
- `whatsapp_poll` (every 600s)
- `fireflies_scan` (every 7200s)
- `daily_briefing` (06:00 UTC)

### 5b. Wait for first automatic poll
Let the scheduler run for 6 minutes. Verify:
- email_poll fires at least once
- No crashes, no auth errors
- Log shows "Email trigger: X new threads found" or "no new threads"

### 5c. Graceful shutdown
Ctrl+C → verify "Scheduler stopped" message, no orphan processes.

### Phase 5 success criteria
- [ ] Scheduler starts with all 4 jobs
- [ ] First automatic email poll completes
- [ ] Graceful shutdown works

---

## SUMMARY

| Phase | What | Checks |
|-------|------|--------|
| 0 | Tier mapping fix | 4 |
| 1 | Gmail OAuth2 setup | 3 |
| 2 | Historical backfill | 4 |
| 3 | Live polling smoke test | 4 |
| 4 | Slack output verification | 2 |
| 5 | Scheduler continuous run | 3 |
| **Total** | | **20** |

**Success:** 20/20 PASS, 0 FAIL. SKIPs allowed for Phases 1/4 if credentials
or Slack webhook not configured.

---

## HUMAN GATES

Phase 1 (OAuth2) and Phase 4 (Slack) may require human action:

1. **Gmail credentials:** If `config/gmail_credentials.json` doesn't exist, Claude Code
   must STOP and output setup instructions. Dimitry creates the OAuth client in Google
   Cloud Console and provides the credentials file.

2. **First OAuth consent:** If `config/gmail_token.json` doesn't exist, the first run
   opens a browser for consent. This can't run headless. Dimitry runs the consent flow
   manually, then Claude Code continues.

3. **Slack verification:** Manual check of #cockpit channel after T1/T2 alert.

---

## CLEANUP

Phase 0 tier fix is permanent (no cleanup needed).
If test emails were sent to trigger pipeline, they will be in Gmail permanently but
will only process once (dedup by thread_id in trigger_log).

### M365 Migration Cutover Note

Once the Evok → M365 migration completes (~2-3 weeks from now), the
`dvallen@brisengroup.com` → `vallen300@gmail.com` redirect stops automatically.
At that point:
1. **Kill Gmail polling** — disable the `email_poll` job in scheduler
2. **Activate Microsoft Graph API connector** — replace Gmail trigger with Graph-based trigger
3. **No overlap period** — clean switch, no dedup needed between Gmail and Graph
4. This is a future brief (Brief 8+), not part of this scope

---

## FILES TOUCHED

| File | Change |
|------|--------|
| `orchestrator/pipeline.py` | Add `_normalize_tier()`, replace 2 mapping blocks |
| `tests/test_tier_normalization.py` | NEW — 9 unit tests |
| `config/settings.py` | Extend `noise_senders` + add header-based noise filters |
| `scripts/extract_gmail.py` | Add `List-Unsubscribe` / `Precedence` header checks |
| `config/gmail_credentials.json` | Human-provided (OAuth client) |
| `config/gmail_token.json` | Auto-generated (OAuth consent) |
| `config/gmail_poll_state.json` | Auto-updated (watermark) |
| `03_data/gmail/gmail_threads.json` | Generated (historical backfill) |

---

## DEPENDENCIES

- Phase 0 has no dependencies (can run immediately)
- Phases 1-5 depend on Phase 0
- Phase 1 depends on human action (OAuth credentials)
- Phase 2 depends on Phase 1
- Phases 3-5 depend on Phase 2
- Phase 4 depends on Slack webhook being configured
