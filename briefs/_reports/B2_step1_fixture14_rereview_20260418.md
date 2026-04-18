# Step 1 + Fixture #14 Re-Review (B2 — third cycle on Step 1)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task A
**Files at commit `6c255d1`:**
- `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` — Step 1 third cycle (S1 cross-matter elevation, S2 PR #6 API alignment)
- `briefs/_drafts/KBL_B_TEST_FIXTURES.md` — Fixture #14 added (cross-matter elevation test)
**Diffs scoped:** `773f8c5..6c255d1` for Step 1 prompt; `f47e9a5..6c255d1` for fixtures
**Cross-referenced:** PR #6 `kbl/loop.py` (merged); my prior CHANDA-fold review (S1 + S2 verdict)
**Date:** 2026-04-18
**Time:** ~20 min

---

## 1. Verdict

**REDIRECT — 1 should-fix, narrow surface (env-var name typo). All other items applied per intent.**

S1 (cross-matter elevation) and S2 (PR #6 API alignment) both applied correctly with one isolated docstring typo: §1.4's `load_recent_feedback` docstring cites `KBL_LEDGER_DEFAULT_LIMIT` as the env-var; PR #6 ships `KBL_STEP1_LEDGER_LIMIT`. Three-line fix.

Fixture #14 is correctly scoped, single-shot-asserted, and pre-conditions are clean. Pattern accepted (new fixture vs expanding #11) per my Part 2 N1 recommendation.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

### S1-rereview — Env-var name mismatch in §1.4 docstring

**Location:** `KBL_B_STEP1_TRIAGE_PROMPT.md:188` (inside `load_recent_feedback` docstring).

```
the env-var default (KBL_LEDGER_DEFAULT_LIMIT, set to 20 in
production env; explicit limit=20 from Step 1 makes it deterministic
regardless of env).
```

PR #6 `kbl/loop.py` ships **`KBL_STEP1_LEDGER_LIMIT`** (verified via `grep` — 3 occurrences in production code: line 22 module docstring, line 36 constant, line 134 function docstring). B3's §1.4 introduces the wrong name.

**Why this matters.** §1.4 explicitly claims to be the verbatim PR #6 surface ("These signatures match the merged PR #6 verbatim"). An operator reading §1.4 to set the env var on Mac Mini will set `KBL_LEDGER_DEFAULT_LIMIT=N`, the helper won't pick it up (silently falls back to default 20), and they'll waste time debugging why their override isn't working.

**Fix.** One-line replace in §1.4 docstring: `KBL_LEDGER_DEFAULT_LIMIT` → `KBL_STEP1_LEDGER_LIMIT`. Trivial.

This is the only mismatch I found. The other three S2 items match PR #6 exactly:
- `render_ledger(rows)` (no `_block` suffix) ✓
- `load_recent_feedback(conn, limit: int | None = None)` ✓
- `build_step1_prompt(signal_text: str, conn) -> str` (caller owns conn) ✓
- Empty-content guard `if not content:` covers both `None` and `""` ✓

---

## 4. Nice-to-have

### N1 — "Elevation wins on +0.05" wording could be tighter

**Location:** §1.2 "How to use `hot.md`" mixed-elevation/suppression rule.

> *"If a signal qualifies for BOTH elevation AND suppression (one matter on ACTIVE, another on FROZEN), **net them**: elevation wins on +0.05 (0.15 − 0.10), but cite both in `summary` so the steering is auditable."*

The parenthetical `(0.15 − 0.10)` makes the math explicit, but "elevation wins on +0.05" reads slightly ambiguously — could parse as either (a) net is +0.05, or (b) elevation overrides and suppression is ignored. The model is likely to pick (a) because of the parenthetical, but a 5-second wording tighten would foreclose ambiguity:

> *"net them deterministically: +0.15 − 0.10 = **+0.05 net** (still net elevation; cite BOTH the ACTIVE and FROZEN matches in `summary` so the steering chain is auditable)."*

Cosmetic. Defer if you want.

### N2 — Mixed-state parametric variant of #14 deserves its own fixture eventually

§"Variant case worth noting" notes that pytest can parameterize hot.md state across:
1. only-related-active (the canonical #14 case)
2. only-primary-active (already covered by #11)
3. mixed-frozen-and-active (the +0.05 net case)

Case 3 is currently a "property" of #14 with no separate fixture. Pytest parameterization works for v1, but the mixed case is the most fragile (off-by-one risk in the elevation/suppression arithmetic, single-shot rule applied per match-class rather than per signal, etc.). I'd surface this as Fixture #15 in a future amendment when the §10 implementer wires the parametric tests.

Not blocking. B3's §10-future-work parking is acceptable.

### N3 — Fixture #14 commit-SHA placeholder

§"Paths exercised" of Fixture #14 says: *"Confirms STEP1-AMEND-S1 (commit `<TBD>`) widened-match rule fires correctly."*

The commit SHA placeholder is `<TBD>`. The actual amend commit is `6c255d1` (this very commit). Replace `<TBD>` with `6c255d1` so the trace is complete. One-line edit.

---

## 5. S1 + S2 application audit

### S1 — Cross-matter elevation rule

| Where applied | Status |
|---|---|
| §1.2 "How to use `hot.md`" — ELEVATE rule (lines 126-130) | ✓ Widened to "primary_matter, OR related_matters, OR slug-mention in signal text" |
| §1.2 ELEVATE single-shot guard (line 130) | ✓ Explicit: "Apply the elevation **once per signal** even if multiple matches occur — do NOT stack a +0.15 per match" + worked counter-example |
| §1.2 SUPPRESS rule (line 131) | ✓ Same widened-match shape, single-shot guard |
| §1.2 Mixed elevation+suppression rule (line 132) | ✓ "net them: elevation wins on +0.05 (0.15 − 0.10), but cite both in summary" — see N1 wording flag |
| §6 OQ6 (line 416) | ✓ ~~Deferred~~ → **RESOLVED**, single-shot mitigation cited explicitly |
| §2.2 changes table (line 332) | ✓ STEP1-AMEND-S1 documented with rationale, OQ3 ratification cited |
| Fixture #14 cross-link | ✓ §1.2 + §6 + §2.2 all reference Fixture #14 in `KBL_B_TEST_FIXTURES.md` |

Applied per AI Head OQ3 resolution exactly. Single-shot mitigation addresses the original deferral rationale (over-elevation noise) cleanly.

### S2 — `kbl/loop.py` API alignment

| Item | PR #6 actual | Step 1 §1.1 / §1.4 | Match? |
|---|---|---|---|
| Function name (renderer) | `render_ledger` | `render_ledger` | ✓ |
| `load_recent_feedback` signature | `(conn, limit: Optional[int] = None)` | `(conn, limit: int \| None = None)` | ✓ functionally equivalent |
| `build_step1_prompt` signature | n/a (B3 owns) | `(signal_text: str, conn)` | ✓ correct caller-owns-conn pattern |
| Empty-content handling | `if not content:` (per PR #6 N1) | `hot_md_content if hot_md_content else "(...)"` | ✓ catches None AND "" |
| `LoopReadError` documented | yes (PR #6) | yes (§1.4 line 198) | ✓ |
| Env-var name | `KBL_STEP1_LEDGER_LIMIT` | `KBL_LEDGER_DEFAULT_LIMIT` (§1.4 line 188) | ✗ **see S1-rereview should-fix above** |

5/6 alignment items correct. The env-var name is the only miss.

### Comments on §1.1 builder code quality

The new builder code (lines 25-58) is clean:
- `conn` parameter docstring explicitly says "caller owns the connection lifecycle"
- Inv 3 comments are explicit — "no caching", "fresh read per signal", "the read MUST occur on every call"
- Empty-content fallback is split into intermediate vars (`hot_md_content`, `rendered`) which makes the `if not X` guard readable instead of inline `or` expressions
- `LoopReadError` not caught — if PR #6 raises, Step 1 fails loud (caller decides retry posture). Correct CHANDA Inv 3 posture: ledger unreachable should fail Step 1, not silently process without ledger steering. (B3's §1.4 docstring says "Step 1 should treat as availability fallback: log WARN, render '(ledger unreachable)', proceed without ledger steering" — implying caller handles. Current builder doesn't catch — flagged for B1 impl decision.)

The "what does Step 1 do on `LoopReadError`?" question is implicit. The §1.4 docstring suggests one path (continue without ledger), the §1.1 builder neither catches nor documents the exception path. Not a blocker — B1 impl will need to decide. Flag this as a sub-question for the LAYER0-IMPL-style follow-up dispatch on Step 1 wiring.

---

## 6. Fixture #14 audit

### 6.1 Pre-condition correctness

```
- ACTIVE: hagenauer-rg7 — drawdown sequence pre-Schlussabrechnung (this week)
- ACTIVE: cupial — Hassa response window (Apr 22 deadline)
```

`wertheimer` NOT on hot.md. ✓ matches the cross-matter scenario exactly: primary out, related (`hagenauer-rg7`) in.

The signal (Wertheimer SFO approach with `related_matters=["hagenauer-rg7"]`) is reused from Fixture #5 — no new corpus material needed. Same pre-condition mechanism as #11/#12/#13 (synthetic hot.md content + pytest fixture wipe/restore).

### 6.2 Hard-assert loop compliance

| Assertion | Verdict |
|---|---|
| `hot_md_loaded` = TRUE | ✓ standard Inv 3 read assertion |
| `feedback_ledger_queried` = TRUE | ✓ standard Inv 3 |
| `cross_matter_elevation_fired` = TRUE | ✓ **the OQ3-resolution assertion** — proves the widened rule fires when primary is OUT but related is IN |
| `elevation_count` = 1 | ✓ **single-shot guard** — the over-elevation-noise mitigation B3 originally feared. Pytest fails if `elevation_count >= 2`. |
| `triage_score_observed` between 88 and 100 | ✓ band-check (base 75-80 + 15 elevation = 90-95, with 100 cap). Critical behavioral assertion — proves model READ AND USED the elevation. |
| `triage_score_summary_cites_cross_matter` = TRUE | ✓ steering-chain auditability |
| `gold_context_by_matter_loaded` = TRUE for wertheimer (Phase 2) | ✓ reuses #13's zero-Gold case |

All 7 assertions are behavior-tied (not just data-presence). Same shape as #11/#12 — `assert the read INFLUENCED the output`.

### 6.3 Variant case parking

§"Variant case worth noting" says the parametric matrix (only-related-active / only-primary-active / mixed) can be done via pytest parameterization. ✓ acceptable for v1. Mixed case (the +0.05 net case from N1) is the highest-risk arithmetic — flagged as N2 above for future fixture #15 if Phase 1 burn-in shows arithmetic bugs.

### 6.4 Path-coverage matrix + budget updates

| §0 path-coverage matrix | ✓ Added "Leg 3 cross-matter elevation" row → #14 |
| §3 budget table | ✓ Synthetic 4→5, WhatsApp 4→5, source distribution still representative |
| §2 harness needs | ✓ Reuses #5 signal + #11 hot.md fixture mechanism — no new harness needed |
| §"these 14 fixtures" count | ✓ Updated from "13" to "14" |

All metadata updated consistently. ✓

---

## 7. Confirmations — Part 2 of prior review accepted

My CHANDA-fold review Part 2 N1 said:
> *"If/when Part 1 S1 lands (cross-matter elevation rule), a matching fixture is needed. Two options: (a) Add Fixture #14 ... or (b) Expand Fixture #11 ... Either is fine."*

B3 went with option (a) — new Fixture #14 — and explicitly justified the choice in the "B2's recommendation accepted" section:
1. #11 already pins primary-match elevation; expanding would create a multi-purpose fixture
2. Named fixture target makes the test discoverable
3. Reuses Fixture #5's signal — no new corpus material

All three reasons are sound. ✓ Agree with the choice.

---

## 8. Summary

- **Verdict:** REDIRECT (1 should-fix, narrow surface).
- **Blockers:** 0.
- **Should-fix:** 1 (env-var name `KBL_LEDGER_DEFAULT_LIMIT` → `KBL_STEP1_LEDGER_LIMIT` in §1.4 docstring; 1-line fix).
- **Nice-to-have:** 3 (mixed-net wording tighten; mixed-state parametric fixture; Fixture #14 commit-SHA placeholder).
- **S1 cross-matter elevation:** ✓ applied per AI Head OQ3, single-shot guard explicit, FROZEN mirror, mixed-net documented.
- **S2 API alignment:** 5/6 items match PR #6 exactly; env-var name is the one miss.
- **§6 OQ6 flip:** ✓ DEFERRED → RESOLVED with single-shot mitigation cited.
- **Fixture #14:** ✓ pre-condition correct; 7 hard-assert loop-compliance rows including the critical `cross_matter_elevation_fired` + `elevation_count == 1` (single-shot guard).
- **Pattern accepted:** new fixture (not expanded #11) per Part 2 N1.

This is the third cycle on Step 1. The S1 + S2 amendments closed the two should-fix items from cycle 2 cleanly. The remaining S1-rereview (env-var typo) is a 1-line fix — not a fourth cycle, just a touch.

The amendment-log table at §10 of the Step 0 file (which I praised in re-review) doesn't yet exist on the Step 1 file. Recommend adopting the same convention there for the next amend.

---

*Re-reviewed 2026-04-18 by Code Brisen #2. Files @ `6c255d1`. Cross-referenced against `kbl/loop.py` PR #6 (merged) for env-var name + signature verification. No code changes; design re-review only.*
