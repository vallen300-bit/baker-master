---
brief_id: DEADLINE_SIGNAL_HYGIENE_1
brief_version: 1.0
author: AH1
target: b3
dispatched: 2026-05-13
trigger_class: TIER_B_CLASSIFIER_THRESHOLD_+_QUERY_HYGIENE
mandatory_2nd_pass: false
security_review_required: false
effort_estimate: ~3h
complexity: Medium
predecessor: DEADLINE_MATTER_SLUG_BACKFILL_1 (PR #200 merged 761b07d; Director-ratified 19/19 applied 2026-05-13T10:31Z)
followup: DEADLINE_FEEDBACK_LOOP_1 (NOT this brief — dashboard UI + feedback table, dispatched after this ships)
---

# BRIEF: DEADLINE_SIGNAL_HYGIENE_1 — classifier threshold + source-pattern noise blacklist + matter-closed query filter

## Context

Director 2026-05-13 ratifying the matter_slug Triaga: *"All dropped items should never be even surfaced. It is pure noise. Can we avoid them in the future? Also, the items that were done already (e.g. Cupial) — this is a closed item."*

Three concrete problems surfaced by the dry-run + Director's review:

1. **Classifier overmatches on weak signals.** The keyword scorer at `orchestrator/pipeline.py:87` accepts `score >= 1` — a single keyword hit. Result: "tax" in an American Express bill → `austrian-tax`; "Cap Ferrat" alias in a Touring Club Suisse promo → `cap-ferrat`. Director dropped 14 of 33 proposed matches as noise.
2. **Source-pattern noise has no pre-filter.** Subscription renewals, webcast registrations, marketing seminars, hardware delivery notifications, Bloomberg ads — these reach the classifier at all because no pre-classifier rule rejects the source signature (sender domain × subject keywords).
3. **Closed-matter rows leak into "active" surfaces.** Cupial settlement deadline (id 1486) was surfaced in the active scanner query even though the Cupial matter is operationally closed. The deadline row has `status='active'` but the matter is no longer worth tracking.

Two stray entries in production also need cleanup:
- `deadlines.matter_slug='Oskolkov-RG7'` (1 row) and `='Financing Vienna & Baden-Baden'` (1 row) — raw `matter_name` strings leaked through `slug_registry.normalize()` (returned the raw string instead of None when no canonical match). Probably from a recent write through a path where `slug_registry.normalize()` got a non-string or pre-normalize edge case.

This brief closes all four issues at the server side. The follow-up brief (DEADLINE_FEEDBACK_LOOP_1) adds the dashboard UI for Director-click "dismiss as noise" / "mark done" learning.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites
- `BAKER_VAULT_PATH` set (existing)
- Predecessor DEADLINE_MATTER_SLUG_BACKFILL_1 merged (✅ 761b07d)
- Director ratified 19/19 applied (✅ commit 918188f)

---

## Scope A — Raise classifier threshold + add source-pattern blacklist

### Problem
`orchestrator/pipeline.py:87` returns the matter for `best_score >= 1`. A single keyword match (often a weak signal like "tax" or short-alias hit) is enough. Result: ~42% false-positive rate on retroactive backfill (14/33 Director-dropped).

### Implementation

**A1.** `orchestrator/pipeline.py:87` — raise threshold to `best_score >= 3`.

```python
# Before
if best_score >= 1:  # Even a single person-name match is meaningful
    return best_match
return None

# After
# Threshold raised from 1 → 3 per DEADLINE_SIGNAL_HYGIENE_1: a single
# weak-signal keyword hit produces ~42% false-positive rate (Director
# dropped 14/33 in 2026-05-13 retroactive backfill). A score >= 3 means:
# matter name (3pts) OR keyword + person-partial (2+1) OR 2 keywords
# (2+2 cap'd at 3) — all genuine multi-signal matches.
if best_score >= 3:
    return best_match
return None
```

**A2.** New module `kbl/noise_patterns.py` — pre-classifier source-pattern blacklist.

```python
"""DEADLINE_SIGNAL_HYGIENE_1: pre-classifier noise filter.

Pattern-matches incoming deadline candidates against known-noise signatures
(subscription renewals, webcast/seminar registrations, marketing promos,
hardware delivery, generic billing). Returns True if the candidate is noise
and should be SKIPPED at insert time (no deadline row created).

This runs BEFORE _match_matter_slug() so noise never reaches the classifier.

Patterns are conservative: match only structural signals (verb + object pairs
that are categorical, not matter-specific). Examples that MUST pass through:
- "Cupial settlement chase" — concrete matter action
- "Sign Aukera term sheet by Friday" — deal action
Examples that MUST be filtered:
- "Slack subscription renewal" — SaaS billing
- "Register for AML analysis course" — training event
- "Delivery of [hardware product]" — domestic logistics
- "Subscribe to Bloomberg.com" — marketing
"""
import re
from typing import Optional

# Case-insensitive substring patterns. Each pattern is a structural noise
# signature, not a matter-related one. Anchored to verb+object pairs.
_NOISE_PATTERNS = [
    # SaaS / subscription billing
    r"\bsubscription\s+(renew(al)?|expir|offer|special)",
    r"\bsubscribe\s+to\s+\w+\.(com|io|net)",
    r"\b(special|exclusive)\s+(subscription\s+)?offer\s+(for|on)\b",
    # Marketing / promotional
    r"\b\d{1,2}\s*%\s+(discount|off)\s+(on|for)\b",
    r"\bspring\s+promot",
    # Training / webcast / seminar / course registration
    r"\b(register\s+for|attend|participate\s+in)\s+(the\s+)?[\w\s]+\s+(webcast|seminar|course|event|webinar)\b",
    r"\b'?[\w\s]+'?\s+(webcast|webinar|seminar)\b",
    # Generic billing
    r"\bmake\s+payment\s+to\s+(american\s+express|visa|mastercard|paypal)",
    r"\b(credit\s+card|invoice)\s+(payment|late\s+fee)",
    # Domestic logistics / personal delivery
    r"\bdelivery\s+of\s+\w+",
    r"\bmother's\s+day\s+gifts?",
    # Generic forecast/meeting noise
    r"\bdiscuss\s+\w+/ytd\s+and\s+forecast",
    # Newsletter chrome
    r"\bnews\s+to\s+(read|share)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _NOISE_PATTERNS]


def is_noise(description: str, source_snippet: Optional[str] = None) -> bool:
    """Return True if the candidate matches a known-noise signature.

    Conservative — only matches structural patterns (verb + categorical object).
    Concrete matter language (named counterparty, slug-able entity, deal action)
    is intentionally NOT pattern-matched here.
    """
    if not description:
        return False
    text = description
    if source_snippet:
        text = text + " " + source_snippet
    for pat in _COMPILED:
        if pat.search(text):
            return True
    return False
```

**A3.** Wire the noise filter into `models/deadlines.py:265` `insert_deadline()`.

Before the dedup check (line ~284), add:
```python
from kbl.noise_patterns import is_noise
if is_noise(description, source_snippet):
    logger.info(
        "deadline rejected as noise (pre-classifier): id=skip src_type=%s desc=%s",
        source_type, (description or "")[:80],
    )
    return None  # No insert. Caller treats as deduped-skip.
```

**A4.** Same wiring in `models/cortex.cortex_create_deadline()` at line ~485 (before the `insert_deadline` call).

**A5.** Same wiring in `triggers/clickup_trigger.py:548` direct-INSERT path (before the cursor.execute).

### Tests (Scope A)
`tests/test_deadline_noise_filter.py` (new) — ≥6 tests:
1. `is_noise("Slack subscription renewal")` → True
2. `is_noise("Cupial settlement chase")` → False
3. `is_noise("Register for AML analysis course")` → True
4. `is_noise("Sign Aukera term sheet by Friday")` → False
5. `is_noise("")` and `is_noise(None)` → False (defensive)
6. `insert_deadline(description="Slack subscription renewal", ...)` returns None (no DB row) when noise filter is active
7. (Optional 7th) `_match_matter_slug` returns None for `best_score == 2` (threshold proof — currently 2 would pass but >=3 won't)

---

## Scope B — Matter-closed filter on active-deadline queries

### Problem
`triggers/vault_scanner.py:218` and `:645` query `WHERE status = 'active'` only. If the underlying matter is closed (e.g., Cupial settled), the deadline row still surfaces. Same leak likely in cockpit + DM queries.

### Implementation

**B1.** Identify all "active-deadline" surface queries. From recon, the known list:
- `triggers/vault_scanner.py:218-228` (per-desk DM query)
- `triggers/vault_scanner.py:645-655` (broader scan)
- Any cockpit/dashboard query with `FROM deadlines WHERE status = 'active'`

Run `grep -rn "FROM deadlines" outputs/dashboard.py triggers/ orchestrator/ scripts/` to enumerate all.

For EACH active-surface query that pulls deadlines for "current attention" (DM, cockpit cards, scanner): add a matter-closed filter.

**B2.** Add the filter as a left-join + exclusion:
```sql
SELECT d.id, d.description, ...
FROM deadlines d
LEFT JOIN matter_registry m ON m.matter_name = d.matter_slug OR LOWER(m.matter_name) = d.matter_slug
WHERE d.status = 'active'
  AND (d.matter_slug IS NULL OR m.status IS NULL OR m.status = 'active')
  -- (rest of query unchanged)
```

The triple-OR is important:
- `d.matter_slug IS NULL` → keep untagged deadlines (they may be real, just not classified)
- `m.status IS NULL` → keep deadlines whose matter_slug isn't in matter_registry yet (don't lose them)
- `m.status = 'active'` → keep deadlines on currently-active matters
- → exclude `m.status IN ('closed', 'paused', 'inactive')` rows

**Important:** `matter_registry.matter_name` is the registry's column; deadlines store canonical slug. Join condition needs lower-case comparison since `matter_name` is "Cupial" while `matter_slug` is "cupial". Verify via `psql` against prod first; the actual JOIN may need `ON LOWER(m.matter_name) = LOWER(d.matter_slug)` or a slug-aliased column. Use the brief's recon step in Step 1 below to confirm.

**B3.** Idempotent — these are read-side filter changes, no DDL. Each modified query gets a test that asserts: a row with matter_slug pointing at a closed matter is excluded.

### Tests (Scope B)
`tests/test_deadline_matter_closed_filter.py` (new) — ≥3 tests against the actual queries:
1. Setup: insert a deadline with `matter_slug='cupial'`, set `matter_registry.matter_name='Cupial'` to `status='closed'`. Run scanner query. Assert id NOT in result.
2. Same setup, but matter status='active' → assert id IS in result.
3. Setup: deadline with NULL matter_slug → assert id IS in result (we don't drop unclassified).

---

## Scope C — One-shot cleanup of 2 stray raw matter_name rows

### Problem
Post-apply verification surfaced 2 rows where `deadlines.matter_slug` contains a raw `matter_name` string (not a canonical slug):
- `matter_slug='Oskolkov-RG7'` (1 row)
- `matter_slug='Financing Vienna & Baden-Baden'` (1 row)

Both came from a write path where `slug_registry.normalize()` returned a non-canonical value. The exact write path is TBD — but for this brief we just clean up the data; the write-path bug fix can be a follow-up if recurrence is observed.

### Implementation

**C1.** Add a tiny one-shot to the backfill script as a new `--cleanup-strays` flag (or a separate `scripts/cleanup_stray_matter_slugs.py` if you prefer a dedicated script — your call).

The cleanup logic:
```python
# Find rows where matter_slug is set but NOT in the canonical slug set.
from kbl import slug_registry
canonical = slug_registry.canonical_slugs()

cur.execute("""
    SELECT id, matter_slug FROM deadlines
    WHERE matter_slug IS NOT NULL
      AND matter_slug != ''
    LIMIT 500;
""")
stray_ids = []
for rid, slug in cur.fetchall():
    if slug not in canonical:
        # Try normalize once; if it resolves, fix; else NULL it.
        normalized = slug_registry.normalize(slug)
        if normalized and normalized in canonical:
            stray_ids.append((rid, normalized))
        else:
            stray_ids.append((rid, None))

# Dry-run prints the list. Apply (with same SAVEPOINT pattern) updates them.
```

Same dry-run-default + 3-safety-rails pattern as the main backfill script.

### Tests (Scope C)
Either fold into the existing `tests/test_backfill_matter_slug.py` (add 1-2 tests for stray cleanup) or new file. Your judgment.

---

## Files Modified
- `orchestrator/pipeline.py` — single-line threshold change (1 → 3)
- `kbl/noise_patterns.py` — NEW module (~60 LOC of patterns + `is_noise()`)
- `models/deadlines.py` — wire `is_noise()` into `insert_deadline()`
- `models/cortex.py` — wire `is_noise()` into `cortex_create_deadline()`
- `triggers/clickup_trigger.py` — wire `is_noise()` into the direct-INSERT path
- `triggers/vault_scanner.py` — add matter-closed filter to scanner queries (both ~218 + ~645)
- `outputs/dashboard.py` — add matter-closed filter to any active-deadline query (enumerate first; tests gate the change)
- `scripts/backfill_matter_slug.py` (or new `scripts/cleanup_stray_matter_slugs.py`) — `--cleanup-strays` mode for Scope C
- `tests/test_deadline_noise_filter.py` — NEW (≥6 tests)
- `tests/test_deadline_matter_closed_filter.py` — NEW (≥3 tests)
- `tests/test_backfill_matter_slug.py` — possibly extended for Scope C (1-2 tests)

## Do NOT Touch
- `_match_matter_slug()` body (lines 27-92) except the threshold line — DO NOT rewrite scoring logic; that's a different scope (LLM upgrade, future brief)
- `orchestrator/deadline_manager.py` recurring respawn — already correctly inherits parent
- `outputs/dashboard.py` commitment migration block (~line 5301) — already explicit
- Already-wired ingest triggers (`email_trigger.py`, `fireflies_trigger.py`, `dropbox_trigger.py`, `calendar_trigger.py`) — they route through `insert_deadline()` so they pick up A3 wiring automatically
- DDL — no schema changes
- `baker-vault/slugs.yml` — separate-repo PR only

## Key Constraints

1. **Noise patterns conservative.** Each pattern must match STRUCTURAL noise (verb + categorical object), never matter-specific language. Director's manual review of the patterns is welcome; on a false-positive (a real deadline gets filtered), open an issue + add the description to a `_ALLOWLIST` exception array. Better to under-filter than over-filter on day 1.
2. **Threshold change is the high-blast-radius edit.** Going from `>=1` to `>=3` will reduce auto-classification rate on the existing classifier. If pre-fix the classifier produces a slug 50% of the time, post-fix it might be 25%. That's INTENDED — Director already said the cheap classifier is too noisy. The follow-up brief (DEADLINE_FEEDBACK_LOOP_1) supplies the smarter learning loop.
3. **Matter-closed JOIN condition needs prod recon.** Check via psql against prod that `matter_registry.matter_name = d.matter_slug` is the right join — the names may not match cases (matter_name='Cupial', matter_slug='cupial'). Use `LOWER()` on both sides or alias-table lookup if registry has it.
4. **Conn.rollback() in every except** — PostgreSQL pool hygiene.
5. **LIMIT on every SELECT** — 500 default is safe.
6. **Singleton hook compliance** — `SentinelStoreBack._get_global_instance()` only (no bare instantiation).
7. **Idempotency for Scope C** — `WHERE matter_slug IS NOT NULL AND matter_slug NOT IN (canonical_set)` so re-runs are safe.

## Verification

### Ship gate
Literal `pytest tests/test_deadline_noise_filter.py tests/test_deadline_matter_closed_filter.py tests/test_backfill_matter_slug.py -v` output paste in ship report. No "by inspection".

### Quality checkpoints
1. `pytest` green (paste full output)
2. `bash scripts/check_singletons.sh` PASS
3. Pattern-list review: paste the final `_NOISE_PATTERNS` list in the ship report for Director eyeball
4. Threshold change diff visible in `orchestrator/pipeline.py`
5. Enumeration of all "FROM deadlines WHERE status = 'active'" queries pasted in ship report — shows which got the matter-closed filter and which didn't (and why)
6. Scope C dry-run executed + proposal preserved at `briefs/_reports/B3_stray_matter_slug_cleanup_<ts>.md` (1-2 expected stray rows)

### Verification SQL (post-merge, run by AH1)
```sql
-- Confirm threshold raise: classifier-output rate on next 100 insert attempts
-- (run after deploy, sample-mode)
SELECT count(*) FILTER (WHERE matter_slug IS NOT NULL) AS tagged,
       count(*) FILTER (WHERE matter_slug IS NULL) AS untagged
FROM deadlines
WHERE created_at >= NOW() - INTERVAL '24 hours'
LIMIT 1;
-- Expected: ratio shifts down vs predecessor baseline (precision↑ at recall cost)

-- Confirm matter-closed filter works for Cupial example
-- (after Director marks Cupial registry entry inactive, if desired)
SELECT d.id, d.description, m.status AS matter_status
FROM deadlines d
LEFT JOIN matter_registry m ON LOWER(m.matter_name) = d.matter_slug
WHERE d.status = 'active' AND d.matter_slug = 'cupial'
LIMIT 5;
-- Expected: 0 rows if Cupial matter is closed
```

### Director ratification gate (Scope C only)
**Do NOT execute `--cleanup-strays --apply`.** AH1 will:
1. Read your dry-run proposal file
2. Surface the 1-2 stray rows + proposed action (fix or NULL) to Director
3. On ratification, AH1 executes `--apply` from fresh `git pull --rebase origin main` checkout
4. On clean apply, this brief is fully closed

---

## Step 1 — Recon (REQUIRED before code changes)
Before touching code, run from `~/bm-b3`:
```bash
grep -rn "FROM deadlines" outputs/dashboard.py triggers/ orchestrator/ scripts/ | grep -v "test_\|backfill"
```
List ALL active-deadline queries. For each: decide if it's a "current attention" surface (needs matter-closed filter) or a different scope (e.g., audit/history queries — leave alone). Paste the list in the ship report under "Scope B query inventory".

Verify the matter_registry JOIN condition (run `psql` to inspect 1-2 matter_registry rows for shape) — confirm whether to use `LOWER()` or alias lookup. Note your choice in the ship report.

## Bus posting
Bus-post to `lead` on PR open. Topic `ship/DEADLINE_SIGNAL_HYGIENE_1`. Include: PR #, test counts, pattern list, query inventory, Scope C dry-run buckets.

## Mailbox hygiene
On merge, AH1 transitions `briefs/_tasks/CODE_3_PENDING.md` → `status: COMPLETE`. b3 does not touch the mailbox file post-ship.

## Lesson application from predecessors
- ✅ Singleton hook compliance
- ✅ Dry-run-default + Director-gated `--apply` for Scope C
- ✅ Per-row SAVEPOINT pattern for Scope C apply
- ✅ No DDL (no schema changes)
- ✅ `/security-review` NOT required (no auth, no external endpoint, no PII)
- ✅ mandatory_2nd_pass FALSE
- ✅ Conservative noise patterns (start tight, expand via observed false-positives)
- ✅ Director-facing surface for any decision (Scope C apply ratification)
