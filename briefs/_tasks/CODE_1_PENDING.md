# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #14 merged at `58ed935e`. B1 flagged Inv 9 cross-link ambiguity before starting Step 6. Director ratified option **C** — dedicated `kbl_cross_link_queue` table.
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — STEP6-FINALIZE-IMPL with cross-link flow C ratified

---

## Task: STEP6-FINALIZE-IMPL — Deterministic Silver document finalization (Option C cross-link flow)

**Specs (all ratified):**
- `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` @ `ffa2a26` — B3's full spec (5 Pydantic models, 21 validation rules, 12-class error matrix)
- `briefs/_drafts/KBL_B_STEP6_OQ_RESOLUTIONS_20260419.md` @ `bf1ae53` — AI Head ratifications of all 8 OQs
- **Cross-link flow: Option C** (this dispatch) — dedicated `kbl_cross_link_queue` table, UPSERT idempotency, Step 7 consumes + realizes to vault

### Cross-link flow — Option C specification

**Why C:** Director ratified after B1's flagged ambiguity. Trade-off summary:
- Inv 9 honored: Render writes zero vault files; Mac Mini (Step 7) is sole agent writer.
- Idempotency via native PG UPSERT on composite PK, not application-level JSONB mutation.
- Queryable for future CEO Cockpit dashboards + digest narrative enrichment ("cross-matter patterns this week" queries become one SQL statement).
- Step 7 batch-commits cross-links in a single git commit cleanly.

**New table migration — `migrations/20260419_step6_kbl_cross_link_queue.sql`:**

```sql
CREATE TABLE IF NOT EXISTS kbl_cross_link_queue (
    source_signal_id BIGINT NOT NULL REFERENCES signal_queue(id) ON DELETE CASCADE,
    target_slug TEXT NOT NULL,
    stub_row TEXT NOT NULL,            -- the Markdown stub row Step 7 appends verbatim
    vedana TEXT,                       -- threat / opportunity / routine (nullable if Silver has no vedana)
    source_path TEXT NOT NULL,         -- target_vault_path of the source signal
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    realized_at TIMESTAMPTZ,           -- set by Step 7 when committed to vault
    PRIMARY KEY (source_signal_id, target_slug)
);

CREATE INDEX IF NOT EXISTS idx_kbl_cross_link_queue_unrealized
    ON kbl_cross_link_queue (created_at)
    WHERE realized_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_kbl_cross_link_queue_target_slug
    ON kbl_cross_link_queue (target_slug, created_at DESC);
```

**Scope adjustments to B3's spec §4 (atomic_write):**

- **IGNORE** §4.3 `tempfile.NamedTemporaryFile + os.rename` filesystem logic — that's Step 7's job (Mac Mini), not Step 6.
- Step 6 does a single PG UPSERT per related_matter per signal:

  ```sql
  INSERT INTO kbl_cross_link_queue
    (source_signal_id, target_slug, stub_row, vedana, source_path)
  VALUES (%s, %s, %s, %s, %s)
  ON CONFLICT (source_signal_id, target_slug) DO UPDATE SET
    stub_row = EXCLUDED.stub_row,
    vedana = EXCLUDED.vedana,
    source_path = EXCLUDED.source_path,
    created_at = NOW(),
    realized_at = NULL;  -- unrealize on re-emission (rare)
  ```

- B3's `CrossLinkStub` Pydantic model STAYS — it structures the `stub_row` field before insertion. You build the Markdown stub string in Python, then store it as `stub_row TEXT`.
- `stub_row` format per B3 spec §4: `<!-- stub:signal_id=<id> --> - YYYY-MM-DD | source_path | vedana-prefix | 1-line excerpt`. Keep the exact format.
- Idempotency is now free — composite PK + UPSERT. Re-running Step 6 on the same signal is safe and produces the same state.

### Scope (full) — implement per `KBL_B_STEP6_FINALIZE_SPEC.md` WITH Option C cross-link flow

**IN**

1. **Migration** — `migrations/20260419_step6_kbl_cross_link_queue.sql` (table above).
2. **Migration** — `migrations/20260419_step6_signal_queue_final_markdown.sql` (if `final_markdown` + `target_vault_path` columns don't already exist — verify before adding):

   ```sql
   ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS final_markdown TEXT;
   ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS target_vault_path TEXT;
   ```

3. **`kbl/schemas/silver.py`** — all 5 Pydantic models per B3 spec §2 + OQ resolutions:
   - `MatterSlug` constrained str, `MoneyMention`, `SilverFrontmatter` (per OQ1-OQ7), `SilverDocument`, `CrossLinkStub`.
   - All OQ-resolved field shapes per `KBL_B_STEP6_OQ_RESOLUTIONS_20260419.md`.

4. **`kbl/steps/step6_finalize.py`** — the finalizer:
   - `finalize(signal_id, conn) -> None` — load opus_draft_markdown → parse YAML frontmatter + body → validate via `SilverDocument` → build `target_vault_path` (B3 spec §3.6) → write `final_markdown` + `target_vault_path` on signal_queue → UPSERT one row per `related_matter` into `kbl_cross_link_queue` → advance state.
   - State transitions: `awaiting_finalize` → `finalize_running` → `awaiting_commit` (success) OR `opus_failed` (validation fail → Opus R3 retry per B3 §5) OR `finalize_failed` (after 3 Opus retries fail).
   - Error matrix per B3 spec §5 — 12 classes, each → state + retry policy.
   - Money parser `_parse_money_string(raw: str) -> MoneyMention | None` per OQ4.
   - `FinalizationError(KblError)` net-additive in `kbl/exceptions.py`.

5. **`target_vault_path` builder** — per B3 spec §3.6. Format `wiki/<primary_matter>/<yyyy-mm-dd>_<slug_of_title>.md`. Slug-of-title: lowercase, dash-separated, max 60 chars. Collision handling: append `_<source_id_short>` if path exists.

6. **Cross-link UPSERT writer** — per Option C spec above. No filesystem IO.

7. **Logging** per B3 spec §6 — Pydantic failures WARN, cross-link IO failures don't apply (no IO in Step 6 anymore; Step 7 owns those errors).

8. **`pipeline_tick.py` wire-up** — extend `_process_signal` to call `finalize()` after Step 5's successful return. State progression now `awaiting_opus` → Step 5 → `awaiting_finalize` → Step 6 → `awaiting_commit`. Stop at `awaiting_commit` (Step 7 not yet shipped). Extend `tests/test_pipeline_tick.py` with Step 6 happy + fail paths.

9. **Tests** — `tests/test_step6_finalize.py` + `tests/test_silver_schema.py`:
   - Pydantic schema coverage: valid document parses; each R1-R21 validation rule triggers expected failure.
   - `target_vault_path` builder: canonical paths, collision handling, slug-of-title edge cases.
   - **Cross-link UPSERT:** first call INSERTs; second identical call UPDATEs same row (asserts `COUNT(*) == 1` on composite PK). `realized_at` set to NULL on UPDATE.
   - Money parser: `[3000 GBP]`, `[1200000 EUR, 600000 EUR]`, malformed → None.
   - Error matrix: each of 12 failure classes → correct state + retry policy.
   - **CHANDA Inv 1** test: zero-Gold Silver finalizes without crash.
   - **CHANDA Inv 4** test: Pydantic REJECTS any Opus draft with `author: director` or `voice: gold` — structural enforcement.
   - **CHANDA Inv 8** test: all emitted Silver is `author: pipeline` + `voice: silver`.
   - **CHANDA Inv 9** test: `finalize()` performs ZERO filesystem writes (mock `open`, `os.rename`, `tempfile` — all unused). Only DB writes.
   - Live-PG `@requires_db` round-trip: finalize against real PG row with realistic `opus_draft_markdown` content + assert `kbl_cross_link_queue` row count.

### CHANDA pre-push

- **Q1 Loop Test:** deterministic step; no Leg touched. Pass.
- **Q2 Wish Test:** tight schema = Director trusts Silver; clean cross-link queue = future digest narrative enrichment trivial. Pass.
- **Inv 4** — Pydantic structurally rejects `author: director` + `voice: gold`. Not a runtime check; a type-system check. Best kind.
- **Inv 6** — this IS Step 6.
- **Inv 8** — `author: Literal['pipeline']` in Pydantic makes Silver→Gold auto-promotion structurally impossible.
- **Inv 9** — Step 6 on Render does zero vault FS writes. All vault IO is Step 7 on Mac Mini. **Explicit test asserts this.**
- **Inv 10** — no prompts.

### Branch + PR

- Branch: `step6-finalize-impl`
- Base: `main`
- PR title: `STEP6-FINALIZE-IMPL: kbl/steps/step6_finalize.py + kbl/schemas/silver.py + kbl_cross_link_queue (option C)`
- Target PR: #15

### Reviewer

B2.

### Timeline

~75-90 min. Slight uptick vs original estimate because Option C adds a migration + UPSERT test. Still focused Python, no external calls.

### Dispatch back

> B1 STEP6-FINALIZE-IMPL shipped — PR #15 open, branch `step6-finalize-impl`, head `<SHA>`, <N>/<N> tests green. Option C cross-link flow: kbl_cross_link_queue table + UPSERT idempotency. Inv 9 zero-FS-write test passing. pipeline_tick _process_signal extended through awaiting_commit. Ready for B2 review.

### After this task

- B2 reviews PR #15 → auto-merge on APPROVE
- I dispatch **Mac Mini Step 7 prep** to AI Dennis (IT shadow agent) when PR #15 opens
- Next B1 ticket: **STEP7-COMMIT-IMPL** per KBL-B §4.8 — consumes `kbl_cross_link_queue WHERE realized_at IS NULL` + `signal_queue.final_markdown`, writes both to vault, batches into a single git commit, marks `realized_at = NOW()` on success.

---

*Posted 2026-04-19 by AI Head. Option C ratified. All OQs resolved. Straight implementation against spec.*
