# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-19 (late morning)
**Status:** OPEN — PR #15 review (final pipeline PR before Step 7)

---

## Completed since last dispatch

- Task M — PR #14 S1 delta APPROVE (@ `e2bb201`) ✓ **MERGED `58ed935e`**

---

## Task N (NOW): Review PR #15 — STEP6-FINALIZE-IMPL (Option C cross-link flow)

**PR:** https://github.com/vallen300-bit/baker-master/pull/15
**Branch:** `step6-finalize-impl`
**Head:** `69d8483`
**Tests:** 89/89 green in scope (41 schema + 39 finalize + 9 pipeline_tick) + 337 wider KBL subset green, zero regressions
**Spec:**
- `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` @ `ffa2a26` — B3's spec (5 Pydantic models, 21 validation rules, 12-class error matrix)
- `briefs/_drafts/KBL_B_STEP6_OQ_RESOLUTIONS_20260419.md` @ `bf1ae53` — all 8 OQs ratified
- Dispatch brief @ `22f4000` — Option C cross-link flow

### Scope — surfaces to audit

1. **`migrations/20260419_step6_kbl_cross_link_queue.sql`** — new table `kbl_cross_link_queue` with composite PK `(source_signal_id, target_slug)` + 2 indexes
2. **`migrations/20260419_step6_signal_queue_final_markdown.sql`** — `final_markdown` + `target_vault_path` columns (IF NOT EXISTS)
3. **`kbl/schemas/silver.py`** — 5 Pydantic models per spec §2 + OQ resolutions
4. **`kbl/steps/step6_finalize.py`** — finalizer with parse → validate → build path → UPSERT cross-links → advance state
5. **`kbl/exceptions.py`** — `FinalizationError` net-additive
6. **`kbl/pipeline_tick.py`** — `_process_signal` extended through `awaiting_commit`
7. **`tests/test_silver_schema.py`** — 41 tests covering R1-R21 validation rules
8. **`tests/test_step6_finalize.py`** — 39 tests for orchestration + UPSERT + Inv 9 zero-FS-write
9. **`tests/test_pipeline_tick.py`** — extended with 9 new tests for Step 6 happy + fail paths

### Specific scrutiny

#### Pydantic schema enforcement (structural Inv 4 + Inv 8)

1. **`author: Literal['pipeline']`** — structurally impossible to emit `author: director`. Verify Pydantic raises on `author: director` attempt (test should exist).
2. **`voice: Literal['silver']`** — structurally impossible to emit `voice: gold`. Test should exist.
3. **`vedana: Literal['threat', 'opportunity', 'routine']`** — strict 3-value per `memory/vedana_schema.md`. Rejects `neutral`, `other`, etc.
4. **`source_id` singular (not `sources`)** — per OQ1 resolution. Verify field name + type.
5. **`title` max 160 chars** — per OQ2.
6. **`thread_continues` lenient regex** (`^wiki/.*\.md$`) — per OQ3.
7. **`money_mentioned: list[str]`** — raw strings emitted by Opus. Parser `_parse_money_string` normalizes to `MoneyMention` at validation time (per OQ4). Verify parser handles `[3000 GBP]`, `[1200000 EUR, 600000 EUR]`, and malformed strings → `None`.
8. **`status: Literal['full', 'stub_auto', 'stub_cross_link', 'stub_inbox']`** — per OQ5.
9. **Currency enum `{EUR, USD, CHF, GBP, RUB}`** — per OQ6.
10. **`primary_matter: Optional[MatterSlug]`** with R7 coherence: null primary iff `related_matters == []`. Per OQ7.
11. **`⚠ CONTRADICTION:` marker** — freeform, no structural parse. Per OQ8.
12. **Zero-Gold handling** (Inv 1) — Silver with empty prior-Gold context finalizes without crash.

#### Cross-link flow (Option C)

13. **Table schema** — `kbl_cross_link_queue` matches dispatch §2 exactly: `source_signal_id BIGINT NOT NULL REFERENCES signal_queue(id) ON DELETE CASCADE`, `target_slug TEXT NOT NULL`, `stub_row TEXT NOT NULL`, `vedana TEXT`, `source_path TEXT NOT NULL`, `created_at`, `realized_at`. PRIMARY KEY `(source_signal_id, target_slug)`.
14. **Indexes** — `idx_kbl_cross_link_queue_unrealized` WHERE `realized_at IS NULL`; `idx_kbl_cross_link_queue_target_slug` on `(target_slug, created_at DESC)`.
15. **UPSERT correctness** — `INSERT ... ON CONFLICT (source_signal_id, target_slug) DO UPDATE SET stub_row, vedana, source_path, created_at = NOW(), realized_at = NULL`. Verify re-emission unrealizes the row (Step 7 will re-realize). **Test:** first call INSERTs, second identical call UPDATEs same row → `COUNT(*) == 1` on composite PK.
16. **`stub_row` format** — per B3 spec §4 exactly: `<!-- stub:signal_id=<id> --> - YYYY-MM-DD | source_path | vedana-prefix | 1-line excerpt`. Verify.
17. **No filesystem IO from Step 6** — B3 spec §4.3 (tempfile + rename) is IGNORED per Option C. Step 6 does PG writes only. **Test:** Inv 9 zero-FS-write test pins `os.rename`, `os.replace`, `os.makedirs`, `tempfile.NamedTemporaryFile`, `Path.write_text`, `Path.write_bytes` — all assert uncalled on happy path.

#### Target vault path builder

18. **Regex compliance** — `target_vault_path` matches `^wiki/[a-z0-9-]+/\d{4}-\d{2}-\d{2}_[\w-]+\.md$`. Verify test for canonical path + collision handling (`_<source_id_short>` suffix if path exists).
19. **Slug-of-title** — lowercase, dash-separated, alphanumeric + dashes only, max 60 chars. Edge cases: unicode, punctuation, very long titles.

#### State machine + pipeline_tick wire-up

20. **State transitions:** `awaiting_finalize` → `finalize_running` → `awaiting_commit` (success) OR `opus_failed` (Pydantic validation → Opus R3 retry per §4.7) OR `finalize_failed` (after 3 Opus retries).
21. **CHECK constraint compliance** — all state values in 34-value set from PR #12.
22. **`paused_cost_cap` short-circuit** — Step 6 NOT called on paused signals; they re-enter next tick. Verify wire-up.
23. **pipeline_tick orchestrator** — `_process_signal` now stops at `awaiting_commit` (Step 7 not yet shipped). Tests should assert no attempt to call Step 7.
24. **Line count check** — B1's previous orchestrator was ~70 lines (under 100-line guardrail). New Step 6 additions shouldn't blow past. Verify.

#### Error matrix (B3 spec §5)

25. **12-class coverage** — each of 12 failure classes produces correct state + retry policy. Verify tests exist per class:
    - Missing required frontmatter key → `opus_failed`, R3
    - Invalid enum (vedana/voice/author) → `opus_failed`, R3
    - Unknown slug in primary/related → `opus_failed`, R3
    - Body too short/long → `opus_failed`, R3
    - Invalid `target_vault_path` regex → `opus_failed`, R3
    - Money parse failure → field drops silently (not a FinalizationError)
    - R7 violation (null primary + non-empty related) → `opus_failed`, R3
    - After 3 Opus retries → `finalize_failed` terminal

#### Logging

26. **Pydantic WARN rows** — one per failed field. `level='WARN'`, `component='finalize'`, `message=f'{field}: {reason}'`.
27. **No ERROR for cross-link IO** — since Step 6 does no FS IO, those errors don't apply (Step 7 territory).

#### CHANDA

28. **Q1 Loop Test** — deterministic step; no Leg touched. Verify cited in commit or module docstring.
29. **Q2 Wish Test** — tight schema = Director trusts Silver = faster Silver→Gold velocity.
30. **Inv 4 structurally enforced** via Pydantic types.
31. **Inv 8 structurally enforced** via Pydantic types.
32. **Inv 9 test present** — zero vault FS writes from Step 6.

### Format

`briefs/_reports/B2_pr15_review_20260419.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~40-60 min. Focused Python, Pydantic-heavy, clean surface.

### Dispatch back

> B2 PR #15 review done — `briefs/_reports/B2_pr15_review_20260419.md`, commit `<SHA>`. Verdict: <...>.

On APPROVE: I auto-merge PR #15. Step 6 done; 6 of 7 pipeline steps on main.

---

## Working-tree reminder

**Never /tmp/.** Work in `~/bm-b2` or similar under home dir (survives reboots). Fresh clone if local stale:
```
rm -rf ~/bm-b2 && git clone git@github.com:vallen300-bit/baker-master.git ~/bm-b2 && cd ~/bm-b2
```

**After each PR cycle: quit your Terminal tab and start fresh** — releases accumulated Claude Code CLI memory. Director's Mac hit 95 GB Terminal RAM earlier; sessions ballooning over long runs is the cause.

---

*Posted 2026-04-19 by AI Head. PR #15 = last KBL-B Phase 1 implementation PR before Step 7 (Mac Mini).*
