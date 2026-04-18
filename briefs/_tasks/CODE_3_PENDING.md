# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3 (app instance)
**Previous:** Step 0 Layer 0 rules shipped at `6341b94` (being reviewed by B2 in parallel)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution

---

## Task: Draft KBL-B §10 Test Fixtures — 10-Signal End-to-End Corpus

You own the richest empirical knowledge of the 50-signal labeled set (`outputs/kbl_eval_set_20260417_labeled.jsonl`). AI Head is about to write §10 (test plan) and needs a 10-signal fixture that exercises every path through the 8-step pipeline.

### Deliverable

File: `briefs/_drafts/KBL_B_TEST_FIXTURES.md`

### Selection criteria — pick 10 signals that collectively exercise these paths

Every signal should be annotated with:
- **Source `signal_id`** (from the labeled JSONL, by source + source-specific ID)
- **Source kind** (email / whatsapp / meeting_transcript / scan_query)
- **Expected Layer 0 outcome** (pass | drop with rule-name)
- **Expected Step 1 triage outcome** (primary_matter, vedana, triage_score range)
- **Expected Step 2 resolve outcome** (thread match expected? based on what eval signal context?)
- **Expected Step 3 extract outcome** (rough schema — e.g., "extract Ofenheimer, Brisen, 1 money figure, 1 deadline, 1 action_item")
- **Expected Step 4 classify decision** (full_synthesis | stub_only | cross_link_only | skip_inbox)
- **Expected Step 5 opus firing** (yes/no, if no why — cost-cap / skip_inbox / paused)
- **Expected Step 6 sonnet firing** (yes/no)
- **Expected Step 7 commit outcome** (target_vault_path template)

### Required path coverage

The 10 signals must collectively hit ALL of these paths at least once:

| Path | Signals count minimum |
|---|---|
| Layer 0 drops (per-source, different rules) | 2 (one email drop + one WA/transcript drop) |
| Triage routes to inbox (low triage_score) | 1 |
| Thread-resolve hits existing vault entry (arc continuation) | 1 |
| New arc (empty resolved_thread_paths) | 1 |
| Cross-link multi-matter (related_matters[] non-empty) | 1 |
| Full synthesis path (clean through all steps) | 2 (one email + one transcript) |
| Layer 2 gate blocks (non-hagenauer-rg7 matter routed to inbox) | 1 |
| Expected Step 5 cost-cap defer (synthetic — hypothetical scenario) | 1 |

Total: 10 signals, each covering 1-3 distinct path aspects. Some signals will naturally cover multiple (e.g., a Hagenauer transcript with continuation arc covers "new arc" OR "continuation" + "full synthesis").

### Format

For each signal, use a card-style block:

```markdown
### Fixture #N — <short descriptive title>

**Signal:** `<source>:<signal_id>`  (line <N> of labeled.jsonl)
**Paths exercised:** <Path 1>, <Path 2>, ...
**Raw content excerpt:** `"<first 80 chars>..."`

| Step | Expected |
|---|---|
| 0 layer0 | pass / drop (rule: `<name>`) |
| 1 triage | primary_matter=`<X>`, vedana=`<Y>`, triage_score ≈ <N> |
| 2 resolve | resolved_thread_paths = [<path>] OR [] |
| 3 extract | `{"people": [<N> expected], "money": [<N>], ...}` (high-level) |
| 4 classify | `<decision>` |
| 5 opus | fires / skipped (reason: `<why>`) |
| 6 sonnet | fires / skipped |
| 7 commit | `wiki/<matter>/<yyyymmdd>_<title-slug>.md` OR N/A |

**Rationale:** why this signal was chosen for this path, referencing v1/v2/v3 eval observations.
```

### Out of scope

- Running any signal through actual Python — paper fixtures only
- Speculating about signals not in the labeled set
- Writing pytest code — that's §10 implementation work, separate ticket
- Adjusting labels or D1 outcomes

### Why this is your task

You labeled the signals with Director. You know their content, ambiguity, and empirical behavior. AI Head picking signals from text alone would miss the nuance.

### Dispatch back

> B3 §10 fixtures drafted — see `briefs/_drafts/KBL_B_TEST_FIXTURES.md`, commit `<SHA>`. 10 signals covering <N> distinct paths.

### Est. time

~30-45 min:
- 10 min re-read labels + path-coverage matrix
- 25 min fixture authoring
- 5 min commit + report

---

*Dispatched 2026-04-18 by AI Head.*
