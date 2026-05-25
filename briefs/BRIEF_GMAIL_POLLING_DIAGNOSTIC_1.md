---
brief_id: GMAIL_POLLING_DIAGNOSTIC_1
authored_by: aihead1
dispatched_by: aihead1
target: b4
created: 2026-05-25
type: READ-ONLY DIAGNOSTIC (no code edits — diagnose + propose only)
anchor: deputy bus #1006 (gmail-polling-outage-separate-defect) + #1000 (counter-finding)
director_authorization: 2026-05-25 ~09:30Z chat "go" — dispatch diagnostic to b4
---

# BRIEF: GMAIL_POLLING_DIAGNOSTIC_1 — diagnose silent 9-day Gmail polling outage

## Context

`documents` table where `source_path LIKE 'email:%'` has zero entries since 2026-05-16 (9 days stale). Meanwhile:

- `apscheduler` job `email_poll` runs every 5 min and completes successfully — verified in Render logs every 5 min: "Running job Gmail polling" then "Job email_poll completed successfully" then "Watermark updated for email_poll" then "Watermark updated for email_poll_checked".
- Watermark `email_poll` shows recent timestamp (e.g. 2026-05-25T07:38:28Z observed at 09:24Z) — same value across consecutive fires.
- Non-email pipeline is healthy: 901 docs ingested last 12h (WhatsApp, transcripts, Substack).
- `baker_actions` last 12h: zero gmail/email/poll/ingest action types.
- On-demand `baker_gmail_attachment_read` works (E2E PASS earlier today against multiple Gmail messages including 2026-05-15-dated Bank of Cyprus PDF in message id 19e2c1b1e2bdd4c0).

The break is somewhere between "poll fetches from Gmail API" and "documents row gets written for the email" — NOT in the scheduler (running fine) and NOT in Gmail OAuth (read paths work). Hag-desk Tuesday LG Wien filing is NOT blocked because on-demand attachment read is live; this is fixing silent ongoing rot in agent-DB reasoning over recent counterparty mail.

### Surface contract: N/A — diagnostic-only. No tool surface, no UI, no schema change.

## Estimated time: ~1-2h
## Complexity: Low (read-only investigation)
## Prerequisites: None — pure investigation against production DB + recent Render logs.

## Scope: READ-ONLY DIAGNOSTIC

**HARD RULE: b4 does NOT modify any code in this brief.** This is investigation + a written diagnosis report. The fix lands in a SEPARATE brief (`GMAIL_POLLING_FIX_1`) authored by AH1 once root cause is named. If b4 sees a one-line fix and is tempted to apply it directly: STOP. Write the diagnosis first; AH1 dispatches the fix.

Reason for the split: the polling code intersects with multiple systems (signal_queue ingestion, dedup, label filters, noise-sender list, attachment extraction, document indexing, cost circuit breaker). A naive fix in one spot can mask the actual defect in another. AH1 will scope the fix brief after seeing b4's diagnosis.

## Investigation steps

### 1. Confirm the disconnect

Run these queries against production PG (use `psql "$DATABASE_URL"` from b4 shell — env should be present from prior B-code work; if not, surface as blocker):

```sql
-- 1a. Latest doc per source (confirm email-source is stale)
SELECT
  split_part(source_path, ':', 1) AS source_type,
  MAX(ingested_at) AS latest,
  COUNT(*) FILTER (WHERE ingested_at > NOW() - INTERVAL '12 hours') AS last_12h,
  COUNT(*) FILTER (WHERE ingested_at > NOW() - INTERVAL '24 hours') AS last_24h
FROM documents
GROUP BY 1
ORDER BY 2 DESC NULLS LAST
LIMIT 20;

-- 1b. Latest entry in email_messages (the table the poll writes to BEFORE documents)
SELECT MAX(received_at) AS latest_received, MAX(ingested_at) AS latest_ingested, COUNT(*) AS total
FROM email_messages
WHERE received_at > NOW() - INTERVAL '14 days'
LIMIT 1;

-- 1c. Recent email_messages by received_at — does the table get new rows at all?
SELECT message_id, sender, subject, received_at, ingested_at
FROM email_messages
ORDER BY received_at DESC
LIMIT 20;

-- 1d. Are there email_messages rows that DIDN'T make it to documents?
SELECT em.message_id, em.subject, em.received_at, em.ingested_at,
       EXISTS (SELECT 1 FROM documents d WHERE d.source_path LIKE 'email:' || em.message_id || '%') AS has_doc
FROM email_messages em
WHERE em.received_at > NOW() - INTERVAL '14 days'
ORDER BY em.received_at DESC
LIMIT 50;
```

Report findings explicitly:
- Is `email_messages` getting new rows? (If yes → poll writes to email_messages, indexing-to-documents is broken. If no → poll itself isn't writing.)
- For rows in `email_messages` last 14 days: how many have a corresponding `documents` row vs not?
- What's the most-recent `email_messages.ingested_at`?

### 2. Read the poll code path

Files (READ ONLY — do not edit):
- `triggers/embedded_scheduler.py:89-95` — registers `email_poll` → `check_new_emails`
- `triggers/email_trigger.py:611` — `def check_new_emails()` — top-level poll entry
- `triggers/email_trigger.py:214` — `def _get_gmail_service()` — OAuth singleton
- `triggers/email_trigger.py:259` — `def _poll_baker_labeled_emails(service)` — label-based deep-analysis flow (separate from main poll)
- `scripts/extract_gmail.py:931` — `def extract_poll(service)` — actual Gmail API call + extraction
- `scripts/extract_gmail.py:880-930` — `load_poll_state` / `save_poll_state` — watermark persistence
- `scripts/extract_gmail.py:618-710` — `extract_attachments_text` + helpers — attachment pipeline
- Wherever `documents` table gets the `source_path = 'email:...'` INSERT — find this. Likely `triggers/email_trigger.py` or a downstream helper called from `check_new_emails`. `grep -rn "source_path.*email:" --include="*.py"` is a fast probe.

Trace the chain: `check_new_emails()` → `extract_poll(service)` → loop body → email_messages INSERT → documents INSERT. Map each step. Note where the chain becomes conditional (filters, dedup checks, label checks, noise-sender exclusions, size limits).

### 3. Exercise the polling code manually

From b4's local shell with Baker Gmail OAuth env vars present (`BAKER_GMAIL_CLIENT_ID`, `BAKER_GMAIL_CLIENT_SECRET`, `BAKER_GMAIL_REFRESH_TOKEN` + `DATABASE_URL`):

```bash
cd ~/bm-b4
# Verify env is sourced
env | grep -E "BAKER_GMAIL|DATABASE_URL" | sed 's/=.*/=<set>/'

# Exercise check_new_emails() in isolation with verbose logging
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(name)s | %(levelname)s | %(message)s')
from triggers.email_trigger import check_new_emails
check_new_emails()
"
```

Report:
- Stdout/stderr from the run (truncate to ≤500 lines if long).
- Did the function return without error?
- Did it print/log any "skipping", "filtered", "noise sender", "deduped", "label rejected" messages?
- After the run, re-query `email_messages` — did a new row land? Did `documents` get a new row?

### 4. Inspect Gmail-side state

Use the just-shipped MCP tool against the live Render deployment (deputy already confirmed it works):

```bash
# Search Gmail for any inbound mail in the last 24 hours
curl -sS -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_gmail_attachment_read","arguments":{"message_id":"<msg_id_picked_from_a_recent_real_inbound_email_found_via_director_or_via_local_gmail_account>","filename":"any.pdf"}}}'
```

Or via Director's `claude_ai_Gmail` integration — ask Director to search-and-paste 3-5 recent inbound message_ids you can then sanity-check against. If b4 cannot get message_ids on their own, surface this as a BLOCKER and request lead-side help.

The point: is Gmail itself receiving mail in the period 2026-05-16 → now? Verify externally before assuming the bug is in baker's poll.

### 5. Check git log around 2026-05-15 to 2026-05-16

```bash
cd ~/bm-b4
git log --since="2026-05-14" --until="2026-05-17" --oneline -- \
  triggers/email_trigger.py \
  scripts/extract_gmail.py \
  triggers/embedded_scheduler.py \
  outputs/dashboard.py
```

For any commits in the window that touch the poll path: read the diff and note whether the change could plausibly silence the poll. Pay attention to:
- New filter rules (label exclusions, noise-sender additions).
- Watermark logic changes (off-by-one, timezone bugs).
- Dedup logic changes (false-positive dedups would silently skip everything).
- Schema migrations against `email_messages` or `documents` that landed without backfill.
- Cost circuit breaker tweaks (cost monitor at €113 right now — extraction skipped on every email per logs from earlier today: `WARNING | Extraction skipped (circuit breaker at EUR 113.26)`). **This is a strong candidate** — verify whether the circuit breaker prevents the `documents` INSERT or only the LLM extraction step.

### 6. Render-side log scrape

```bash
# AH1 will share the Render API key + service ID if b4 doesn't have them.
# Pull last 24h of logs and grep for the poll path
RENDER_KEY=$(op read "op://Baker API Keys/API Render/credential")
SVC="srv-d6dgsbctgctc73f55730"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
WIN=$(date -u -v-24H +"%Y-%m-%dT%H:%M:%SZ")
curl -s -H "Authorization: Bearer $RENDER_KEY" \
  "https://api.render.com/v1/logs?ownerId=tea-cqs1lc6juvgs73d6h8e0&resource=$SVC&startTime=$WIN&endTime=$NOW&direction=backward&limit=500&text=email_poll" \
  > /tmp/email_poll_logs.json
# Count + tail
python3 -c "
import json
d = json.load(open('/tmp/email_poll_logs.json'))
logs = d.get('logs',[])
print(f'total email_poll log lines last 24h: {len(logs)}')
for log in logs[-20:]:
    print(f\"  {log.get('timestamp','')[:23]} {log.get('message','')[:200]}\")
"
```

Look for: watermark progression (does the `email_poll` watermark advance over the 24h window or is it stuck?), any WARNING/ERROR lines, any "skipped" / "filtered" / "no new" log lines.

### 7. Look for upstream `return` early-exit patterns

The known anti-pattern (`tasks/lessons.md` line ~? — "Sequential pollers blocked by upstream failure"): one poller hitting 429 / auth failure / unhandled exception triggers an early `return` in a shared function, killing downstream pollers. Apply this lens: does `check_new_emails()` call other pollers (Bluewin, Exchange) BEFORE the Gmail fetch? If yes, and one of those is failing silently, the Gmail branch may never execute.

## Diagnosis report format

Write the diagnosis to `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md`. Required sections:

1. **Bottom line** (1-2 sentences): what's the root cause?
2. **Evidence chain** — which queries, log lines, code paths confirm the diagnosis. Cite by file:line.
3. **What's broken vs what's working** — explicit table.
4. **Recommended fix** — narrow and specific, with: file path, line range, proposed change (≤20 lines of code if applicable), reasoning. If multiple possible fixes, rank them.
5. **Risks of the proposed fix** — what could it break, what tests would need to pass.
6. **Whether AH1 should author a fix brief or fold into a `STATE_FILE_REFRESH_2`-style rolling cleanup.**

## Hard constraints

- **DO NOT modify any production code.** This is investigation. Fix goes in a separate brief authored by AH1 after seeing the diagnosis.
- **DO NOT paste OAuth tokens, refresh tokens, API keys, or credential file contents into the report.** If b4 finds credentials in logs or code paths, redact and reference by env var name.
- **DO NOT run `extract_poll(service)` with `--apply` flags that would write to production tables in unintended ways.** If b4 wants to write, use a feature branch + dry-run mode + AH1 ratification.
- **DO NOT touch `tasks/lessons.md`** — append-only audit trail; AH1 captures the lesson post-fix.

## Acceptance criteria

- **AC1:** Report file exists at `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md` with all 6 required sections.
- **AC2:** All 7 investigation steps documented with concrete findings (or explicit "step skipped because X").
- **AC3:** Bottom-line root cause is named with confidence ranking (high/medium/low) — if confidence is low, list the top 3 hypotheses.
- **AC4:** Recommended fix is specific enough that AH1 can dispatch a fix brief in <30 min without re-investigation.
- **AC5:** Bus-post to `lead` with topic `diag/gmail-polling-outage-1` on report completion. Include: report path, bottom-line in ≤2 sentences, confidence rank, est fix time.

## Reporting (bus reply-to-sender)

```bash
BAKER_ROLE=b4 ~/bm-b4/scripts/bus_post.sh lead \
  "diag/gmail-polling-outage-1 — report at briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md. Root cause: <X> (confidence <high/medium/low>). Top recommended fix: <Y>. Est fix effort: ~<Z>h. Full evidence + code path map in report." \
  diag/gmail-polling-outage-1
```

## References

- Deputy bus #1006 (gmail-polling-outage-separate-defect) — counter-finding that originally surfaced the gap
- Deputy bus #1000 (initial hypothesis that scheduler-singleton subsumed this — superseded by #1006)
- Lead bus #1004 (scheduler /health misdiagnosis correction)
- `tasks/lessons.md` — sequential-pollers + circuit-breaker patterns relevant
- Cost monitor circuit breaker active: €113.26 > €100 hard stop (potential causal factor; verify)
- Gmail-attachment-read PR #257 (squash 89008e0a) — proven OAuth singleton works on read paths; isolates the bug to the poll/write side

## Heartbeat cadence

Minimum every 12h while actively investigating. Given ~1-2h scope, no heartbeat expected unless b4 hits a credential or DB-access blocker.
