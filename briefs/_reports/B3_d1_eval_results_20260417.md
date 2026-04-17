# B3 — D1 Pre-Shadow Eval Results

**Session:** 2026-04-17
**Author:** Code Brisen 3 (first B3 task)
**Task brief:** `briefs/_tasks/CODE_3_PENDING.md`

---

## TL;DR

**D1 eval: Gemma 70% vedana, 100% JSON, 30% matter. FAIL D1 thresholds.**

Qwen 2.5 14B (comparison): 66% vedana / 100% JSON / 36% matter — also FAIL.

Both models clear JSON validity (100%) but miss vedana by ~20 pp and primary matter by ~50 pp. Neither clears the bar for D1 ratification. Root causes are primarily **schema gaps in the eval prompt** (covered in §4), not raw model capability.

---

## 1. Gemma 4 8B — the D1 target

| Metric | Result | Threshold | Pass? |
|---|---|---|---|
| JSON validity | 100.0% | 100% | ✅ |
| Vedana overall | 70.0% | ≥ 90% | ❌ |
| Primary matter | 30.0% | ≥ 80% | ❌ |
| Score bucket | 82.0% | (info) | — |

**Per-source vedana:**

| Source | n | Vedana | Matter | JSON | Bucket | Pass ≥85%? |
|---|---|---|---|---|---|---|
| email | 25 | 64% | 32% | 100% | 72% | ❌ |
| meeting | 10 | 70% | 30% | 100% | 90% | ❌ |
| whatsapp | 15 | 80% | 27% | 100% | 93% | ❌ (close) |

All three source-bands fail the 85% per-source vedana threshold, email worst.

---

## 2. Qwen 2.5 14B — comparison

| Metric | Qwen | Gemma | Winner |
|---|---|---|---|
| JSON validity | 100% | 100% | tie |
| Vedana overall | 66.0% | 70.0% | Gemma |
| Primary matter | 36.0% | 30.0% | Qwen |
| Score bucket | 82.0% | 82.0% | tie |

**Per-source vedana (Qwen):** email 68%, meeting 60%, whatsapp 67%. Qwen loses on meeting (60% vs Gemma 70%), wins on email (68% vs 64%).

**Qwen does not rescue D1.** Neither model passes; Gemma is marginally better overall. The eval doesn't support swapping in Qwen as a Gemma replacement.

---

## 3. Signals where BOTH models failed

**Vedana — 13 / 50 signals both models missed:**

| Signal ID | Expected | Gemma | Qwen |
|---|---|---|---|
| email:1975e7d294e34a34 | routine | opportunity | opportunity |
| email:198bf7246fa5649b | routine | opportunity | opportunity |
| email:1999a3807914bdde | routine | opportunity | opportunity |
| email:19c6b2a3b05880ca | **threat** | routine | routine |
| email:19d3d94fc290db9c | **threat** | opportunity | opportunity |
| email:19d77f4c155b7b86 | opportunity | routine | routine |
| email:8370465D…brisengroup | opportunity | routine | routine |
| meeting:01KES6JZPVPQKXYB3WP9H7NDN2 | opportunity | threat | threat |
| meeting:01KFJGBHN7PFVQKEV1MSXVYMB1 | **threat** | opportunity | opportunity |
| meeting:01KJB66KQWSFF5TP65QD1QHD8P | routine | threat | threat |
| whatsapp:…120363419098188402 | routine | threat | threat |
| whatsapp:…127783967711391 | routine | threat | threat |
| whatsapp:…246076007297228 | **threat** | opportunity | opportunity |

**Pattern:** both models struggle with the Director-taught vedana rule — **opportunity is reserved for NEW strategic gains**; defensive moves within an existing threat arc are threat, not opportunity. Several signals classified by both models as `opportunity` (seeing a positive-sounding business mention) were actually `threat` under the Director rule because they sit inside the HAG / Cupial dispute arcs. Conversely, three signals the Director called opportunity were downgraded to routine by both models — models didn't recognize forward-looking moves (Roundshield deal, Wertheimer SFO pitch, etc.).

**Primary matter — 29 / 50 signals both models missed:**

Top miss categories:
- **`null` expected (9 cases):** models hallucinated a matter (`brisen-lp`, `ao`, `mo-vie`, even `hospitality` / `investment` / `legal disputes`) when Director said no matter
- **`hagenauer-rg7` expected (9 cases):** both models routinely predicted `brisen-lp` or `mo-vie` for HAG dispute emails — models conflate the contractor dispute with the capital structure or hotel asset
- **New slugs (11 cases):** `franck-muller`, `kitzbuhel-six-senses`, `kitz-kempinski`, `steininger`, `wertheimer`, `baker-internal`, `personal`, `lilienmat`, `constantinos` — models don't know these slugs exist

Models routinely return non-slug strings (`"none"`, `"hospitality"`, `"investment"`, `"legal disputes"`) — they're filling in English categories, not picking from an enumerated set.

---

## 4. Root causes — flag for KBL-B tuning

### 4a. Prompt-schema gap (the dominant matter-accuracy driver)

`scripts/run_kbl_eval.py` line 55:
> *"You are a triage agent for a 28-matter business operation… Classify this signal… **matter: which business matter (e.g. hagenauer-rg7, cupial, mo-vie, ao, brisen-lp, mrci)**"*

The prompt **lists only 6 matters as examples** and says "28-matter" but gives no enumeration. Meanwhile the ground-truth labels reference **19 distinct slugs** (many added by Director during this labeling session). Models can't predict slugs they've never been shown. This alone likely explains most of the 70% matter-miss rate.

**Recommended KBL-B fix:** enumerate the full canonical slug set in the prompt, either inline or as a system-prompt preamble. Emit an explicit instruction that `null` / `None` is a valid output when no matter applies. Consider few-shot examples.

### 4b. Vedana rule is non-obvious from the enum alone

The Director's rule is that **opportunity = forward-looking strategic gains only**; defensive wins / rectifications stay in the threat arc. The enum `opportunity | threat | routine` doesn't telegraph this distinction — models default to "positive-sounding → opportunity / negative-sounding → threat / neutral → routine," which collapses the threat-arc-recovery case into opportunity. Hard to learn zero-shot.

**Recommended KBL-B fix:** add explicit vedana semantics to the prompt. E.g.:
> - `opportunity`: NEW strategic gain (new ventures, new deals, new capital, new relationships). Not "anything positive."
> - `threat`: any adverse event OR any move inside an ongoing threat arc, **including defensive rectifications, recoveries, counter-moves, and settled wins inside a dispute**.
> - `routine`: neither — operational, informational, transactional, housekeeping.

### 4c. Eval set itself is an edge-case-rich sample

- 7 near-duplicate Baker self-analyses of the same Ofenheimer email (WA signals 42/43/45/47/49) — tests deduplication, not fundamentally different classification.
- 1 completely garbled Fireflies transcript (meeting idx 29) — tests model resistance to hallucinating structure from noise.
- Several signals with essentially no content (short WA one-liners, image OCR) — tests the "don't over-classify" instinct.

These are good stress tests, but they drag the vedana average down in ways a cleaner dataset wouldn't.

---

## 5. Side-effects of this session (worth reading)

During labeling Director added **8 new canonical matter slugs** (`aukera`, `kitzbuhel-six-senses`, `kitz-kempinski`, `steininger`, `wertheimer` split from `brisen-lp`, `balducci`, `constantinos`, `franck-muller`). This validates the architectural concern Director raised mid-session: **"Slugs cannot be canonical. They are a living body."** There's a spawned task for AI Head on the slug-registry design; this eval run is further evidence that a drifted task-brief-vs-validator-vs-prompt slug set is a real operational problem, not a theoretical one.

Also discovered during this task: task-file says to use the string `"null"` for empty primary_matter, but the validator requires JSON `null` (Python `None`). Fixed in commit `f4ea322`; task file should be corrected when the brief is revised.

---

## 6. Artifacts + commit SHAs

| Artifact | Path | Commit |
|---|---|---|
| Labeled eval set (50 signals) | `outputs/kbl_eval_set_20260417_labeled.jsonl` | *(added with this report)* |
| Eval results JSON | `outputs/kbl_eval_results_20260417.json` | *(added with this report)* |
| This report | `briefs/_reports/B3_d1_eval_results_20260417.md` | *(added with this report)* |

**B3 session commits (chronological):**

- `1f3d467` — fix: `build_eval_seed.py` — `email_messages` PK is `message_id` not `id`
- `76f3412` — fix: add missing column aliases on 5 CTEs in `build_eval_seed.py`
- `2cdfa09` — feat: extend matter slug set + align labeler with validator (added `aukera`)
- `ebee360` — feat: add `kitzbuhel-six-senses` slug
- `ad50738` — feat: add `steininger` slug
- `3ad7508` — feat: add `kitz-kempinski` slug
- `4bc37b6` — feat: add `wertheimer` + `balducci` slugs; unalias wertheimer from brisen-lp
- `6c1a1b6` — feat: add `constantinos` slug
- `264079b` — feat: add `franck-muller` slug
- `f4ea322` — fix: store JSON null (not `"null"` string) for empty primary_matter

Total: 10 commits across three categories — bug fixes on the seed script (2), slug-registry expansion (7), validator-alignment fix (1).

---

## 7. Recommendation to Director

**D1 ratification should NOT proceed on this eval.** Both Gemma and Qwen fail both vedana and matter thresholds. Before re-evaluating:

1. **Patch the eval prompt** to enumerate all canonical slugs + explain the Director vedana rule (§4a + §4b). This is likely an hour of Code work and should dramatically lift the matter accuracy.
2. **Ratify the slug registry** (§5 + the spawned AI Head task) so the prompt, validator, guesser, and labeler share one source of truth.
3. **Re-run the eval** against the same labeled set with the fixed prompt. If Gemma now clears 90%/80%, D1 can be ratified. If not, the capability gap is real and KBL-B retry (prompt engineering + few-shot) or model swap are on the table.

If the Director wants a faster path: a smaller focused eval (20 signals, no near-duplicates, explicit slug enum in prompt) would give a cleaner read on whether Gemma is fundamentally capable, rather than fighting schema drift as we did here.
