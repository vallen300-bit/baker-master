# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #5 merged at `45c0962`. PR #6 merged at `de7fd6f`. Idle since.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: LAYER0-IMPL — Step 0 Layer 0 Evaluator + Helpers

**Why now:** Layer 0 rules spec ratified (B2 READY at commit `64d1712`). Loader shipped (PR #4). Schema shipped (PR #5). Now build the evaluator that glues rules + signals together. Production-moving.

### Scope

**IN — new modules + helpers**

1. **`kbl/layer0.py`** — the evaluator
   - `evaluate(signal, ruleset=None) -> Layer0Decision` — returns `pass` / `drop(rule_name, detail)`
   - `_process_layer0(signal, conn) -> Layer0Decision` — wraps `evaluate()` + writes to `kbl_layer0_hash_seen` on PASS + `kbl_layer0_review` on 1-in-50 drop sample
   - First-match-wins over rules list ordering
   - Director-sender check runs BEFORE any rule (C2 invariant — never-drop)
   - VIP-sender soft-fail CLOSED (S4 — treat as VIP during VIP-service downtime)
   - Short-slug alias-aware topic-override (S3)
   - Content-hash dedupe (S5) — insert hash on PASS only (not on drop)
   - Review-queue sampling (S6) — deterministic `signal.id % 50 == 0`, 500-char excerpt

2. **`baker/director_identity.py`** — `is_director_sender(signal) -> bool`
   - Normalizes phone via `re.sub(r'\D', '', raw)` to match WAHA serialization `41799605092`
   - Recognizes emails: `dvallen@brisengroup.com`, `vallen300@gmail.com`, `office.vienna@brisengroup.com`
   - Recognizes WhatsApp numbers: `41799605092` (after normalization of any format — `+41 79 960 50 92`, `+41799605092`, `41799605092@c.us`, etc.)
   - Single source of truth — Layer 0 + future Ayoniso + future Gold-promote checks all use this

3. **`kbl/layer0_dedupe.py`** — hash-store ops
   - `normalize_for_hash(content: str) -> str` — lowercase, trim, collapse multi-space, strip trailing whitespace per line, drop standard sig blocks (`\n--\n.*`). Deterministic recipe.
   - `has_seen_recent(conn, content_hash: str) -> bool` — checks `kbl_layer0_hash_seen` with `ttl_expires_at > now()`
   - `insert_hash(conn, content_hash, source_signal_id, source_kind, ttl_hours=72)`
   - `cleanup_expired(conn) -> int` — daily cron callable; returns count of rows purged

4. **`kbl_layer0_review_insert(conn, signal_id, rule_name, excerpt, source_kind)`** — in `kbl/layer0.py` or separate small module
   - Column names match PR #5 schema exactly: `signal_id`, `dropped_by_rule`, `signal_excerpt`, `source_kind`, `created_at` (default now())
   - Note: B2 PR #5 review N1/N2 flagged B3's draft uses `rule_name` / `excerpt` / `sampled_at` in §3.5/§3.6. Schema wins — use PR #5 column names (`dropped_by_rule`, `signal_excerpt`, `created_at`).

**Reconciliations (per B2 Step 0 rereview N1/N2/N4):**
- Step 0 draft's §3.5/§3.6 column names: writer code uses schema column names; if spec and schema diverge, update the spec in a follow-up docs commit (not in this PR)
- Phone normalization: `is_director_sender()` normalizes `+41 79 960 50 92` / `+41799605092` / `41799605092@c.us` to canonical `41799605092` before comparison

**OUT**
- Rule content in baker-vault (Director / B3 own the YAML)
- Loader changes (PR #4 already shipped; just call `get_ruleset()`)
- Pipeline wiring beyond Step 0 (Step 1 onward is separate impl)
- Review-queue UI (KBL-C)

### Tests (new)

- `tests/test_layer0_eval.py`:
  - Pass happy path (signal matches no rule)
  - Drop on each rule name in the fixture ruleset
  - First-match-wins ordering
  - Director-sender short-circuits to PASS (C2 invariant)
  - VIP-sender soft-fail CLOSED (S4) — mock VIP service unreachable, signal still passes
  - Short-slug alias override (S3) — "Andrey Oskolkov" whole-word matches `ao` only via alias
- `tests/test_layer0_dedupe.py`:
  - `normalize_for_hash` deterministic (same input → same output)
  - `has_seen_recent` returns True when hash present + within TTL
  - `has_seen_recent` returns False when hash expired
  - `insert_hash` + `cleanup_expired` round-trip
- `tests/test_director_identity.py`:
  - All email variants recognized
  - WhatsApp number formats all normalize to canonical
  - Non-Director sender returns False
  - Edge: malformed phone string doesn't crash

### CHANDA pre-push

- Q1 Loop Test: Layer 0 is upstream of loop reading. Evaluator doesn't modify Leg 1/2/3 mechanism. Pass.
- Q2 Wish Test: serves wish (filters noise so loop operates on signal). Pass.
- Inv 1: all PASS signals flow downstream to Step 1. Zero-match case = PASS. Correct.
- Inv 4: Director-sender short-circuit enforces author:director authority at signal-intake boundary.
- Inv 7: Layer 0 ≠ alert. Review queue is audit, not notification. Log-only on drop.

### Branch + PR

- Branch: `layer0-impl`
- Base: `main`
- PR title: `LAYER0-IMPL: kbl/layer0.py + director_identity + dedupe helpers`
- Target PR: #7
- PR body: cite rules spec @ `64d1712`, schema @ PR #5, loader @ PR #4; flag N1/N2 docs-update follow-up

### Reviewer

B2 (reviewer-separation).

### Timeline

~90-120 min — largest KBL-B impl unit so far but bounded by the spec.

### Dispatch back

> B1 LAYER0-IMPL shipped — PR #7 open, branch `layer0-impl`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

*Posted 2026-04-18 by AI Head. B3 on micro-fix (env-var typo). B2 CHANDA ack done — awaits REDIRECT fold review task C. Director: Fireflies labeling in separate session (~10 transcripts).*
