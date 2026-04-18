# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #7 phone fix + PR #9 LOOP-GOLD-READER-1 shipped. PR #9 merged at `c95db55`. PR #7 awaits B2 phone-delta re-verify. Idle since.
**Task posted:** 2026-04-18
**Status:** OPEN

---

## Task: STEP2-RESOLVE-IMPL — Source-Specific Thread/Arc Resolver

**Why now:** All dependencies ready. Step 1 triage writes `primary_matter` and `related_matters` (PR #8). Layer 0 upstream (PR #7). LOOP-GOLD-READER-1 for downstream Step 5 (PR #9 merged). Step 2 is the next pipeline unit. Spec ratified in KBL-B §4.3.

### Scope

**IN**

1. **`kbl/steps/step2_resolve.py`** — source-dispatched resolver
   - Strategy pattern: one `Resolver` per source
   - Public: `resolve(signal_id, conn) -> list[str]` — returns resolved vault-relative paths
   - State transitions: `awaiting_resolve` → `resolve_running` → `awaiting_extract` (or `resolve_failed`)
   - Writes: `signal_queue.resolved_thread_paths` (JSONB array)
   - Degraded-mode behavior: on Voyage API unreachable for transcript/scan sources → log WARN, write empty array (new-thread semantics), advance to `awaiting_extract` (do NOT fail the signal)

2. **`kbl/resolvers/email.py`** — metadata resolver
   - Input: `payload->>'email_message_id'`, `payload->>'in_reply_to'`, `payload->'references'`, `payload->>'subject'`
   - Walk `in_reply_to` chain via `signal_queue.payload` lookups (same thread = same `in_reply_to`/`references` graph)
   - Fall back to Subject `Re:` normalization if no header graph match
   - Output: up to 3 vault paths from `wiki/<primary_matter>/*.md` where matching signals' committed paths exist

3. **`kbl/resolvers/whatsapp.py`** — metadata resolver
   - Input: `payload->>'chat_id'`, `payload->>'sent_at'`
   - Same `chat_id` + last-90-day window + same `primary_matter` = same thread
   - Output: vault paths of most recent N prior committed signals in chat

4. **`kbl/resolvers/transcript.py`** — embedding resolver
   - Input: `raw_content`, `primary_matter`
   - Compute Voyage embedding (voyage-3)
   - Query `wiki/<primary_matter>/*.md` frontmatter-stored embeddings (IF stored — else compute on-the-fly for Phase 1)
   - Return top-3 with cosine similarity ≥ `KBL_STEP2_RESOLVE_THRESHOLD` (default 0.75, env-configurable)
   - Degraded-mode: Voyage 500/timeout → empty list, log WARN

5. **`kbl/resolvers/scan.py`** — embedding resolver
   - Same as transcript but scoped to `payload->>'director_context_hint'` if present

6. **`kbl/voyage_client.py`** (if not exists) — HTTP client wrapper for `voyage-3`
   - Single `embed(text: str) -> list[float]`
   - Timeout 10s
   - Raises `VoyageUnavailableError` on 5xx / timeout
   - Env: `VOYAGE_API_KEY` (already in KBL-A secrets)

7. **Tests** — `tests/test_step2_resolve.py`:
   - Email resolver: In-Reply-To graph walk (3-signal chain → 2 prior paths)
   - Email resolver: no match → `[]`
   - WhatsApp resolver: same chat_id → prior N paths
   - Transcript resolver: mocked Voyage client, 3-match happy path
   - Transcript resolver: Voyage unavailable → degraded mode (empty list + WARN log)
   - Scan resolver: same as transcript
   - `resolve()` dispatcher: routes by source correctly
   - Invariant: `resolved_thread_paths` always array (never None), always vault-relative starting `wiki/`

### Cost ledger

- Email + WhatsApp: no row (metadata-only, zero cost)
- Transcript + Scan: one row per call, `step='resolve'`, `model='voyage-3'`, `input_tokens` (approx = chars / 4), `cost_usd ≈ 0.00005`

### CHANDA pre-push

- **Q1:** Step 2 is downstream of Step 1 reads (Leg 3). It does not touch the reading pattern itself. Pass.
- **Q2:** serves wish (arc continuity = loop compounding). Pass.
- **Inv 1:** empty resolved_thread_paths = valid zero-Gold read for new-arc signals. Test explicitly.
- **Inv 9:** resolver READS baker-vault only. No writes (that's Step 7). Verify.

### Branch + PR

- Branch: `step2-resolve-impl`
- Base: `main`
- PR title: `STEP2-RESOLVE-IMPL: source-specific thread/arc resolver`
- Target PR: #10

### Reviewer

B2.

### Timeline

~75-105 min (4 resolvers + Voyage client wrapper + tests).

### Dispatch back

> B1 STEP2-RESOLVE-IMPL shipped — PR #10 open, branch `step2-resolve-impl`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

*Posted 2026-04-18 by AI Head. B2 on REDIRECT fold review (Task D). B3 idle.*
