# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #14 STEP5-OPUS-IMPL merged at `58ed935e`. 6 of 7 pipeline steps on main.
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — STEP6-FINALIZE-IMPL, OQs all resolved

---

## Task: STEP6-FINALIZE-IMPL — Deterministic Silver document finalization

**Specs (ALL ratified):**
- `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` @ `ffa2a26` — B3's full spec (8 sections, 21 validation rules, 5 Pydantic models, 12-class error matrix, 6-event log spec)
- `briefs/_drafts/KBL_B_STEP6_OQ_RESOLUTIONS_20260419.md` (this session) — AI Head ratifications of all 8 OQs
- KBL-B brief §4.7 (anchor)

### Why

Step 6 is deterministic (post-REDIRECT 2026-04-18) — no model call, no ledger row. It's the **last quality gate** before vault commit. Pydantic validates Opus's `opus_draft_markdown`, builds `final_markdown`, writes cross-link stubs to `wiki/<m>/_links.md`. If this step accepts broken drafts, broken Silver lands in the vault. If it over-rejects, Opus R3 burns cost on valid-but-marginal drafts.

B3 has authored the spec fully. All 8 OQs are resolved (see table in OQ resolutions doc). **This is a straight implementation against the spec — no design work.**

### Scope — implement per `KBL_B_STEP6_FINALIZE_SPEC.md`

**IN**

1. **`kbl/schemas/silver.py`** — all 5 Pydantic models per spec §2:
   - `MatterSlug` constrained str (regex against v9 canonical form; validator reads `slugs.yml` once at module import, cached — static during process lifetime per spec)
   - `MoneyMention` model (amount: int, currency: `Literal['EUR', 'USD', 'CHF', 'GBP', 'RUB']`) — per **OQ6**
   - `SilverFrontmatter` — all required keys from §2 + OQ resolutions:
     - `source_id: str` (not `sources` — **OQ1**)
     - `title: str` max 160 chars (**OQ2**)
     - `voice: Literal['silver']` (Inv 8 enforcement)
     - `author: Literal['pipeline']` (Inv 8 enforcement)
     - `created: datetime` (ISO 8601, UTC, tz-aware validator)
     - `primary_matter: Optional[MatterSlug]` (**OQ7**: null allowed iff `related_matters == []`)
     - `related_matters: list[MatterSlug]` (unique, != primary_matter)
     - `vedana: Literal['threat', 'opportunity', 'routine']` (strict 3-value per `memory/vedana_schema.md`)
     - `triage_score: int` (0-100)
     - `triage_confidence: float` (0.0-1.0)
     - `money_mentioned: list[str]` (raw strings emitted by Opus; parser normalizes to `list[MoneyMention]` at validation time per **OQ4**)
     - `status: Literal['full', 'stub_auto', 'stub_cross_link', 'stub_inbox']` (**OQ5**)
     - `thread_continues: list[str]` (lenient regex `^wiki/.*\.md$` per **OQ3**)
   - `SilverDocument` — frontmatter + body (body char bound 1500-4000 per spec §2)
   - `CrossLinkStub` — per §4

2. **`kbl/steps/step6_finalize.py`** — the finalizer:
   - `finalize(signal_id: int, conn) -> None` — load `opus_draft_markdown` + all prior-step outputs → parse YAML frontmatter + body → validate via `SilverDocument` → build `target_vault_path` per §3.6 → write `final_markdown` + `target_vault_path` → append cross-link stubs per §4 → advance state
   - State transitions: `awaiting_finalize` → `finalize_running` → `awaiting_commit` (success) OR `opus_failed` (validation fail, triggers Opus R3 per §4.7 brief + spec §5) OR `finalize_failed` (after 3 Opus retries fail OR cross-link IO error after 1 retry)
   - Error matrix per spec §5 — 12 classes, each maps to state + retry policy
   - Money parser: `_parse_money_string(raw: str) -> MoneyMention | None` — ~30 lines per OQ4
   - `FinalizationError(KblError)` net-additive in `kbl/exceptions.py`

3. **`target_vault_path` builder** — per spec §3.6. Format: `wiki/<primary_matter>/<yyyy-mm-dd>_<slug_of_title>.md`. Slug-of-title: lowercase, dash-separated, alphanumeric + dashes only, max 60 chars. Collision handling: append `_<source_id_short>` suffix if path exists.

4. **Cross-link stub writer (`_append_cross_link`)** — per spec §4:
   - Format: one stub per `related_matter`, appended to `wiki/<m>/_links.md`
   - Idempotency by `source_signal_id`: grep the file for an existing stub with the same signal ID; REPLACE in place (not append duplicate). Regex: `^<!-- stub:signal_id=<id> -->$`
   - Atomic write: `tempfile.NamedTemporaryFile(dir=vault_path, delete=False)` + `os.rename()` (POSIX atomic)
   - Sorted by `created` DESC (newest first at top of file)

5. **Logging per spec §6:**
   - Pydantic validation failure: `level='WARN'`, `component='finalize'`, `message=f'{field}: {reason}'`. One log row per failed field.
   - Cross-link write failure: `level='ERROR'`, `component='finalize'`, `message=f'cross-link write failed: {path}: {reason}'`
   - Success: no log.

6. **No migration.** Columns `final_markdown TEXT` + `target_vault_path TEXT` already exist (per B1 PR #14 migration OR earlier; if not, B1 adds `ADD COLUMN IF NOT EXISTS` inline). Verify before starting.

7. **`pipeline_tick.py` wire-up** — extend `_process_signal` to call `finalize()` after Step 5's successful return. State progression: `awaiting_opus` → (Step 5) → `awaiting_finalize` → (Step 6) → `awaiting_commit`. Stop at `awaiting_commit` (Step 7 not yet shipped). Tests in `tests/test_pipeline_tick.py` extend to assert Step 6 call.

8. **Tests** — `tests/test_step6_finalize.py` + `tests/test_silver_schema.py`:
   - Pydantic schema coverage: valid document → parses; each R1-R21 validation rule → triggers expected failure
   - `target_vault_path` builder: canonical paths, collision handling, slug-of-title edge cases
   - Cross-link stub: idempotent replacement, atomic write, sorted order
   - Money parser: `[3000 GBP]` → MoneyMention, `[1200000 EUR, 600000 EUR]` → list of 2, malformed string → None
   - Error matrix: each of 12 failure classes produces correct state + retry policy
   - **CHANDA Inv 1** test: zero-Gold signal produces valid Silver (doesn't crash on empty prior-Gold context)
   - **CHANDA Inv 4** test: Pydantic rejects any Opus draft with `author: director` or `voice: gold` — structural enforcement of Silver→Gold-only-by-Director
   - **CHANDA Inv 8** test: all emitted Silver has `author: pipeline` + `voice: silver`
   - Live-PG `@requires_db` round-trip: finalize against real PG row with real `opus_draft_markdown` content

### CHANDA pre-push

- **Q1 Loop Test:** Step 6 is deterministic, no Leg touched (reads are DB columns, writes are DB + vault file). Inv 3 Leg 3 not applicable (no hot.md/ledger read). Pass.
- **Q2 Wish Test:** serves wish — tight schema = Director trusts Silver = faster Silver→Gold velocity. Pass.
- **Inv 4** (author-director files untouched) — Step 6 reads opus_draft_markdown (created by pipeline, not Director). Cross-link stubs written to `wiki/<m>/_links.md` — these are pipeline files, not Director files. Verify none of the target paths have `author: director` frontmatter.
- **Inv 6** (never skip Step 6) — this IS Step 6. Its existence satisfies the invariant; no further check.
- **Inv 8** (Silver→Gold only by Director edit) — enforced at Pydantic layer (`author: Literal['pipeline']` + `voice: Literal['silver']`). Structural impossibility to emit Gold.
- **Inv 9** (Mac Mini single writer) — cross-link stubs write to `wiki/<m>/_links.md`. **In the current deploy model, Step 6 runs on Render** — but Step 7 (which runs on Mac Mini) is where the commit happens. Cross-link stubs from Step 6 land on Render's local file system, then Step 7 picks them up to commit. **Verify this flow matches brief §4.7 side-effect spec.** If the flow is "Step 6 writes cross-link stubs on Render, Step 7 commits from Mac Mini" — then we need a sync mechanism (probably Step 7 reads both `final_markdown` from PG AND cross-link staging area from a shared path). Flag any ambiguity; ask AI Head before designing around it.
- **Inv 10** (prompts don't self-modify) — Step 6 has no prompts. Pass.

### Branch + PR

- Branch: `step6-finalize-impl`
- Base: `main`
- PR title: `STEP6-FINALIZE-IMPL: kbl/steps/step6_finalize.py + kbl/schemas/silver.py`
- Target PR: #15

### Reviewer

B2.

### Timeline

~60-90 min. Pure Python, no external calls, tight spec. Focused surface.

### Dispatch back

> B1 STEP6-FINALIZE-IMPL shipped — PR #15 open, branch `step6-finalize-impl`, head `<SHA>`, <N>/<N> tests green. Pydantic schema enforces Inv 4 + Inv 8 structurally. pipeline_tick _process_signal extended through awaiting_commit. Ready for B2 review.

### After this task

- B2 reviews PR #15 → auto-merge on APPROVE
- I dispatch AI Dennis on **Mac Mini Step 7 prep** (SSH keys + git clone + flock) in parallel with this task shipping, per Director ratification
- Next B1 ticket: **STEP7-COMMIT-IMPL** per KBL-B §4.8

---

*Posted 2026-04-19 by AI Head. All 8 OQs resolved; B1 implements against the spec directly. Step 6 closes the loop from Opus draft → Pydantic-validated Silver → ready-to-commit.*
