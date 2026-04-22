# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 (post-Gate-1-mechanical; Gate 2 content-quality investigation)
**Status:** OPEN — STEP5_OPUS_SCOPE_GATE_DIAGNOSTIC_1

---

## Context — Gate 1 closed mechanically; content is all stubs

Pipeline is end-to-end healthy after your PR #36 merged. 10 signals reached terminal state with `target_vault_path` + `commit_sha`. **But all 10 are `step_5_decision = 'skip_inbox'` — Opus judged every signal as "out-of-scope" — including 9 rows tagged `primary_matter = 'hagenauer-rg7'` and 1 tagged `lilienmatt`.**

Hagenauer and Lilienmatt are **active in-scope matters** per `kbl/matters/*` and the Director's current worklist. The bridge routed these signals correctly (matter_slug set), but the Step 5 Opus scope-gate rejected them all with the boilerplate title "Layer 2 gate: matter not in current scope."

This is Gate 2 territory: the pipeline works, but it produces zero real content. Every signal becomes a stub.

## Scope — DIAGNOSTIC (don't ship a fix yet)

You are running a **read-only investigation**. Surface findings; AI Head decides the fix brief.

### Question 1: Why does Opus rule every signal out-of-scope?

- Read `kbl/steps/step5_opus.py` end-to-end. Map the decision flow from claim → prompt build → Opus call → decision parse → `step_5_decision` write.
- Read `kbl/prompts/step5_opus_system.txt` and `kbl/prompts/step5_opus_user.txt` — what instructions is Opus receiving about scope? What does the prompt tell Opus counts as "in-scope"?
- Find the scope list. Is there a hardcoded list of "current matters"? Is it loaded from a config / DB table / hot.md? Is Hagenauer on it? Is Lilienmatt?
- Check the actual Opus response on one of the completed rows (id 2, 12, 17, 18, 20, 25, 50, 51, 52, 53) — is there a stored `result` or `triage_summary` column capturing what Opus said?

### Question 2: Is the scope list stale?

- Matter slugs in Baker: `hagenauer-rg7`, `lilienmatt`, `annaberg`, `balducci`, `cupials`, `mo-vienna`, `baden-baden`, `ao`, etc. (verify via `SELECT DISTINCT primary_matter FROM signal_queue`). Confirm the scope gate matches what the Director considers active.
- If the scope list is hardcoded inline (e.g. a Python list), note the location. If loaded from `hot.md`, check the file state. If loaded from Postgres, query the source table.

### Question 3: Is it prompt drift vs. list drift?

Two distinct root causes possible:
- **List drift:** the scope list is authoritative but missing Hagenauer/Lilienmatt (or contains stale slugs).
- **Prompt drift:** the list is correct but the prompt tells Opus to be conservative / reject ambiguous / default-to-skip, and Opus follows that instruction too literally.

Diagnose which one. If both, rank by impact.

### Question 4: What would unlock real content?

Based on findings, sketch the fix direction (not the PR — just direction):
- (a) Update scope list to include all active matters
- (b) Re-tune prompt instructions (less conservative default; clearer "if matter_slug matches, it IS in scope")
- (c) Both
- (d) Something else entirely (e.g. Opus model config, temperature, token budget)

### Out of scope
- Don't ship a fix. Diagnostic first; AI Head decides the fix brief based on findings.
- Don't touch Step 5 code in this pass.
- Don't touch schema or bridge.
- Don't ship a prompt-template edit as part of this diagnostic — flag the edit location for the follow-up brief.

## Deliverable

- **Report (no PR):** `briefs/_reports/B1_step5_opus_scope_gate_diagnostic_20260422.md`.
- Report sections:
  1. Decision flow trace (claim → decision-write) with file:line anchors
  2. Prompt contents summary (scope instructions + current matter list surface)
  3. Scope list location + content + staleness assessment
  4. Stored evidence on completed rows (IDs 2/12/17/18/20/25/50-53) — what Opus actually said
  5. Root-cause classification: list drift / prompt drift / both
  6. Fix-direction recommendation with rough effort size (XS / S / M)
  7. Any adjacent findings (e.g. the gate triggers on something unexpected)

## Constraints

- **Effort: S (~1-2 hours).** Read-only investigation.
- No PR, no code changes.
- **Timebox: 2 hours.** If you hit 2h without a finished report, escalate.
- Standard no-ship-by-inspection rule applies if you later ship the fix.

## Working dir

`~/bm-b1`. `git checkout main && git pull -q`.

— AI Head
