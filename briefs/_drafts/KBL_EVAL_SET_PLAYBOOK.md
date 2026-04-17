# KBL Pre-Shadow Eval Set — Director's Playbook

**Status:** DRAFT (pre-stage; ratification pending v2.1 → final).
**Unblocks:** D1 Gemma-4-8B lock. Per v2.1 B1, the eval set must exist **before** shadow mode starts, not during. This playbook is the path from zero → ratified D1.
**Prepared-by:** Code Brisen #2 (2026-04-17).
**Reference specs:**
- [`DECISIONS_PRE_KBL_A_V2_DRAFT.md`](../DECISIONS_PRE_KBL_A_V2_DRAFT.md) D1, B1, S8
- [`scripts/benchmark_ollama_triage.py`](../../scripts/benchmark_ollama_triage.py) — existing synthetic-signal benchmark; eval runner reuses its prompt + parsing

---

## 1. Purpose

D1 locks Gemma 4 8B as the primary KBL pipeline model for Steps 1–4. The lock is **conditional** on this eval set passing acceptance criteria (see §6). Without the eval, D1 can't ratify. Without D1, KBL-A can't dispatch. So this playbook is the critical path gate.

The eval also produces the dataset against which future model swaps are judged — so it's reused through Phase 1 and beyond.

---

## 2. Sampling — 50 signals from real PG data (S8)

Stratified: **25 email + 15 WhatsApp + 10 meeting transcripts**. Within each source, split ~60/40 Hagenauer / other matters. Seeded random for reproducibility.

### 2a. Pre-flight: confirm source counts

Already run per CB2 census (2026-04-17): email 159, WA 126, meeting 37 — all ≥20 per source. Re-run if stale:

```sql
SELECT 'email' AS source, COUNT(*) FROM email_messages
  WHERE subject ILIKE '%hagenauer%' OR full_body ILIKE '%hagenauer%'
     OR subject ILIKE '%RG7%' OR full_body ILIKE '%RG7%'
UNION ALL
SELECT 'whatsapp', COUNT(*) FROM whatsapp_messages
  WHERE full_text ILIKE '%hagenauer%' OR full_text ILIKE '%RG7%'
UNION ALL
SELECT 'meeting', COUNT(*) FROM meeting_transcripts
  WHERE title ILIKE '%hagenauer%' OR title ILIKE '%RG7%'
     OR full_transcript ILIKE '%hagenauer%' OR full_transcript ILIKE '%RG7%';
```

### 2b. Sampling SQL → JSONL seed file

Run this from any machine with PG access (Render shell, local with `DATABASE_URL`, or via `mcp__baker__baker_raw_query`). Seed = `42` (matches D1 `seed=42`):

```sql
-- 15 Hagenauer emails
WITH email_hg AS (
  SELECT 'email' AS source, id::text, subject AS title,
         LEFT(full_body, 2000) AS signal_text,
         received_at AS occurred_at
    FROM email_messages
   WHERE subject ILIKE '%hagenauer%' OR full_body ILIKE '%hagenauer%'
      OR subject ILIKE '%RG7%'
   ORDER BY md5(id::text || '42') LIMIT 15
),
-- 10 non-Hagenauer emails (other matters)
email_other AS (
  SELECT 'email' AS source, id::text, subject AS title,
         LEFT(full_body, 2000) AS signal_text,
         received_at AS occurred_at
    FROM email_messages
   WHERE NOT (subject ILIKE '%hagenauer%' OR full_body ILIKE '%hagenauer%' OR subject ILIKE '%RG7%')
   ORDER BY md5(id::text || '42') LIMIT 10
),
-- 9 Hagenauer WA + 6 other
wa_hg AS (
  SELECT 'whatsapp' AS source, id::text, NULL AS title,
         LEFT(full_text, 2000) AS signal_text,
         created_at AS occurred_at
    FROM whatsapp_messages
   WHERE full_text ILIKE '%hagenauer%' OR full_text ILIKE '%RG7%'
   ORDER BY md5(id::text || '42') LIMIT 9
),
wa_other AS (
  SELECT 'whatsapp' AS source, id::text, NULL AS title,
         LEFT(full_text, 2000) AS signal_text,
         created_at AS occurred_at
    FROM whatsapp_messages
   WHERE NOT (full_text ILIKE '%hagenauer%' OR full_text ILIKE '%RG7%')
     AND full_text IS NOT NULL AND length(full_text) > 50
   ORDER BY md5(id::text || '42') LIMIT 6
),
-- 6 Hagenauer + 4 other meetings
mtg_hg AS (
  SELECT 'meeting' AS source, id::text, title,
         LEFT(full_transcript, 3000) AS signal_text,
         meeting_date AS occurred_at
    FROM meeting_transcripts
   WHERE title ILIKE '%hagenauer%' OR full_transcript ILIKE '%hagenauer%' OR full_transcript ILIKE '%RG7%'
   ORDER BY md5(id::text || '42') LIMIT 6
),
mtg_other AS (
  SELECT 'meeting' AS source, id::text, title,
         LEFT(full_transcript, 3000) AS signal_text,
         meeting_date AS occurred_at
    FROM meeting_transcripts
   WHERE NOT (title ILIKE '%hagenauer%' OR full_transcript ILIKE '%hagenauer%' OR full_transcript ILIKE '%RG7%')
     AND full_transcript IS NOT NULL AND length(full_transcript) > 100
   ORDER BY md5(id::text || '42') LIMIT 4
)
SELECT source, id, title, signal_text, occurred_at
  FROM (
    SELECT * FROM email_hg UNION ALL SELECT * FROM email_other
    UNION ALL SELECT * FROM wa_hg UNION ALL SELECT * FROM wa_other
    UNION ALL SELECT * FROM mtg_hg UNION ALL SELECT * FROM mtg_other
  ) sampled
 ORDER BY source, id;
```

Export as JSONL to `eval/seed_unlabeled.jsonl` — **one line per signal**. Script wrapper:

```bash
# From repo root on any machine with DATABASE_URL set:
python3 scripts/build_eval_seed.py  # writes eval/seed_unlabeled.jsonl
```

(Script to be written when this playbook ratifies — ~30 LOC wrapper around the SQL above + `psycopg2` + `json.dumps`. Can be hand-rolled at apply time if preferred.)

### 2c. Expected distribution

| Source | Hagenauer | Other | Total |
|---|---|---|---|
| email | 15 | 10 | 25 |
| whatsapp | 9 | 6 | 15 |
| meeting | 6 | 4 | 10 |
| **total** | **30** | **20** | **50** |

---

## 3. Labeling schema

Each line in `eval/seed_unlabeled.jsonl` becomes one record with `{source, id, title, signal_text, occurred_at}`. Director adds the labels below, producing `eval/labeled.jsonl`:

```jsonc
{
  // --- from seed (don't edit) ---
  "source": "email",
  "id": "...",
  "title": "...",
  "signal_text": "...",
  "occurred_at": "2026-03-14T09:12:00Z",

  // --- Director adds ---
  "vedana": "threat",                    // "opportunity" | "threat" | "routine"
  "primary_matter": "hagenauer-rg7",     // canonical matter slug; null if no matter applies
  "related_matters": ["cupial"],         // array of secondary matter slugs; [] if none
  "triage_threshold": 50,                // 0–100. "If Gemma scores >= this, it should alert me."
                                         // Implicit: score < threshold means the signal should not
                                         // have interrupted Director. Calibrates §6 acceptance.
  "notes": "Final-account threat letter; time-critical 14-day deadline"
}
```

**Matter slug canonical list** (use only these; expand via AI Head if missing):
`hagenauer-rg7`, `cupial`, `mo-vie`, `ao`, `brisen-lp`, `mrci`, `lilienmat`, `edita-russo`, `theailogy`, `baker-internal`, `personal`.

**`null` primary_matter** is legal and meaningful — signals that should route to `_inbox/` per R1.11.

**`related_matters`** captures the R1.10 multi-matter case (Hagenauer threat from Cupial's lawyer would be `primary=hagenauer-rg7`, `related=['cupial']`).

---

## 4. Labeling UX — two paths

Pick whichever is faster for the Director on any given signal. Both write the same `labeled.jsonl` format.

### Option A — JSONL edit in your editor (fast for bulk)

```bash
cd "/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/baker-code"
cp eval/seed_unlabeled.jsonl eval/labeled.jsonl
code eval/labeled.jsonl     # or your editor of choice
```

For each line, add the five Director fields inline. A validator script catches errors:

```bash
python3 scripts/validate_eval_labels.py eval/labeled.jsonl
# reports: missing fields, invalid vedana values, unknown matter slugs,
# triage_threshold out of range.
```

**Time estimate:** ~45–60 s per signal once you're warmed up → **40–50 min total**.

### Option B — Baker-chat inline (one at a time, context-aware)

For signals that need context (e.g. "is this threat real?"), route through Baker:

1. Open Baker Scan (`baker-master.onrender.com/scan`).
2. Prompt:
   ```
   Help me label this KBL eval signal. Source=email, id=<id>.
   Read the full signal in context of our matter history and propose:
   vedana / primary_matter / related_matters / triage_threshold.
   I'll confirm or correct, then you write the labeled JSONL line.
   ```
3. Baker returns a proposal. You `[y]` to accept, or type a correction.
4. Baker appends the line to `eval/labeled.jsonl` in the repo via MCP (`mcp__baker__baker_raw_write` with schema guard, or a dedicated `/eval/label` endpoint added in KBL-A).

**Time estimate:** ~90–120 s per signal (more context, slower) → **~75–100 min**. Use this for ambiguous cases, Option A for obvious ones.

A realistic mix: ~40 easy signals in Option A (~40 min) + ~10 hard signals in Option B (~15 min) = **~55 min total labeling time**.

---

## 5. Eval runner — `scripts/run_kbl_eval.py`

The runner SSHs to macmini, hits local Ollama, runs the Step-1 triage prompt against each labeled signal, compares model output to Director labels, reports per-source accuracy. Reuses [`scripts/benchmark_ollama_triage.py`](../../scripts/benchmark_ollama_triage.py) for prompt + JSON parsing.

### Inputs
- `eval/labeled.jsonl` (Director output from §4)
- `--model` flag: `gemma4:latest` (primary) or `qwen2.5:14b` (fallback)
- Env: `OLLAMA_HOST=macmini:11434` (Tailscale), or run from macmini directly

### Call shape per signal (matches the real pipeline)

```python
response = ollama_generate(
    model=args.model,
    prompt=STEP1_TRIAGE_PROMPT.format(signal=record["signal_text"]),
    format="json",                      # forces JSON per benchmark_ollama_triage.py
    options={
        "temperature": 0.0,             # D1 lock
        "seed": 42,                     # D1 lock
        "top_p": 0.9,                   # D1 lock
        "num_predict": 512,
    },
)
parsed, json_ok = parse_json_response(response)   # reuse
```

### Per-signal scoring

| Check | Pass condition |
|---|---|
| JSON validity | `json.loads(output)` succeeds with `vedana`, `primary_matter`, `triage_score` present |
| vedana match | `output["vedana"] == label["vedana"]` (case-insensitive) |
| primary_matter match | `output["primary_matter"] == label["primary_matter"]`, OR both are null, OR matches alias map (see benchmark_ollama_triage.py:171) |
| triage_score bucket | `(output["triage_score"] >= label["triage_threshold"]) == (label["vedana"] != "routine")`  — i.e. model's alert decision agrees with Director's |

Per-source + overall accuracy reported. Per-signal failures logged to `eval/results_<model>_<timestamp>.jsonl` for diff review.

### Output

```
=== KBL Pre-Shadow Eval — gemma4:latest — 2026-04-18T10:12Z ===
                 vedana   primary_matter   triage_bucket   json_valid
email   (25):    23/25    22/25            22/25           25/25
whats   (15):    14/15    13/15            13/15           15/15
mtg     (10):     9/10     8/10             9/10           10/10
-----------------------------------------------------------
overall (50):    46/50    43/50            44/50           50/50
                 92.0%    86.0%            88.0%          100.0%

vs. acceptance (§6):
  vedana ≥90% overall:       PASS
  vedana ≥85% per source:    PASS  (92/93/90%)
  json validity 100%:        PASS
  primary_matter ≥80%:       PASS  (86%)

RESULT: D1 eval — Gemma 4 8B — PASS.
```

---

## 6. Acceptance criteria (D1 ratification)

All four must pass for Gemma 4 8B to lock as primary:

| # | Criterion | Threshold | Why |
|---|---|---|---|
| C1 | Overall vedanā accuracy | **≥90%** | Vedanā is the single highest-leverage field — drives D6 auto-proceed + alert-or-not |
| C2 | Per-source vedanā accuracy | **≥85% each** (email, WA, meeting) | Prevents a source being silently useless |
| C3 | JSON validity | **100%** | Any invalid JSON = pipeline stall or DLQ. Unacceptable. |
| C4 | `primary_matter` accuracy | **≥80%** | Drives D3 routing. 80% tolerates matter-ambiguous edge cases; below 80%, routing becomes unreliable |

A 49/50 failure on C3 (one invalid JSON) is still a fail — the benchmark_ollama_triage.py parser has three fallback strategies; if all three fail, the pipeline fails too.

---

## 7. Failure path

If Gemma 4 8B fails any acceptance criterion, follow this ladder **without** changing D1:

1. **Re-run with Qwen 2.5 14B** (already pulled per R3 Task D, `qwen2.5:14b` / 8.4 GiB blob):
   ```bash
   python3 scripts/run_kbl_eval.py --model qwen2.5:14b
   ```
2. **If Qwen passes all four criteria and Gemma failed any:** D1 swaps primary to Qwen, Gemma becomes fallback. Document the swap in v2.2 + rationale (e.g. "Qwen 86% vs Gemma 81% on primary_matter — structural win").
3. **If both models fail the same criterion:** the criterion itself may be mis-calibrated for local 8–14B models. Escalate to AI Head — candidates: relax C4 to 75% with S-tier gap monitoring, OR fall back to Haiku-via-Anthropic for Steps 1–4 (reverses D1 rationale; big decision; requires Director).
4. **If one model fails only C2 per-source** (e.g. meeting source <85% but email/WA pass): sample more meeting signals (n=20 instead of 10), re-run; meeting signals have higher variance due to transcript noise.

Qwen cold-swap at runtime is already a spec'd D1 behavior — the eval just validates the claim.

---

## 8. Director's critical path to D1 unlock

1. Code Brisen #2 (or Code) writes `scripts/build_eval_seed.py` and `scripts/run_kbl_eval.py` when this playbook ratifies. **~1 h code time.**
2. Director runs `build_eval_seed.py` → `eval/seed_unlabeled.jsonl`. **~30 s.**
3. Director labels. **~55 min** (mixed Option A + B per §4).
4. Validator passes. **~10 s.**
5. `run_kbl_eval.py --model gemma4:latest` on macmini. **~5 min** (50 signals × ~5 s triage each; per benchmark_ollama_triage.py on an M4).
6. If pass → D1 ratifies. If fail → §7 ladder. **~5 min fallback run** if needed.

**Total Director time (happy path): ~60 minutes, start to D1 lock.**

---

## 9. Out of scope for this playbook

- Shadow-mode eval (the D1 Phase-1-exit gate) — separate artifact, reuses this labeled set plus new production signals.
- Eval of Steps 2–4 (Resolve / Extract / Classify) — D1 only ratifies Step 1 via vedanā + primary_matter. Other steps locked once Step 1 is green, eval'd opportunistically during shadow.
- Opus Step 5 / Sonnet Step 6 evals — cloud-model quality not in scope for Gemma lock.

---

**Next action when ratified:** Code (either Brisen) writes `scripts/build_eval_seed.py` + `scripts/validate_eval_labels.py` + `scripts/run_kbl_eval.py`. Estimate 1 h combined. Then handed to Director for §8.
