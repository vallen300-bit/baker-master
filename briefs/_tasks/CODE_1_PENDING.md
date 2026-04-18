# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** LAYER0-LOADER-1 shipped as PR #4 at `fa0cfe8`. In B2 review.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## AI Head quick confirms

- **`BAKER_VAULT_PATH` is canonical.** Brief typo. No rename needed. Noted in B2's review dispatch.

---

## Task: LOOP-SCHEMA-1 — Create Learning Loop Infrastructure Tables

**Why now:** B3's CHANDA audit surfaced **Step 1 prompt violates Inv 3** (`hot.md` + `feedback_ledger` not loaded). B2's Step 0 review surfaced **S5 undefined `kbl_layer0_hash_seen` storage** + **S6 undefined `kbl_layer0_review` queue**. All three tables are loop-critical (Legs 2+3 of CHANDA §2) and currently absent from schema. Until they exist, neither the Step 1 Inv-3 fix nor the Layer 0 S5/S6 fixes are implementable. You unblock three downstream tickets with one schema migration PR.

### Scope

**IN**
- New migration file: `migrations/20260418_loop_infrastructure.sql` (or next-in-sequence number)
- Three tables:

```sql
-- feedback_ledger (CHANDA §2 Leg 2 Capture)
CREATE TABLE IF NOT EXISTS feedback_ledger (
  id             BIGSERIAL PRIMARY KEY,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  action_type    TEXT NOT NULL,       -- 'promote' | 'correct' | 'ignore' | 'ayoniso_respond' | 'ayoniso_dismiss'
  target_matter  TEXT,                -- slug from slug_registry, nullable for cross-matter actions
  target_path    TEXT,                -- vault path of affected wiki entry, nullable for non-vault actions
  signal_id      BIGINT,              -- FK to signal_queue.id, nullable
  payload        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- action-specific detail
  director_note  TEXT                 -- free-text rationale, optional
);
CREATE INDEX IF NOT EXISTS idx_feedback_ledger_created_at ON feedback_ledger(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_ledger_matter ON feedback_ledger(target_matter);

-- kbl_layer0_hash_seen (S5 from B2 Step 0 review — 72h dedupe)
CREATE TABLE IF NOT EXISTS kbl_layer0_hash_seen (
  content_hash     TEXT PRIMARY KEY,           -- sha256 of normalized content
  first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  ttl_expires_at   TIMESTAMPTZ NOT NULL,
  source_signal_id BIGINT,                     -- FK to signal_queue.id (first instance)
  source_kind      TEXT NOT NULL               -- 'email' | 'whatsapp' | 'meeting_transcript' | 'scan_query'
);
CREATE INDEX IF NOT EXISTS idx_kbl_layer0_hash_ttl ON kbl_layer0_hash_seen(ttl_expires_at);

-- kbl_layer0_review (S6 from B2 Step 0 review — 1-in-50 drop sampling queue)
CREATE TABLE IF NOT EXISTS kbl_layer0_review (
  id              BIGSERIAL PRIMARY KEY,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  signal_id       BIGINT NOT NULL,             -- FK to signal_queue.id
  dropped_by_rule TEXT NOT NULL,               -- rule name that triggered drop
  signal_excerpt  TEXT NOT NULL,               -- first 500 chars of payload for quick Director scan
  source_kind     TEXT NOT NULL,
  reviewed_at     TIMESTAMPTZ,                 -- NULL = pending, set when Director clicks through
  review_verdict  TEXT                         -- 'correct_drop' | 'false_positive' | 'ambiguous', NULL if unreviewed
);
CREATE INDEX IF NOT EXISTS idx_kbl_layer0_review_pending ON kbl_layer0_review(created_at) WHERE reviewed_at IS NULL;
```

- No business logic changes, no loader, no writer — schema only
- Rollback section in migration file (DROP TABLE IF EXISTS × 3) for disaster recovery
- `tests/test_migrations.py` entry that runs the migration up + rollback against a test DB to confirm syntax

**OUT**
- Writer code (Step 1 reader, ledger writer, Layer 0 hash writer) — those land in KBL-B impl + KBL-C
- Data seeding (empty tables are correct initial state)
- Any change to `signal_queue` or `kbl_cost_ledger` (existing tables untouched)

### CHANDA pre-push self-check

- **Q1 Loop Test:** This migration CREATES the storage layer Legs 2+3 depend on. It does not modify existing reading/writing behavior; it enables future compliance. Proceeds without Director stop — the creation of loop infrastructure IS the remedy for detected non-compliance, not a new loop modification. Reference CHANDA §2 Leg 2 (ledger must exist atomically-writable) and Leg 3 (Step 1 must read ledger).
- **Q2 Wish Test:** Pure wish-service. No convenience shortcut.
- **Inv 2 note:** This migration makes Inv 2 (atomic ledger write on every Director action) *possible*. Actual atomicity is enforced by KBL-C write path + the strict-read policy we ratified during CHANDA adoption.

### Branch + PR

- Branch: `loop-schema-1`
- Base: `main` (latest)
- PR title: `LOOP-SCHEMA-1: feedback_ledger + kbl_layer0_hash_seen + kbl_layer0_review`
- PR body: cite CHANDA §2 Leg 2/3 + B2 S5/S6 findings + B3 CHANDA audit Flag 1

### Reviewer

B2 (reviewer-separation).

### Timeline

~45-60 min. You've done N migrations before; this is N+1.

### Dispatch back

> B1 LOOP-SCHEMA-1 shipped — PR #5 open, branch `loop-schema-1`, head `<SHA>`, tests green. 3 new tables. Ready for B2 review.

### Work-in-flight note

PR #4 (LAYER0-LOADER-1) stays in B2 review. No action needed from you on PR #4 unless B2 returns fixes.

---

*Posted 2026-04-18 by AI Head. PR #4 in B2 queue. This is parallel production-moving work.*
