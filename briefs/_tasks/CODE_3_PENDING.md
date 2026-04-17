# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous reports:**
- `briefs/_reports/B3_d1_eval_results_20260417.md` (v1 — FAIL)
- `briefs/_reports/B3_d1_eval_retry_20260417.md` (v2 — FAIL, vedana +16pp / matter stuck)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution
**Supersedes:** v2 retry task (complete, reported at commit `6328f11`)

---

## Task: D1 Pre-Shadow Eval — v3 (Semantic Glossary + Scoring Bug Fix)

### Context (60-second read)

v2 result: Gemma 86% vedana / 100% JSON / **34% matter** (FAIL on matter only; vedana cleared the +16pp bar). Qwen 80% / 100% / 36% — worse on vedana.

**Diagnosis you reported (v2 §findings):**

1. Vedana rule landed as designed — prompt engineering works when given semantic content
2. List-expansion alone didn't fix matter — model sees 18 slug names but doesn't know what each *means*
3. Dominant error: `hagenauer-rg7 → brisen-lp` (13/33 misses) — model conflates real-estate dispute with capital structure

The hypothesis is clear: **the model needs a semantic glossary, not a longer list**. One line per slug describing what the matter IS. If vedana precedent holds, matter accuracy should jump meaningfully.

Also: the scoring bug you flagged (`normalize_matter()` doesn't convert `"null"` / `"none"` string to Python `None` → 1-4 rows scored wrong per model) should be fixed before v3 so the measurement is honest.

---

## What to do

### 1. Patch the prompt in `scripts/run_kbl_eval.py`

**Add a per-slug glossary block to `_build_step1_prompt()` (introduced in SLUGS-1).** Source of truth for descriptions: `kbl.slug_registry.describe(slug)` — populated from `baker-vault/slugs.yml` per-entry `description` field.

Format proposal (adjust if a different layout reads better to the model):

```
Matter slugs (pick one or null):

  hagenauer-rg7 — RG7 final-account dispute, Baden bei Wien (contractor/developer litigation)
  cupial        — Cupial handover dispute — Tops 4,5,6,18 (buyer payment + defects)
  mo-vie        — Mandarin Oriental Vienna, asset management oversight
  brisen-lp     — Brisen fund / capital structure matters with LPs
  wertheimer    — Wertheimer relationship / SFO outreach (separated from brisen-lp)
  ao            — Andrej Oskolkov — VIP contact, contract matter
  mrci          — MRCI GmbH real estate investment, Baden-Baden DE
  lilienmat     — Lilienmat GmbH (7% ownership), Baden-Baden DE
  ...
  null          — no matter applies (personal, automated, noise)
```

**Key design note:** several of the "new 8" slugs (`aukera`, `kitzbuhel-six-senses`, `kitz-kempinski`, `steininger`, `balducci`, `constantinos`, `franck-muller`) currently have `description: "(Director to annotate)"` placeholder in baker-vault. For v3 purposes, either:

**(a)** Run with placeholders — model gets the name + "(Director to annotate)" and will likely guess less confidently. Honest but weakens the experiment.
**(b)** Pull one-line descriptions from `CLAUDE.md` where documented (hagenauer-rg7, cupial, mo-vie, ao, mrci, lilienmat, brisen-lp, wertheimer are all in there). For the slugs not in CLAUDE.md, either leave placeholder OR write your best-guess description based on what appeared in the labeled signals that used those slugs.

**Preference: (b).** Document every description you write yourself in the report so Director can ratify them post-hoc. This is a prompt-engineering artifact — the canonical Director-ratified descriptions can land via a later baker-vault PR.

### 2. Fix the `normalize_matter` scoring bug

**Two-line fix.** Per your v2 finding, the `normalize()` path doesn't treat string `"null"` / `"none"` as Python `None`. This costs 1-4 rows per model. Fix in `kbl/slug_registry.py` OR in `scripts/run_kbl_eval.py` score_row, whichever is cleaner given the SLUGS-1 landing state.

If you're on a clone that has SLUGS-1 merged: fix in `slug_registry.normalize()` — that's the canonical normalizer and fixes the bug everywhere at once. Add a test case for it.

If SLUGS-1 hasn't merged yet (baker-vault PR #1 + baker-master PR #2 pending): fix locally in `run_kbl_eval.py`, note the duplicate-fix-in-registry as a follow-up.

**Document which branch you're on and which path you took in the report.**

### 3. Re-run the eval

Same command, same labeled set:

```bash
cd /tmp/bm-b3
git pull --ff-only origin main
BAKER_VAULT_PATH=<your baker-vault clone with slugs-1-vault or main> \
  .venv/bin/python3 scripts/run_kbl_eval.py \
    outputs/kbl_eval_set_20260417_labeled.jsonl \
    --compare-qwen
```

### 4. File report at `briefs/_reports/B3_d1_eval_v3_20260417.md`

Include:

- **TL;DR** (1 line: pass/fail + key numbers)
- **Before/after table** — v2 vs v3, Gemma + Qwen, overall + per-source
- **Matter misses analysis** — did the `hagenauer-rg7 → brisen-lp` confusion resolve? Which categories of miss persist?
- **Vedana stability check** — did the v2 vedana gain (86%) hold or regress?
- **Scoring-bug fix evidence** — 1-2 example rows that now score differently
- **Descriptions you wrote yourself** — list them with slug for Director review
- **Recommendation:** D1 ratify / fourth iteration / architectural escalation

### 5. Dispatch back

Chat one-liner:

> `B3 D1 v3 done — see briefs/_reports/B3_d1_eval_v3_20260417.md, commit <SHA>. TL;DR: <pass|fail> with <Gemma vedana%/matter%>.`

---

## Scope guardrails

- **Do NOT touch** labels, D1_OPTIONS, ACCEPT thresholds.
- **Do NOT re-open** the slug set itself. SLUGS-1 owns the canonical list.
- **DO** document every self-written description so Director can ratify.
- **DO** note any further architectural signals — if matter plateaus *again* despite glossary, that's a real capability ceiling and needs escalation, not a fourth retry.

---

## Decision logic after v3

- **Gemma vedana ≥ 90% AND matter ≥ 80%** → D1 ratifies for Gemma. AI Head flags Qwen-fallback-structural-issue to Director separately.
- **Gemma matter < 80% but ≥ 60%** → partial progress. Architectural question: does KBL-B's Step 2 (resolve) + Step 4 (classify) recover enough to make Step 1 matter-accuracy at 60-80% tolerable, or is 80% a hard requirement? AI Head escalates to Director.
- **Gemma matter < 60%** → hard capability ceiling at 8B local. Options: (a) cloud-based triage (breaks data-residency), (b) different local model (Llama 3.3 70B, Mixtral 8x7B — requires new eval), (c) relax D1 entirely and ship with tolerance. Director decides.
- **No v4.** If v3 doesn't pass cleanly, we stop iterating this prompt and escalate. Diminishing returns are clear.

---

## Est. time

~40 minutes:

- 15 min glossary drafting + prompt patch
- 5 min scoring-bug fix + test
- 10 min eval run
- 10 min report + commits

---

*Dispatched 2026-04-17 by AI Head. Git identity: `Code Brisen 3` / `dvallen@brisengroup.com`.*
