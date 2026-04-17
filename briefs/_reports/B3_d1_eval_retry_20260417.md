# B3 — D1 Pre-Shadow Eval RETRY Results

**Session:** 2026-04-17
**Author:** Code Brisen 3 (retry run after prompt patch)
**Previous report:** `briefs/_reports/B3_d1_eval_results_20260417.md` (FAIL — root cause: prompt schema gaps)
**Handover that scoped this retry:** `briefs/_handovers/B3_20260417.md`
**Scope:** re-run eval against ground-truth labels with improved prompt; **do NOT re-label**.

---

## TL;DR

**Gemma 86% vedana / 100% JSON / 34% matter — FAIL D1 thresholds.**
Qwen 80% / 100% / 40% — also FAIL.

Prompt patch produced a **large vedana lift** (Gemma +16pp, Qwen +14pp) confirming the vedana rule was the right fix. **Matter accuracy barely moved** (+4pp both models) — root cause is different from vedana, and requires a separate intervention (see §4). D1 should not ratify on Gemma under current prompt; Qwen is worse, not a recovery option.

---

## 1. Headline comparison vs prior run

| Metric | Gemma prior | Gemma retry | Δ | Qwen prior | Qwen retry | Δ | Threshold |
|---|---|---|---|---|---|---|---|
| Vedana overall | 70% | **86%** | +16pp | 66% | **80%** | +14pp | ≥ 90% |
| Primary matter | 30% | **34%** | +4pp | 36% | **40%** | +4pp | ≥ 80% |
| JSON validity | 100% | 100% | 0 | 100% | 100% | 0 | 100% |

Vedana rule landed hard. Matter list expansion did not, for reasons explained in §4.

---

## 2. Gemma 4 8B — retry detail

| Metric | Result | Threshold | Pass? |
|---|---|---|---|
| JSON validity | 100.0% | 100% | ✅ |
| Vedana overall | 86.0% | ≥ 90% | ❌ (4pp short) |
| Primary matter | 34.0% | ≥ 80% | ❌ (46pp short) |
| Score bucket | 92.0% | (info) | — |

**Per-source:**

| Source | n | Vedana | Matter | JSON | Bucket | Vedana ≥85%? |
|---|---|---|---|---|---|---|
| email    | 25 | 84% | 44% | 100% | 88% | ❌ (1pp short) |
| meeting  | 10 | 90% | 40% | 100% | 100% | ✅ |
| whatsapp | 15 | 87% | 13% | 100% | 93% | ✅ |

Failures raised by acceptance check:
- `vedana_overall 86% < 90%`
- `primary_matter 34% < 80%`
- `vedana[email] 84% < 85%`

---

## 3. Qwen 2.5 14B — comparison

| Metric | Result | Threshold | Pass? |
|---|---|---|---|
| JSON validity | 100.0% | 100% | ✅ |
| Vedana overall | 80.0% | ≥ 90% | ❌ |
| Primary matter | 40.0% | ≥ 80% | ❌ |
| Score bucket | 88.0% | (info) | — |

**Per-source:**

| Source | n | Vedana | Matter | Vedana ≥85%? |
|---|---|---|---|---|
| email    | 25 | 76% | 28% | ❌ |
| meeting  | 10 | 80% | 60% | ❌ |
| whatsapp | 15 | 87% | 47% | ✅ |

Qwen is **worse than Gemma on vedana**, better on matter (40% vs 34%). The handover's fallback path ("retry with Qwen if Gemma fails") is closed — Qwen is not a drop-in rescue.

---

## 4. Root-cause analysis: why matter stuck at 34/40%

Matter misses categorized (Gemma / Qwen):

| Category | Gemma | Qwen | Notes |
|---|---|---|---|
| `hagenauer-rg7` → `brisen-lp` | **13** | 9 | Model hallucinates brisen-lp when signal mentions Brisen Group context (headers, signatures) |
| Scoring bug: label `None` vs model string `"null"`/`"none"` | 1 | 4 | Pure code bug in `normalize_matter()` — not model error |
| Other confusions (franck-muller→hagenauer, kitzbuhel-six-senses→steininger, etc.) | 19 | 17 | Model can't distinguish adjacent semantic matters |
| **Total misses** | 33 | 30 | |

**Dominant failure mode — `hagenauer-rg7` → `brisen-lp` (13/33 Gemma misses, 40% of all Gemma matter misses):**

The prompt now lists both slugs, but the model systematically picks `brisen-lp` for Hagenauer-related signals. Hypothesis: the signal content includes brisengroup.com email headers and "Brisen" references in the body, and the model anchors on the word "Brisen" rather than the matter semantics. The prompt does not tell the model what each slug MEANS — only that these slugs exist.

**This is the next intervention, and it's out of scope for this retry.** The fix is not a list expansion but a semantic glossary:

```
Matter slug meanings:
- hagenauer-rg7: the Hagenauer construction project in Baden bei Wien (RG7 / "Hagenauer").
  Signals about contractor disputes, Schlussabrechnung, handover, Cupial/Scorpios buyers,
  defect claims. Brisen Group is the OWNER — do not label brisen-lp just because a
  brisengroup.com header appears.
- brisen-lp: LP-level investor relations, fund strategy, limited partner communications.
  Only when the signal is specifically about the LP vehicle, not an underlying project.
- cupial: disputes with the Cupial family (Tops 4,5,6,18 at RG7). NOT hagenauer-rg7 —
  labeled separately because the legal matter is distinct.
...
```

Similar disambiguators needed for: franck-muller vs hagenauer-rg7, kitzbuhel-six-senses vs steininger, wertheimer vs brisen-lp.

**Scoring bug (smaller, code-level):**

`normalize_matter()` returns lowercase string; labels for "no matter" are Python `None`. Model output `"null"` or `"None"` does not compare equal to Python `None`. Fix: one line — treat `{"null", "none", ""}` as `None` in `normalize_matter()`. Costs 1 Gemma / 4 Qwen rows.

---

## 5. Per-signal signatures both models miss (hard rows — likely ambiguous ground truth)

Signals where **both Gemma and Qwen missed vedana**:
- `email:19c6b2a3b05880ca` (signal 9)
- `email:19d3d94fc290db9c` (signal 20)
- `email:8370465D-...@brisengroup.com` (signal 25)
- `meeting:01KES6JZPVPQKXYB3WP9H7NDN2` (signal 26)
- `whatsapp:false_447578191477@c.us_3A776C43...` (signal 38)
- `whatsapp:true_127783967711391@lid_3B50C45A...` (signal 41)

Signals where both missed matter (sample): `email:1964a26249bc2c0c`, `email:19cb01431b40fddf`, `email:19cb074316b37f87`, and the `whatsapp:true_246076007297228@lid_...` cluster (5/5 all missed).

These are candidates for Director's 5-minute review — if any are genuinely ambiguous, relabel or split from the eval set. If they're clear and models both fail, they're pure prompt-design signal for KBL-B.

---

## 6. Changes made in this retry

**File patched:** `scripts/run_kbl_eval.py`

**What changed:**
1. Replaced `STEP1_PROMPT` — added explicit allowed-slug list (18 slugs + null, union of handover enum + ground-truth labels file with labels-file spelling winning — e.g. `lilienmat` not `lilienmatt`)
2. Added vedana classification rules verbatim from B3 handover (opportunity = NEW strategic gains only; defensive wins stay in threat; routine = noise)

**What I did NOT change (stayed in scope):**
- `MATTER_ALIASES` dict — affects scoring, not prompt. Left as-is even though I suspect the `brisen-lp → ["brisen","wertheimer"]` alias is partially responsible for the hagenauer→brisen collapse being so visible in raw outputs.
- `normalize_matter()` null-handling bug — logged in §4, not fixed.
- Director labels — held as ground truth per handover rule.

---

## 7. Recommendation

1. **Do NOT ratify D1 on Gemma under current prompt.** Vedana 4pp short, matter 46pp short.
2. **Qwen is not a fallback** — worse on vedana.
3. **Next intervention:** semantic glossary in prompt (§4). Estimated effort: 30 min to draft glossary entries for the 15+ slugs with highest-confusion neighbors, 10 min to re-run eval. Expected lift on matter: +20-30pp. If that hits ≥80% matter + closes the 4pp vedana gap on email, D1 ratifies.
4. **Parallel cleanup:** 2-line fix to `normalize_matter()` to handle string "null"/"none" → Python None. Buys 1-4 rows free.
5. **Director 5-min spot check** on the 6 signals where BOTH models miss vedana — confirm labels are correct before spending prompt-engineering time on them.

---

## 8. Commits

- Prompt patch: (commit SHA populated after commit)
- Results JSON: `outputs/kbl_eval_results_20260417.json` (overwrote the prior-run file — same filename, same date)
- Log: `eval_retry.log` (not committed — transient)
- This report: `briefs/_reports/B3_d1_eval_retry_20260417.md`

---

*Wall-clock: ~14 min for 100 inferences over SSH+curl fallback (HTTP path unavailable — macmini hostname doesn't resolve from Dropbox Mac, handover noted this). No code errors, no timeouts.*
