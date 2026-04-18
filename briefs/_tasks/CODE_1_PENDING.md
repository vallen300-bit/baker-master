# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** STEP1-TRIAGE-IMPL shipped as PR #8. PR #7 REDIRECT with 1 should-fix (phone trunk prefix).
**Task posted:** 2026-04-18
**Status:** OPEN — two items in sequence

---

## Task A (small, now): PR #7 Phone Trunk-Prefix Fix

**Source:** `briefs/_reports/B2_pr7_review_20260418.md` S1

### What

In `baker/director_identity.py`, the digit-only normalizer currently handles `+41 79 960 50 92`, `+41799605092`, `41799605092@c.us` — but misses the `0041` international trunk-prefix form (European dial-convention alternative to `+41`).

**Fix:** after digit extraction, if the result starts with `00` followed by country code, strip the leading `00`. One-line addition. Add parametrized test case `0041799605092` → canonical `41799605092`.

### Branch

Amend the `layer0-impl` branch (PR #7 open), push. B2 re-verifies via 5-min delta.

### Dispatch back

> B1 PR #7 S1 phone trunk-prefix fix applied — head `<SHA>`, <N>/<N> tests green. Ready for B2 re-verify.

---

## Task B (medium, after Task A): LOOP-GOLD-READER-1 — `load_gold_context_by_matter` helper

**Why now:** STEP5-OPUS-PROMPT §1.4 (B3 draft at `7ea63c6`) references `load_gold_context_by_matter(matter, vault_path=None)` as an input block. B3 framed as deployment-blocker (not draft-review blocker) per their OQ5. Step 5 can't fire without it. Same SLUGS-1 / LOOP-HELPERS-1 loader-style shape.

### Scope

**IN**
- New helper in `kbl/loop.py` (extending existing module):

```python
def load_gold_context_by_matter(matter: str, vault_path: str | None = None) -> str:
    """Load all Gold wiki entries under baker-vault/wiki/<matter>/ into a single prompt-insertable block.

    vault_path: override `$BAKER_VAULT_PATH`. Required via env var otherwise.
    matter: the primary_matter slug (canonical; caller normalizes via slug_registry if needed).

    Returns:
      A concatenated Markdown block with page-break separators:

        <!-- GOLD: wiki/<matter>/2026-04-01_topic.md -->
        ---
        <frontmatter>
        ---
        <body>

        <!-- GOLD: wiki/<matter>/2026-04-03_other.md -->
        ...

      Returns "" (empty string) if the matter directory has no Gold entries.
      Empty return is Inv 1 compliant: zero Gold is read AS zero Gold.

    Raises:
      LoopReadError on IO/permission errors.

    Filter: only files with frontmatter `voice: gold`. Silver entries are EXCLUDED.
    Ordering: sorted by filename (date-prefix convention → chronological).
    """
```

- Unit tests in `tests/test_loop_gold_reader.py`:
  - Happy path: 3 Gold files in matter dir → concatenated with page-breaks, correct order
  - Zero-Gold case: empty dir → returns `""` (not raise, not None)
  - Mixed Silver + Gold: Silver filtered out
  - Missing matter dir (new matter, no dir yet) → returns `""` (zero-Gold equivalent)
  - Permission error → raises `LoopReadError`
  - Malformed frontmatter (no `voice:` key) → treated as Silver, excluded
- Fixture vault layout in `tests/fixtures/gold_reader_vault/`:
  - `wiki/hagenauer-rg7/2026-04-01_kick_off.md` (voice: gold)
  - `wiki/hagenauer-rg7/2026-04-03_hassa_reply.md` (voice: gold)
  - `wiki/hagenauer-rg7/2026-04-05_draft.md` (voice: silver)
  - `wiki/mo-vie/2026-04-02_egger_sync.md` (voice: gold)

**OUT**
- Writer side (any Step 5/6 write logic) — separate tickets
- Caching — Step 5 reads per-call; if profiling shows hot-path cost, add caching in a follow-up
- Frontmatter schema validation — just look for `voice: gold`; full Pydantic is Step 6 territory

### CHANDA pre-push

- **Q1 Loop Test:** This helper IS Leg 1 (Gold-read-by-matter). Creating it is the enabler of Inv 1 compliance in Step 5. Cite in PR body — this is LOOP-CRITICAL infra, treat with the gravity CHANDA §2 gives it.
- **Q2 Wish Test:** pure wish (Leg 1 pattern realization). Pass.
- **Inv 1:** zero-Gold → empty string (tested explicitly).

### Branch + PR

- Branch: `loop-gold-reader-1`
- Base: `main`
- PR title: `LOOP-GOLD-READER-1: kbl/loop.py load_gold_context_by_matter`
- Target PR: #9

### Reviewer

B2.

### Timeline

~30-45 min.

### Dispatch back

> B1 LOOP-GOLD-READER-1 shipped — PR #9 open, branch `loop-gold-reader-1`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

---

*Posted 2026-04-18 by AI Head. B2 reviewing PR #8. B3 applying STEP5-OPUS S1 rename.*
