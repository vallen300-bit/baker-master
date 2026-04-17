# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance, fresh session, dedicated labeling companion)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: D1 Pre-Shadow Eval — Director Labeling Companion + Gemma Eval Runner

### Purpose

D1 is ratified conditionally on Gemma 4 8B achieving **≥90% vedana accuracy on a 50-signal Director-labeled eval**. Your job: make the 60-min labeling session as frictionless as possible for Director, then run the eval.

### Prerequisites (verify before starting)

Run these quick checks, report fail if any:

```bash
cd <baker-master-clone>

# 1. Scripts present
ls -la scripts/build_eval_seed.py scripts/validate_eval_labels.py scripts/run_kbl_eval.py

# 2. DATABASE_URL set (you'll need this to pull signals)
echo "${DATABASE_URL:+SET}" | grep -q SET || echo "FAIL: DATABASE_URL not in env"

# 3. SSH to macmini works (for run_kbl_eval at the end)
ssh -o ConnectTimeout=5 macmini "echo ok" || echo "FAIL: macmini SSH not reachable"

# 4. Ollama on macmini has gemma4 + qwen2.5:14b
ssh macmini "ollama list" | grep -E "gemma4|qwen2.5:14b"
```

If any fail, report to Director via chat, don't proceed.

### Step 1 — Build eval seed (~30 sec)

```bash
python3 scripts/build_eval_seed.py
```

Should produce `outputs/kbl_eval_set_<YYYYMMDD>.jsonl` (50 signals) + a labeling template file.

Confirm 50 signals loaded. Report counts per source:
```
Email: <N>   WhatsApp: <N>   Meeting: <N>
Total: 50 ✓
```

### Step 2 — Labeling session (~55 min, Director-interactive)

**Your role:** present signals one at a time in chat; parse Director's one-line replies; write labels back to JSONL file progressively (save after each signal so a mid-session pause doesn't lose work).

**Presentation format per signal:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Signal 12/50 | source: email | date: 2026-03-22
From: m.hassa@tfkable.com
Subject: RG7 Schlussabrechnung — response to 18 March

<full body or first 600 chars if longer>

Hint matter (from tags, may be empty): hagenauer-rg7
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Your call:
  vedana: opportunity | threat | routine
  primary_matter: <slug> (e.g., hagenauer-rg7, cupial, mo-vie, ao, null)
  related_matters: comma list (or empty)
  triage_pass (would you want to be alerted?): y/n
  notes (optional): <free text>

Format: "threat | hagenauer-rg7 | cupial | y | final account escalation"
```

**Parsing:** accept `<vedana> | <primary> | <related csv> | <y/n> | <notes>`. Be tolerant:
- Empty `related_matters` is `""` or `none` or `-`
- Director may drop the trailing notes field — that's fine
- Case-insensitive on vedana + y/n
- If the line doesn't parse, ask for a re-type; don't skip

**Vedana enum (STRICTLY these 3 values):** `opportunity` | `threat` | `routine`. If Director types `pleasant` / `unpleasant` / `neutral` (classical Buddhist vocab), gently correct and explain the production schema uses `opportunity/threat/routine`. DO NOT accept the classical vocab — validator will reject it.

**Matter slugs (production canonical):** `hagenauer-rg7`, `cupial`, `mo-vie`, `ao`, `morv`, `lilienmatt`, `wertheimer`. If Director uses a variant, normalize or ask. If none apply, use `null` (the string `null`, which the validator accepts).

**Progress indicator:** after every 10 signals, report `Labeled 10/50. Estimated remaining: ~45 min.` etc.

**Save-after-each:** append to or update the labels file after each Director response. Never batch — if session drops at signal 34, resume from 35.

**Filename for labels:** `outputs/kbl_eval_set_<YYYYMMDD>_labeled.jsonl` (the labeling template file, filled in). Create if not present at start.

### Step 3 — Validate labels (~1 sec)

```bash
python3 scripts/validate_eval_labels.py outputs/kbl_eval_set_<YYYYMMDD>_labeled.jsonl
```

**Expected:** exit 0, "50/50 valid".

If validator rejects any rows:
- Fix inline with Director (show the specific row + error, ask for re-label)
- Re-run validator until clean

### Step 4 — Run eval against Gemma + Qwen (~5-10 min)

```bash
python3 scripts/run_kbl_eval.py outputs/kbl_eval_set_<YYYYMMDD>_labeled.jsonl --compare-qwen
```

This SSHes to macmini, runs Gemma 4 8B on each of the 50 signals, then runs Qwen 2.5 14B for comparison. Produces `outputs/kbl_eval_results_<YYYYMMDD>.json`.

### Step 5 — Report results

File per mailbox pattern at `briefs/_reports/B3_d1_eval_results_20260417.md`.

**Must include:**

1. **TL;DR one-liner:** `D1 eval: Gemma <X>% vedana, <Y>% JSON, <Z>% matter. <PASS|FAIL> D1 thresholds.`
2. Per-source breakdown (email / WA / meeting) with vedana accuracy each
3. Qwen comparison numbers (does Qwen pass if Gemma failed?)
4. Any signals where BOTH models failed — likely schema/prompt issue, flag for KBL-B tuning
5. Commit SHAs: the JSONL file(s) + results JSON + this report

**Acceptance (D1 thresholds):**
- Vedana overall ≥ 90%
- Vedana per-source ≥ 85%
- JSON validity 100%
- Primary matter accuracy ≥ 80%

### Step 6 — Commit + push

```bash
git add outputs/kbl_eval_set_*.jsonl outputs/kbl_eval_results_*.json briefs/_reports/B3_d1_eval_results_20260417.md
git -c user.name="Code Brisen 3" -c user.email="dvallen@brisengroup.com" commit -m "feat: D1 pre-shadow eval — Director labels + Gemma/Qwen results"
git push origin main
```

Chat one-liner to Director:
```
D1 eval report at briefs/_reports/B3_d1_eval_results_20260417.md, commit <SHA>.
TL;DR: Gemma <X>% vedana, <PASS|FAIL> D1.
```

### Time budget

| Step | Estimated |
|---|---|
| Prerequisites | 1 min |
| Step 1 (seed) | 30 sec |
| Step 2 (labeling, Director-interactive) | **55 min** |
| Step 3 (validate) | 1 sec |
| Step 4 (eval runner) | 5-10 min |
| Step 5 (report) | 5 min |
| Step 6 (commit) | 1 min |
| **Total Director time** | ~60 min |
| **Total B3 wall-clock** | ~75 min including runner |

### Critical reminders

- **Save labels incrementally** — never batch. Session crash mid-labeling is recoverable.
- **Strict vedana enum** — `opportunity/threat/routine` only.
- **One signal at a time** — don't dump 5 signals in a block; Director can't parallelize.
- **Don't offer your own labels** — you present the signal, Director decides. If Director ASKS for a hint ("what do you think?"), you can suggest, but default to letting them decide cold.
- **Report file is MANDATORY even if Gemma fails** — D1 has a defined fallback path (retry with Qwen; if both fail, D1 reverts to option B). Failure isn't a reporting exception.

### Parallel context

- AI Head (me) is running KBL-A R2 review flow with Code B1 in parallel.
- B2 is standing by with no task.
- Director will context-switch between me (KBL-A ratification) and you (labeling) during the 60 min.
- SSH hardening (5-min Director task) may happen in parallel — ignore for your scope.

---

*Task posted by AI Head 2026-04-17. This is Code Brisen #3's first task — fresh session, no prior context. If you hit anything unexpected (table not present, SSH fails, DATABASE_URL drift), STOP and report to Director via chat — don't improvise.*
