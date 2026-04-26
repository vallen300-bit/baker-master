# CODE_1_PENDING — B1: DEADLINE_EXTRACTOR_QUALITY_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer)
**Working dir:** `~/bm-b1`
**Branch:** `deadline-extractor-quality-1` (create from main)
**Brief:** `briefs/BRIEF_DEADLINE_EXTRACTOR_QUALITY_1.md`
**Status:** OPEN
**Trigger class:** LOW (no auth/DB-migration/secrets/external API/financial/cross-capability writes) → AI Head solo merge

---

## §2 pre-dispatch busy-check

- **Mailbox prior:** `COMPLETE — VIP_BACKFILL_1 ... 2026-04-26 by B1`. Idle ✓
- **Branch state:** main; `git checkout main && git pull` first.
- **Other B-codes:** B2 → WIKI_LINT_1 in flight (no overlap). B3 → about to take BRANCH_HYGIENE_1 (no overlap). B5 → CHANDA rewrite (no overlap).
- **Lesson #47 redundancy check:** `triggers/email_trigger.py` + `orchestrator/deadline_manager.py` extractor work — no shipped equivalent; spec confirms gap (~60% noise on email-extracted deadlines).

**Dispatch authorisation:** Director default-fallback 2026-04-26 ("Your 3 question — you default. I skip") + Cat 6 close "C" ratification.

## Brief route (charter §6A)

`/write-brief` 6 steps applied. Brief at `briefs/BRIEF_DEADLINE_EXTRACTOR_QUALITY_1.md`. Director Q1/Q2/Q3 defaulted to RA recommendations (see brief §4). All 12 Code Brief Standards items ticked in brief §5.

## Action

Read brief end-to-end. Implement L1+L2 filter + whitelist override + audit log table + Triaga HTML for Director-review of L1 harvest list before deploy.

Pre-build harvest of sender domains from 25 dismissed Cat 6 items (brief §10 lists deadline IDs):
```sql
SELECT DISTINCT sender_email FROM email_messages em
  JOIN deadlines d ON d.source_id = em.message_id  -- or equivalent join key
  WHERE d.id IN (1424, 1469, 1465, 1467, 1475, 1397, 1477, 1447, 1476, 1442, 1454, 1455, 1478, 1481, 1427, 1464, 1420, 1482, 1483, 1473, 1479, 1429, 1449, 1468, 1396)
  ORDER BY sender_email;
```
(verify exact join key in schema before running). Output to Triaga HTML `_01_INBOX_FROM_CLAUDE/2026-04-26-l1-harvest-review.html` for Director tick-approval before deploy.

## Ship gate (literal output required)

```
pytest tests/test_deadline_extractor_quality.py -v
# ≥6 cases (L1 blocked / allowed / whitelist-override; L2 high/mid/low-score)
pytest tests/ 2>&1 | tail -3
bash scripts/check_singletons.sh
git diff --name-only main...HEAD
git diff --stat
```

**No "by inspection"** (per `feedback_no_ship_by_inspection.md`).

## Ship-report shape

- **Path:** `briefs/_reports/B1_deadline_extractor_quality_1_20260426.md`
- **Contents:** all literal outputs above + Triaga HTML link + L1 harvest list count + L2 keyword list + acceptance test result on 50 most-recent suppressions.
- **PR title:** `DEADLINE_EXTRACTOR_QUALITY_1: L1+L2 deadline extractor filter + audit log`
- **Branch:** `deadline-extractor-quality-1`

## Mailbox hygiene (§3)

After PR merged, overwrite this file:
```
COMPLETE — DEADLINE_EXTRACTOR_QUALITY_1 merged as <commit-sha> on 2026-04-26 by AI Head B. §3 hygiene per b-code-dispatch-coordination.
```

## Timebox

**~3–4h.** Includes harvest + classifier + tests + audit-log table + Triaga HTML.

## Out of scope (explicit)

- NO Slack/WhatsApp deadline extractors (separate briefs)
- NO sender reputation system (V2)
- NO promotional content classification beyond deadlines
- NO LLM-based L2 classifier (deterministic V1 per Q2 default)

---

**Dispatch timestamp:** 2026-04-26 ~07:00 UTC.
**Authority chain:** Director default-fallback → RA-19 spec → AI Head B brief promotion + dispatch → B1 execution.
