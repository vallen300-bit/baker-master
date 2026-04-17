# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance, fresh session, D1 eval retry)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution
**Supersedes:** the labeling-companion task previously at this path (completed — results in `briefs/_reports/B3_d1_eval_results_20260417.md`)

---

## Task: D1 Pre-Shadow Eval — Retry with Fair Prompt (Option C)

### Context (60-second read)

Your first eval run failed both models at Option-A thresholds:

- Gemma: 70% vedana / 100% JSON / 30% matter (need ≥90% / 100% / ≥80%)
- Qwen: 66% / 100% / 36%

Your own §4 analysis identified the cause as **prompt engineering, not model capability**:

1. The Step-1 prompt lists only 6 of the 19 canonical matter slugs
2. Director's vedana semantics ("opportunity = NEW strategic gains only; defensive wins stay in threat arc") are nowhere in the prompt
3. Near-duplicate Baker self-analyses + 1 garbled transcript drag the average

Director approved **Option C**: patch the prompt, re-run against the same labeled set, and let the retry decide D1. The labels at `outputs/kbl_eval_set_20260417_labeled.jsonl` are ground truth — **do NOT re-label**.

---

## What to do

### 1. Patch the prompt in `scripts/run_kbl_eval.py`

Current prompt (lines 55–65):

```python
STEP1_PROMPT = """You are a triage agent for a 28-matter business operation (real estate, hospitality, legal disputes, investment). Classify this signal. Output ONLY valid JSON, no commentary.

Signal: "{signal}"

Respond with exactly this JSON:
{{
  "matter": "which business matter (e.g. hagenauer-rg7, cupial, mo-vie, ao, brisen-lp, mrci)",
  "vedana": "opportunity | threat | routine",
  "triage_score": 0-100,
  "summary": "one line"
}}"""
```

Replace with a prompt that:

**(a)** Enumerates the full canonical matter allowlist (19 slugs + `null`). **Source of truth:** `scripts/validate_eval_labels.py` → `MATTER_ALLOWLIST` (19 entries as of commit `7a3ea2d`). Import it rather than duplicate — single source.

**(b)** States that `null` is a valid output when no matter applies, and that non-slug strings like `"none"`, `"hospitality"`, `"investment"`, `"legal disputes"` are invalid.

**(c)** Embeds Director's vedana rule verbatim:

```
Vedana classification rules:
- opportunity: NEW strategic gains ONLY — a new deal, investor interest,
  unrequested approach, favorable market shift, novel capability revealed.
  Defensive wins inside an ongoing threat arc (e.g., court ruling in our
  favor on a dispute, successful rectification) stay in threat, not opportunity.
- threat: risks, problems, disputes, deadlines, unpaid invoices, regulatory
  issues, counterparty demands, adverse events, and defensive moves/recoveries
  inside an ongoing threat arc.
- routine: noise — receipts, automated notifications, newsletters, FYI
  emails, admin correspondence with no action required.
```

**(d)** Keeps D1 sampling config (`temperature=0.0, seed=42, top_p=0.9, num_predict=512`) untouched. This is a prompt-only change.

**(e)** Do NOT change `ACCEPT` thresholds, `NORMALIZE_VEDANA`, or the scoring logic. Same bar.

### 2. Optional but recommended — fix the stale alias

`scripts/run_kbl_eval.py` line 83:

```python
"brisen-lp": ["brisen", "wertheimer"],
```

Director split `wertheimer` out as its own slug during labeling. Remove `"wertheimer"` from the `brisen-lp` alias list (otherwise model outputs of `"wertheimer"` get coerced to `brisen-lp` and accuracy gets spuriously dinged when ground truth is `wertheimer`). Rely on the exact-canonical match at line 113, or add `"wertheimer": ["wertheimer"]` explicitly.

Document this fix in the report.

### 3. Re-run the eval

```bash
cd /tmp/bm-b3
git pull --ff-only origin main
.venv/bin/python3 scripts/run_kbl_eval.py outputs/kbl_eval_set_20260417_labeled.jsonl --compare-qwen
```

Same labeled set, same sampling, same macmini Ollama. Only prompt changed.

### 4. Compare results vs thresholds

D1 pass criteria (from `ACCEPT` in the script):

- Gemma vedana_overall ≥ 90%
- Gemma vedana_per_source ≥ 85% (email / meeting / whatsapp)
- Gemma json_validity = 100%
- Gemma primary_matter ≥ 80%

Report pass/fail per metric, per model. Gemma is the D1 target; Qwen is comparison.

### 5. File report

Path: `briefs/_reports/B3_d1_eval_retry_20260417.md`

Include:

- TL;DR (1 line: pass / fail + key numbers)
- Before/after comparison table (Gemma overall + per-source; Qwen overall)
- Which specific signals flipped from miss → hit (top 5 for vedana, top 5 for matter)
- Any signals still missed by both models — is it a genuine capability gap, or further prompt drift? (your judgment)
- Recommendation: D1 ratify, revert to Option B (Qwen primary), or further iterate
- Commit SHAs for: prompt patch, alias fix, eval results JSON

### 6. Dispatch back

Chat one-liner to Director via me (standard mailbox dispatch):

> `B3 D1 retry complete — see briefs/_reports/B3_d1_eval_retry_20260417.md, commit <SHA>. TL;DR: <pass|fail> with <Gemma vedana%> / <matter%>.`

---

## Scope guardrails

- **Do NOT touch** the labeled set. Labels are ground truth.
- **Do NOT touch** ACCEPT thresholds, NORMALIZE_VEDANA, scoring logic, or D1_OPTIONS.
- **Do NOT** add few-shot examples — this retry isolates the slug-enum + vedana-rule variables. Few-shot is a KBL-B experiment, not an Option-C move.
- **Do NOT** rewrite the eval runner architecture. One-function prompt swap.
- **DO** note any further issues you spot (garbled transcripts, near-duplicates, slug drift) in the report's "side-effects" section. AI Head wants the signals for the KBL-B brief.

---

## Decision logic after your report

- **If Gemma passes all 4 thresholds:** D1 ratifies. AI Head moves to KBL-B brief.
- **If Gemma passes vedana but not matter (or vice versa):** partial capability signal — AI Head weighs whether D1 ratifies with a narrower scope or needs further work.
- **If Gemma still fails both with a fair prompt:** capability gap is real. D1 reverts to Option B (Qwen primary) or model swap. AI Head's KBL-B brief will use a model-agnostic choice.

Director's Option-C directive: **the fair-prompt retry is what settles D1.** No further iterations on this eval set after this retry — if it fails, D1 closes via revert.

---

## Est. time

~30 minutes:

- 10 min prompt patch + alias fix
- 10 min eval run (50 signals × 2 models on macmini)
- 10 min report + commits

---

*Dispatched 2026-04-17 by AI Head. Supersedes prior pending content. Acknowledge by committing work to main on `/tmp/bm-b3` with git identity `Code Brisen 3` / `dvallen@brisengroup.com`.*
