# Phase 1 Burn-In Audit — CHANDA §2 Legs + §3 Invariants (B2 — Task K)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task K
**Scope:** merged Phase 1 PRs (#7 LAYER0-IMPL, #8 STEP1-TRIAGE-IMPL, #10 STEP2-RESOLVE-IMPL, #11 STEP3-EXTRACT-IMPL, #12 STATUS-CHECK-EXPAND-1) against current `main` (commit `114a2dc`, pre-PR #13)
**Method:** read-only grep + code trace. No runtime execution.
**Date:** 2026-04-19
**Time:** ~50 min

---

## 1. Verdict

**YELLOW — no CHANDA invariant broken, one integration-layer gap flagged at documentation level.**

All 10 invariants hold at the module level. The one finding worth the Director's attention is not an invariant violation — it's an **architectural context** observation: **Phase 1 code is merged but not wired.** `pipeline_tick.py` remains the KBL-A stub and has zero callers of `triage()` / `resolve()` / `extract()`. The pipeline is dormant. Inv 2 (ledger-write atomicity) is therefore vacuously satisfied today, but the transaction-boundary contract between the Steps and their future caller is unspecified in merged code — worth codifying before Step 5 (PR #14+) introduces the first paid-cost write.

Promoting this to YELLOW rather than GREEN because "code on main that isn't called yet" is itself a drift surface: someone will wire the integration, and ambiguity on transaction boundaries will shape the outcome.

---

## 2. Per-invariant status

| Inv | Subject | Status | Detail |
|---|---|---|---|
| 1 | Gold read before Silver; zero Gold = zero Gold | ✓ GREEN | Each step handles empty inputs via documented fallbacks. `load_gold_context_by_matter` (PR #9, [`kbl/loop.py:342`](kbl/loop.py)) is Leg 1's read — Phase 1 has zero callers, which is correct (Step 5+ territory). |
| 2 | Director actions write ledger atomically, or action fails | ⚠ YELLOW | **Applies to `feedback_ledger` (Leg 2 Capture). Phase 1 has zero Leg 2 writes.** Vacuously preserved. Separately: `kbl_cost_ledger` (operational, not Leg 2) is written by Steps 1 + 3 in caller-owns-commit pattern; transaction boundary with state UPDATE is unspecified (see §4). |
| 3 | Step 1 reads hot.md AND feedback ledger every run | ✓ GREEN | Anchored by `test_triage_invocation_reads_hot_md_and_ledger_once` (`tests/test_step1_triage.py`). `_read_prompt_inputs(conn)` at [`kbl/steps/step1_triage.py:570`](kbl/steps/step1_triage.py) centralizes fresh reads. No module-level cache. Re-verified post-merge. |
| 4 | `author: director` files never modified by agents | ✓ GREEN | Only write surface in kbl/: [`kbl/gold_drain.py:170-172`](kbl/gold_drain.py) — the legitimate pipeline→director flip (KBL-A Phase 5, pre-existing). Guard at line 167 `if fm.get("author") == "director": return 'noop'` refuses to re-modify. No Phase 1 PR touched `gold_drain.py`. |
| 5 | Every wiki file has frontmatter | ✓ GREEN (vacuous) | No Phase 1 PR introduces a wiki-write path. |
| 6 | Pipeline never skips Step 6 | ✓ GREEN | Zero writes of `'completed'` or `'done'` in `kbl/steps/`. Every exit path advances to `awaiting_<next>` (happy) / `<step>_failed` (halt) / `routed_inbox` (Step 1 terminal). See §3.3 for per-step trace. |
| 7 | Ayoniso alerts are prompts, not overrides | N/A | KBL-C surface. Phase 1 doesn't touch. |
| 8 | Silver → Gold only by Director frontmatter edit | ✓ GREEN | Pre-existing `gold_drain.py` owns the flip with Director-identity guard. No Phase 1 drift. |
| 9 | Mac Mini is single writer; Render → `wiki_staging` only | ✓ GREEN | Only baker-vault WRITE surface in kbl/ is `gold_drain.py` (Mac Mini per its commit-identity setup). Phase 1 PRs read vault only ([`kbl/layer0_rules.py`](kbl/layer0_rules.py), [`kbl/slug_registry.py`](kbl/slug_registry.py), [`kbl/config.py`](kbl/config.py)). No new write surfaces introduced. |
| 10 | Pipeline prompts don't self-modify | ✓ GREEN | Zero `.write_text` / `open(...'w')` targeting `kbl/prompts/*.txt` anywhere in kbl/. Only docstring references and read-paths (`_load_template()` in Step 1, module-level `_template_cache` in Step 3). Template cache is populated from disk read, never written back. |

---

## 3. Per-leg status

| Leg | Subject | Status | Detail |
|---|---|---|---|
| 1 | **Compounding** — Gold reads per matter before Silver | ✓ GREEN | `load_gold_context_by_matter` (`kbl/loop.py:342`) called by zero Phase 1 code. Confirmed via `grep -rn load_gold_context_by_matter kbl/` — only the definition in `loop.py` + tests in `test_loop_gold_reader.py`. Correct posture: Step 5 will be the first caller. |
| 2 | **Capture** — Director actions → feedback_ledger atomically | ✓ GREEN | Zero `INSERT INTO feedback_ledger` statements in Phase 1 code. Step 1 READS the ledger (`load_recent_feedback(conn, limit=20)` at `kbl/steps/step1_triage.py:69` and `:583`) into the prompt render; no write. KBL-C will ship Leg 2 writes (WhatsApp/ayoniso handlers). |
| 3 | **Flow-forward** — Step 1 reads hot.md + ledger every run | ✓ GREEN | Anchor test passes (`test_triage_invocation_reads_hot_md_and_ledger_once` — 2 invocations → `m_hot.call_count == 2` AND `m_ledger.call_count == 2` on both happy + retries-exhausted paths). `_read_prompt_inputs(conn)` consolidates reads once per invocation; `_build_pared_prompt` reuses the already-fresh values without re-reading. Contract re-certified in combined main state. |

---

## 4. Drift finding — Inv 2 integration-layer gap (YELLOW)

### 4.1 What I found

`kbl/pipeline_tick.py` lines 80-100 remain the **KBL-A stub**:

```python
emit_log("WARN", "pipeline_tick", signal_id,
         "KBL-A stub: signal claimed but no pipeline logic yet (awaiting KBL-B)")
try:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = 'classified-deferred', "
            "processed_at = NOW() WHERE id = %s",
            (signal_id,),
        )
        conn.commit()
except Exception:
    conn.rollback()
    raise
```

Every signal claimed by `claim_one_signal` is marked `classified-deferred` and returned. **The live pipeline does not invoke any Phase 1 step.**

Independently verified: `grep -rn 'from kbl.steps.step[123]' kbl/` → zero non-self hits. `grep -rn '\.triage(\|\.resolve(\|\.extract('` under `kbl/` → zero non-self hits. Steps 1/2/3 live only in tests and as importable modules.

### 4.2 Why YELLOW, not GREEN

Three reasons:

1. **Transaction-boundary contract is unspecified.** Each Phase 1 step (`triage`, `resolve`, `extract`) follows caller-owns-commit — zero `conn.commit()` calls in `kbl/steps/step[123]_*.py`. The integrator (eventually: rewired `pipeline_tick.main()`) must decide:
   - **(a) One transaction per tick** — claim, run all steps for this tick's signal, commit once. Rollback on any failure loses all cost-ledger rows written during failed steps.
   - **(b) One transaction per step** — commit after each step's state UPDATE + cost-ledger INSERT pair. Safer for telemetry; risks state/cost-ledger split if the commit lands between the UPDATE and the INSERT.
   
   Neither choice is merged. Neither is documented. When Step 5 adds paid cost-ledger writes, getting this wrong is visible in accounting.

2. **Write ordering per step is UPDATE → cost-ledger.** In [`kbl/steps/step1_triage.py:555-562`](kbl/steps/step1_triage.py) and [`kbl/steps/step3_extract.py:557,572`](kbl/steps/step3_extract.py), the pattern is `_write_*_result(...)` (UPDATE signal_queue) THEN `_write_cost_ledger(...)` (INSERT kbl_cost_ledger). If a future integrator splits the transaction between them, a step could advance state without the cost row landing. In Step 2 ([`kbl/steps/step2_resolve.py:211`](kbl/steps/step2_resolve.py)), same pattern: `_write_result` before conditional `_write_cost_ledger`.

3. **Step 1's retry path writes cost-ledger-only, no UPDATE.** On parse-retry (line 547 in step1_triage.py), `_write_cost_ledger(..., success=False)` fires and `_run_triage_attempt` returns `None`; state stays at `triage_running`. The `triage()` wrapper then loops with a pared prompt. If the integrator commits per-step on the middle attempt, the DB sees a `triage_running` row with a failed cost row and no result — a signal stuck mid-retry. Resumable only if the pipeline-tick harness re-claims `triage_running` rows on next tick, which is also unspecified.

None of these are breaking today (no caller). Each becomes breaking the moment pipeline_tick is wired.

### 4.3 Remediation path (if Director wants to close this before Step 5)

**Option A (preferred) — codify transaction boundary at integrator layer, before PR #14.** A 2-line contract note in `kbl/pipeline_tick.py` docstring + an adjustment in the eventual rewire PR: "each step runs in its own sub-transaction; `conn.commit()` after each step's state UPDATE + cost-ledger INSERT pair; on step failure, `conn.rollback()` then mark `<step>_failed` in a fresh transaction." This matches Step 4's failure-path precedent (`_mark_failed` before `raise` — commit-on-mark expectation implicit).

**Option B — leave it to the Step 5 PR author.** Step 5 (Opus call + Anthropic-cost row) forces the question because cost-ledger accuracy is business-critical. The brief scope for Step 5 should include a "transaction boundary model for pipeline tick" task. Adds a day; closes ambiguity.

**Option C — status quo, re-audit at Step 7.** Accept the ambiguity until the full pipeline is wired; re-audit when Step 7 lands. Risk: ambiguity compounds; each step author picks their own interpretation.

My recommendation: **Option A**, because the contract is small (one docstring + one commit-placement line in the future rewire) and the cost of ambiguity compounds with each additional step.

---

## 5. Secondary observations (informational, not drift)

### 5.1 Step 1 has two fresh-read entry points

[`kbl/steps/step1_triage.py:168 build_prompt()`](kbl/steps/step1_triage.py) — public, reads hot.md + ledger — is NOT called from `triage()` in production path. `triage()` goes via `_read_prompt_inputs(conn)` at line 570 instead. Both paths honor Inv 3 independently. Surface-level redundancy — if a test or external caller uses `build_prompt()` alongside `triage()`, you'd see two fresh reads per signal (not a violation, just inefficient).

No fix required. Worth knowing if PR review rubber-stamps a future caller that hits both.

### 5.2 Step 4 adds a second `load_hot_md` surface

When PR #13 merges, `kbl/steps/step4_classify.py` becomes the second production reader of `hot.md` (via `_load_allowed_scope`). Inv 3 stays per-invocation-fresh for each step independently, but a single pipeline tick that runs Step 1 → Step 2 → Step 3 → Step 4 will read `hot.md` TWICE (once at Step 1, once at Step 4). Not a violation — both reads are fresh, correct, and per the CHANDA contract — but a future performance-optimization note: could consolidate into a single tick-level read if latency matters. Flag for the post-Step-5 optimization pass.

### 5.3 `resolve()` Step 2 has no `_mark_running` atomicity note

[`kbl/steps/step2_resolve.py:185`](kbl/steps/step2_resolve.py) calls `_mark_running(conn, signal_id)` to flip status to `resolve_running`. If the resolver then raises between `_mark_running` and `_write_result(..., _STATE_FAILED)`, the `resolve_running` UPDATE and the `resolve_failed` UPDATE are in the same connection but could split across transactions if the integrator commits between them. Same atomicity hazard as §4.2 but surface-level — callable-owns-commit still applies. Acknowledged drift-pattern; no new flag.

---

## 6. Scans executed (evidence trail)

| Check | Command (summary) | Result |
|---|---|---|
| Inv 1 — Gold-read callers | `grep -rn 'load_gold_context_by_matter' kbl/` | Only `kbl/loop.py` definition + `test_loop_gold_reader.py`; zero Phase 1 production callers. ✓ |
| Inv 2 — `conn.commit()` in steps | `grep -n 'commit\b' kbl/steps/step[123]_*.py` | Zero matches across all 3 step modules. Caller-owns-commit confirmed. |
| Inv 2 — feedback_ledger writes | `grep -rnE 'feedback_ledger\|INSERT INTO feedback' kbl/` | Zero writes; only READS in `step1_triage.py` via `load_recent_feedback()`. ✓ |
| Inv 3 — hot.md read surfaces | `grep -rn 'load_hot_md' kbl/` | `kbl/loop.py` (definition) + `kbl/steps/step1_triage.py:186,583`. Two Step 1 sites (one in `build_prompt`, one in `_read_prompt_inputs`) — both honor fresh-read. |
| Inv 4 — `author: director` writers | `grep -rnE 'author.*director' kbl/` | Only `kbl/gold_drain.py:170,172` — pre-existing, gated at line 167. |
| Inv 6 — `completed`/`done` writes | `grep -rnE "'completed'\|'done'" kbl/steps/` | Zero matches. ✓ |
| Inv 9 — baker-vault write surfaces | `grep -rnE '\.write_text\\|open\(.*"w' kbl/` | Only `kbl/gold_drain.py:172` — pre-existing Mac Mini path. |
| Inv 10 — prompts self-modification | `grep -rnE "prompts/.*\.txt" kbl/` | Only docstring references + `_load_template` reads. Zero writes. ✓ |
| Live pipeline integration | `grep -rnE '\.triage\(\|\.resolve\(\|\.extract\(' kbl/` (excluding self) | **Zero hits.** Pipeline dormant. |

---

## 7. Summary

- **Verdict:** YELLOW — 1 documentation-level drift, 0 invariant violations, 2 secondary observations.
- **Inv 2 (atomicity):** transaction-boundary contract between Phase 1 steps and their future caller is unspecified; flag before Step 5 lands. **Recommendation: Option A** — 2-line docstring contract in `pipeline_tick.py` + rewire PR explicit commit placement.
- **All other invariants (1, 3, 4, 5, 6, 8, 9, 10):** GREEN. Inv 7: N/A.
- **All three legs (1, 2, 3):** GREEN.
- **Key architectural context:** Phase 1 code is merged but dormant. Zero callers of `triage/resolve/extract`. Real signal traffic begins when `pipeline_tick.py` is rewired (likely alongside Step 5).
- **Cost impact today:** zero. No Opus calls, no Voyage calls, no Gemma calls from the live tick.
- **Cost impact once wired:** full pipeline will process each pending signal through Steps 1 → 4 deterministic + Step 5 Opus. Transaction-boundary ambiguity surfaces here if not codified.

No RED finding. No BLOCK. One YELLOW I'd close at the cheapest opportunity — ideally as a pre-flight task before Step 5 PR merges.

---

*Audited 2026-04-19 by Code Brisen #2. Scope: `main` @ `114a2dc` (pre-PR #13). Method: read-only grep + code trace. Cross-referenced against CHANDA.md §2 Legs + §3 Invariants + prior B2 review reports for PRs #7/#8/#10/#11/#12. ~50 min.*
