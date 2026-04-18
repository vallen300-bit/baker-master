# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous:** All prior tasks done (PR #4/5/6 reviews, Step 0 rereview, Step 1+Fixture 14 rereview, CHANDA ack). PR #7 (LAYER0-IMPL) just landed from B1.
**Task posted:** 2026-04-18
**Status:** OPEN — two deliverables in sequence

---

## Task A (now): Review PR #7 — LAYER0-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/7
**Branch:** `layer0-impl`
**Head:** `7342617`
**Tests:** 84/84 new (31 director_identity + 27 dedupe + 26 eval) + 1 live-PG skip; related suite 137/137

### Scope of review

**IN**
- **`kbl/layer0.py`** — evaluator: `evaluate()`, `_process_layer0()`, first-match-wins ordering, never-drop invariant chain (scan → Director → primary_matter_hint → VIP CLOSED → slug/alias topic override CLOSED)
- **`baker/director_identity.py`** — `is_director_sender()` — email variants + WhatsApp digit-only normalization
- **`kbl/layer0_dedupe.py`** — `normalize_for_hash` / `has_seen_recent` / `insert_hash` / `cleanup_expired`
- **Side effects audit:**
  - Hash INSERT on PASS only (S5 preserves legit copies)
  - Review INSERT on DROP when `signal.id % 50 == 0` (S6 deterministic)
  - Review row columns match PR #5 schema exactly (`dropped_by_rule`, `signal_excerpt`, `source_kind`, `created_at`) — N1/N2 from your Step 0 rereview
- **CHANDA compliance:**
  - Inv 4: Director-sender short-circuit enforces author-director authority at intake
  - Inv 7: Layer 0 ≠ alert (review queue is audit); log-only on drop
  - Inv 1: zero-match case → PASS (not error)
  - Inv 10: rules are data, evaluator is stable code — no self-modification

**Specific scrutiny**

1. **Phone normalization correctness** — verify the regex strips all non-digits and handles `+` prefix, `@c.us` WAHA suffix, space-separated format, and that comparison uses the canonical `41799605092` form.
2. **Never-drop ordering (§3.2)** — B1 implemented scan → Director → primary_matter_hint → VIP → slug/alias override. Is that the right order semantically? E.g., if signal is from Director AND has VIP-service-downtime, Director check wins — verify.
3. **Hash-store TTL correctness** — 72h default, `ttl_expires_at > now()` check, cleanup idempotent
4. **Review queue determinism** — `signal.id % 50 == 0` means sample hits signals 0, 50, 100, ... Is that the intended distribution vs hashing the signal content? B3 spec'd this; if you disagree, flag.
5. **Error paths** — what happens on DB unavailable during hash read / review insert? PASS-fail-open vs CLOSED? Verify explicitly.
6. **Integration with existing `kbl/slug_registry.py`** — does `is_director_sender` / topic-override logic use `slug_registry.aliases_for()` per S3?

### Format

`briefs/_reports/B2_pr7_review_20260418.md`
Verdict: APPROVE / REDIRECT (list inline-appliable fixes) / BLOCK

### Timeline

~30-40 min. PR #7 is the largest KBL-B impl unit to date.

---

## Task B (now): Review STEP5-OPUS-PROMPT draft

**File:** `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` at commit `7ea63c6` (570 lines, 36KB)
**Author:** B3

### AI Head resolutions to pass through your review

1. **OQ1 (author frontmatter field) resolution:** Step 5 outputs `author: pipeline`. Director promotion flips to `author: gold` / `voice: gold`. Two distinct author values track lifecycle: `pipeline` (machine-generated, Silver) vs `director` (Gold-promoted). Verify B3's draft spec aligns; if it currently says `author: tier2`, flag as should-fix for `author: pipeline`.
2. **OQ5 (`load_gold_context_by_matter` helper):** confirmed needed. B1 follow-on PR will land separately. Treat OQ5 as "unblocks deployment, not draft review" per B3's own flag.

### Scope of review

**IN**
- Template completeness against §4.6 Step 5 I/O contract (reads, writes, invariants)
- Input blocks present: `{signal_raw_text}`, `{extracted_entities}`, `{primary_matter}`, `{related_matters}`, `{vedana}`, `{triage_summary}`, `{resolved_thread_paths}`, `{gold_context_by_matter}`, `{hot_md_block}`, `{feedback_ledger_recent}`
- **Leg 1 compliance:** `gold_context_by_matter` MUST be read + honored, even when empty. Zero-Gold case MUST produce valid first entry (not error). Worked example #1 tests this.
- **Inv 8 compliance:** frontmatter `voice: silver` ALWAYS. No self-promote.
- **Contradiction handling:** if signal contradicts prior Gold, flag with `⚠ CONTRADICTION:` marker in body, don't silently overwrite
- Hard constraints stated in §1.2: no hallucination, no speculation, no long quotes without citation
- Output contract: frontmatter + body, no preamble/postamble, 300-800 token target
- Worked examples (§3): 2-3 from the labeled corpus — zero-Gold, continuation, cross-matter
- CHANDA §5 Q1 + Q2 cited in §4 pre-push self-check

**OUT**
- Re-opening REDIRECT (Step 6 stays deterministic)
- OQ5 helper impl (B1 ticket)
- Pydantic frontmatter schema (KBL-B §4.7 impl)

### Format
`briefs/_reports/B2_step5_opus_prompt_review_20260418.md`
Verdict: APPROVE / REDIRECT (list fix items, inline-appliable) / BLOCK

### Timeline
~25-35 min.

---

## Task C (now, new): Review PR #8 — STEP1-TRIAGE-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/8
**Branch:** `step1-triage-impl`
**Head:** `4918b52`
**Tests:** 44/44 new green + 1 live-PG skip; related suite 97 passed

### Scope

**IN**
- `kbl/prompts/step1_triage.txt` — template extract matches `KBL_B_STEP1_TRIAGE_PROMPT.md` §1.1 (file-based load pattern, Inv 10 compliance)
- `kbl/steps/step1_triage.py` — `build_prompt` / `parse_gemma_response` / `normalize_matter` / `call_ollama` / `triage` / `TriageResult`
- `kbl/exceptions.py` — `TriageParseError` + `OllamaUnavailableError`
- `migrations/20260418_step1_signal_queue_columns.sql` — idempotent ADD COLUMN ×6 for `primary_matter`, `related_matters`, `vedana`, `triage_score`, `triage_confidence`, `triage_summary`
- **State transition correctness:** `awaiting_triage` → `triage_running` → `awaiting_resolve` or `awaiting_inbox_route` based on threshold
- **CHANDA Inv 3 compliance:** reads hot.md + feedback_ledger on EVERY call (B1 tested via patched counters across 3 invocations — verify that test)
- **CHANDA Inv 10 compliance:** template loaded once from file — verify no runtime re-read or mutation
- **CHANDA Inv 1 compliance:** zero-Gold / zero-hot.md / zero-ledger render fallback strings (not crash)
- **Cost ledger row:** `step='triage'`, `model='gemma2:8b'`, `cost_usd=0.0`, input/output tokens if Ollama exposes
- **Parse failure path:** writes kbl_cost_ledger with `success=False` and re-raises — verify

**Specific scrutiny**
1. `call_ollama` error handling — DB connection lost, Ollama timeout, malformed response — each path covered?
2. `parse_gemma_response` fields: does the parser accept both exact `null` and string `"null"` for primary_matter? (Gemma inconsistency common)
3. Triage threshold gating — `KBL_PIPELINE_TRIAGE_THRESHOLD=40` default. Edge case: `triage_score == 40` — inclusive or exclusive of PASS?
4. Cross-matter elevation (S1 from Step 1 third cycle): does `triage()` implementation correctly consume hot.md to adjust triage_score? Or is that logic deferred to the prompt itself (model decides)?
5. Env var naming: `KBL_STEP1_LEDGER_LIMIT` (canonical per prior reconciliation) — confirm used consistently.

### Format
`briefs/_reports/B2_pr8_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline
~30-40 min.

---

## Task C-delta-phone (fast, ~5 min): PR #7 S1 phone fix delta re-verify

B1 applied S1 at head `4780a40`: `_normalize_phone` strips leading `00` after digit extraction; `0041 79 960 50 92` → canonical `41799605092`. +4 parametrized tests. 88/88 tests green.
Short APPROVE report or append to `B2_pr7_review_20260418.md`.

---

## Task C-new (medium, ~30-40 min): Review PR #9 — LOOP-GOLD-READER-1

**PR:** https://github.com/vallen300-bit/baker-master/pull/9
**Branch:** `loop-gold-reader-1`
**Head:** `88b460a`
**Tests:** 21 new green; full loop suite 46/46.

### Scope

- `kbl/loop.py` — new `load_gold_context_by_matter(matter, vault_path=None) -> str`
- Filter: `voice: gold` only (Silver excluded)
- Sort: filename order (chronological via date-prefix convention)
- Block format: `<!-- GOLD: wiki/<matter>/<file>.md -->` headers separated by blank lines
- Zero-Gold cases: missing dir / empty dir / all-Silver / missing-frontmatter → `""` (Inv 1 compliance)
- `LoopReadError` on IO/permission/env errors

### Specific scrutiny (this is Leg 1 critical infra per CHANDA §2)

1. **Zero-Gold tests exhaustive** — 4 variants tested (missing / empty / all-Silver / malformed). Verify coverage.
2. **Filename sort correctness** — date-prefix convention (`YYYY-MM-DD_topic.md`) + mixed naming: how does sort handle a non-date-prefix file? Lexicographic bucket behavior.
3. **Matter slug normalization** — does the helper call `slug_registry.normalize()` or assume caller pre-normalizes? B3's Step 5 prompt calls with `primary_matter` which IS already canonical. Verify expectation.
4. **Block concatenation** — blank-line separation is fine, but if a Gold body ends mid-line (no trailing newline), does the next block's `<!-- GOLD: ... -->` header get glued? Edge case.
5. **Performance note** — Step 5 reads this on every `full_synthesis` call. N Gold entries × file IO. For Hagenauer Phase 1, probably <10 entries, negligible. Flag if you see obvious caching opportunity.

### Format
`briefs/_reports/B2_pr9_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

---

## Task C-delta (fast, ~5 min): STEP5-OPUS S1 delta APPROVE

B3 applied S1 rename at `02e5063` (10 sites total: your 9 + 1 extra for internal consistency). Confirm and close out with short APPROVE report:

`briefs/_reports/B2_step5_opus_s1_delta_20260418.md` — one-paragraph verdict, note the 1 extra site B3 added (header Inv 4 bullet line 14) was a sensible preemptive catch.

---

## Task D (DONE — APPROVE at f712647)

REDIRECT fold reviewed + APPROVE'd. 3 nice-to-haves tracked:
- N1: §13 acceptance criteria — <5% "needs editing" threshold stated in §6.4 but not formalized in §13 acceptance list. Note: brief was extended by Director/linter; §13 now has concrete thresholds. Verify N1 superseded.
- N2: name deterministic metadata override as safety feature
- N3: document cross-link partial-failure idempotency semantics

Pre-flag for AI Head acknowledged: Step 6 impl ticket will include `author: pipeline` regardless-of-Opus-emission test.

---

## Task E (new): Review PR #10 — STEP2-RESOLVE-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/10
**Branch:** `step2-resolve-impl`
**Head:** `d735136`
**Tests:** 41/41 new green; related suite 100/100 (1 live-PG skip)

### Scope

**IN**
- `kbl/steps/step2_resolve.py` — source-dispatched `resolve(signal_id, conn)` + state machine + JSONB result write + conditional cost-ledger
- `kbl/resolvers/{email,whatsapp,transcript,scan,_embedding}.py` — 4 resolvers + shared vault-scan/cosine helper
- `kbl/voyage_client.py` — urllib wrapper for `/v1/embeddings`
- `kbl/exceptions.py` adds `VoyageUnavailableError` + `ResolverError`
- `migrations/20260418_step2_resolved_thread_paths.sql` — JSONB column + GIN index (idempotent)
- **Degraded-mode per §4.3:** Voyage 5xx/timeout → empty paths + WARN + ledger row `success=False` + advance to `awaiting_extract` (not `resolve_failed`)
- **Invariants:** `resolved_thread_paths` always JSONB array (never NULL); entries must start `wiki/` (non-compliant dropped with WARN)

**Specific scrutiny**
1. **Degraded-mode correctness** — Voyage unreachable does NOT fail the signal; signal continues with empty resolve. Verify no edge case flips to `resolve_failed` incorrectly.
2. **Email In-Reply-To graph walk** — depth cap? Cycle detection? If A→B→C→A exists, does the walker terminate?
3. **WhatsApp chat_id sliding window** — 90-day filter applied correctly?
4. **Embedding resolver threshold** — `KBL_STEP2_RESOLVE_THRESHOLD=0.75` default. Env-configurable?
5. **Wiki-relative path validation** — rejection of non-compliant entries with WARN is correct (not silent filter).
6. **Cost-ledger row for Voyage** — correct `step='resolve'`, `model='voyage-3'`, `cost_usd ≈ 0.00005` when fires; zero rows for email/WA resolvers.

### Format
`briefs/_reports/B2_pr10_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline
~30-40 min.

---

## Parallel state

- B1: STEP1-TRIAGE-IMPL dispatched (~60-90 min). PR #7 S1 phone-trunk-prefix fix queued for after.
- B3: STEP5-OPUS-PROMPT shipped, idle.
- AI Head: REDIRECT fold in progress.

### Dispatch back (after each task)

> B2 STEP5-OPUS-PROMPT review done — `briefs/_reports/B2_step5_opus_prompt_review_20260418.md`, commit `<SHA>`. Verdict: <...>.
> B2 REDIRECT fold review done — `briefs/_reports/B2_kbl_b_redirect_fold_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

*Posted 2026-04-18 by AI Head.*
