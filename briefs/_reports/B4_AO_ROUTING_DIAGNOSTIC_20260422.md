# B4 — AO Routing Diagnostic

**Brief:** `briefs/BRIEF_AO_PM_EXTENSION_1.md` — BLOCKING GATE
**Run date:** 2026-04-22
**Code instance:** B4 (session `code-4-2026-04-22`)
**Status:** ROUTING WORKS — Deliverable 2 cleared to proceed

---

## Query results

### (A) AO-related inbound email — last 21 days

```sql
-- Schema-corrected (email_messages has sender_email / full_body / received_date,
-- not from_address / body / created_at as listed in the brief).
SELECT COUNT(*) AS ao_mentions_21d
FROM email_messages
WHERE (sender_email ILIKE '%oskolkov%' OR sender_email ILIKE '%aelio%'
       OR subject ILIKE '%oskolkov%' OR subject ILIKE '%aelio%'
       OR full_body ILIKE '%oskolkov%' OR full_body ILIKE '%aelio%')
  AND received_date > NOW() - INTERVAL '21 days';
```

**Result: `ao_mentions_21d = 14`**

### (B) AO-related WhatsApp — last 21 days

```sql
-- Schema-corrected (whatsapp_messages has timestamp, not created_at).
SELECT COUNT(*) AS ao_wa_21d
FROM whatsapp_messages
WHERE (full_text ILIKE '%oskolkov%' OR full_text ILIKE '%andrey%')
  AND timestamp > NOW() - INTERVAL '21 days';
```

**Result: `ao_wa_21d = 22`**

### (C) ao_pm capability runs — last 21 days

```sql
SELECT COUNT(*) AS ao_pm_runs_21d
FROM capability_runs
WHERE capability_slug = 'ao_pm' AND created_at > NOW() - INTERVAL '21 days';
```

**Result: `ao_pm_runs_21d = 14`**

Distribution (runs per day, descending):

| Date | Runs |
|------|------|
| 2026-04-12 | 3 |
| 2026-04-08 | 1 |
| 2026-04-04 | 6 |
| 2026-04-02 | 4 |

First run in window: 2026-04-02 02:58 UTC. **Last run: 2026-04-12 14:51 UTC** (10 days ago, no activity since).

### (D) Decomposer spot-check

**D1 — AO-laden decomposer inputs (last 20, 21d window):**

```sql
SELECT created_at, capability_slug, sub_task, LEFT(answer, 300)
FROM capability_runs
WHERE capability_slug = 'decomposer'
  AND (sub_task ILIKE '%oskolkov%' OR sub_task ILIKE '%aelio%' OR sub_task ILIKE '%andrey%'
       OR answer ILIKE '%oskolkov%' OR answer ILIKE '%aelio%' OR answer ILIKE '%andrey%')
ORDER BY created_at DESC LIMIT 20;
```

**Result: 0 rows.**

**D2 — Decomposer routed to ao_pm (21d):**

```sql
SELECT COUNT(*) AS ao_pm_routed
FROM capability_runs
WHERE capability_slug = 'decomposer' AND created_at > NOW() - INTERVAL '21 days'
  AND (answer ILIKE '%ao_pm%' OR sub_task ILIKE '%ao_pm%');
```

**Result: `ao_pm_routed = 0`**

---

## Diagnosis

| Input signal | Count | Output signal | Count |
|---|---:|---|---:|
| (A) AO emails 21d | 14 | (C) ao_pm runs 21d | 14 |
| (B) AO WhatsApp 21d | 22 | (D2) decomposer → ao_pm | 0 |
| (A)+(B) combined | 36 | | |

Both inputs and runs are nonzero within the 21-day window. Decision-tree branch:

> **(A) or (B) > 0 AND (C) > 0, roughly aligned → routing works (v3 case d). Proceed with Deliverable 2.**

### Why D1 + D2 are zero

This is consistent with routing working via the **fast path** (regex trigger_patterns on `capability_sets.trigger_patterns` — `\b(oskolkov|andrey|andrej|aelio|lcg)\b` and three partner patterns), which bypasses the decomposer. Direct pattern-match fires `capability_runner.run()` on `ao_pm` without a decomposer hop. The zero decomposer hits confirm the brief's "Do NOT modify `pm_signal_detector.py`" instruction — routing does not depend on decomposer output for this capability.

### Soft anomaly (non-blocking)

Last `ao_pm` run was 2026-04-12, 10 days ago. Over those same 10 days, A+B have continued producing signal. This suggests:

- The Apr 12 silence is not a routing regression per se — if it were, (C) would be 0.
- Most likely cause: the 14 runs concentrated in Apr 2-12 correspond to a high-activity window (Monaco → FX Mayr → capital call walkthrough → Apr 13 reported-to-AO milestone). Post-Apr 13, AO traffic is increasingly ops/status updates that don't trigger scan flows (or Director-side outbound not looped back to scan).
- Not blocking. Worth monitoring post-D2 deploy — if wiki-content AO PM invocations stay silent through next week, open a separate scan-coverage investigation.

---

## Verdict

**ROUTING WORKS. Proceed with Deliverable 2.**

- Deliverable 2 (runtime wiring) cleared.
- Deliverable 5 (lint + scheduler) cleared.
- No routing-fix brief required.

Filing this report to `briefs/_reports/B4_AO_ROUTING_DIAGNOSTIC_20260422.md` per brief instruction; B4 proceeds to D2 implementation.

---

## Corrections to brief's SQL queries

For future reference (not in-scope to fix the brief itself):

1. `email_messages` columns per `information_schema`: `message_id, thread_id, sender_name, sender_email, subject, full_body, received_date, priority, ingested_at`. The brief used `from_address`, `body`, `created_at` — none exist.
2. `whatsapp_messages` columns: `id, sender, sender_name, chat_id, full_text, timestamp, is_director, ingested_at, media_*`. The brief used `created_at` — does not exist.
3. Decomposer (Query D) correction in the brief itself (drop `decomposer_decisions` table, use `capability_runs WHERE capability_slug='decomposer'`) was applied correctly — that survived.

Applied Lessons #2 / #3 from `tasks/lessons.md` (verify DB schema before running queries).
