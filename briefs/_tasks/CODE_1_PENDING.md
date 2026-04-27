---
status: OPEN
brief: briefs/BRIEF_B_CODE_AUTOPOLL_1.md
trigger_class: MEDIUM
dispatched_at: 2026-04-27T22:55:00Z
dispatched_by: ai-head-a
claimed_at: null
claimed_by: null
last_heartbeat: null
blocker_question: null
ship_report: null
autopoll_eligible: false
---

# CODE_1_PENDING — B1: B_CODE_AUTOPOLL_1 — 2026-04-27

**Dispatcher:** AI Head A (Build-lead)
**Brief:** `briefs/BRIEF_B_CODE_AUTOPOLL_1.md` (commit `8ca8b7e`)
**Branch:** `b-code-autopoll-1` (cut from `main`)
**Trigger class:** MEDIUM → AI Head B cross-team review pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md` (introduces new convention all future dispatches inherit; load-bearing helper module).
**Estimated time:** 4-6h (Low-Medium complexity)
**Authority:** Director ratified 2026-04-27 chat: "yees" → "ratified all" on 8 open Qs (Q1=900s, Q2=both stop conditions, Q3=multi-stage block, Q4=both Slack channels, Q5=60min stale recovery, Q6=LWW, Q7=B2+B3 only first overnight, Q8=Lesson #48 window-scoped). Director "1" + "also 2" authorized commit + dispatch.

## §2 busy-check + Lesson #47 codebase grep

- **B1 mailbox prior state:** `COMPLETE — PR #68 AMEX_RECURRING_DEADLINE_1 review (B1 ship dba0806 14/14 APPROVE)`. Idle since AMEX cycle close (`893d72e mailbox §3 hygiene`).
- **Worktree:** clean per pre-dispatch check (AI Head A pwd in `~/bm-b1`; `git status` clean except this dispatch and the brief commit).
- **Other B-codes:** B2 just completed WIKI_LINT_1 PR #67 (merged `93f7d8e` 2026-04-27 ~22:50Z); B3 in flight on BAKER_MCP_EXTENSION_1 (B's M2 lane, not mine). No file overlap with B1 scope (process docs + new `scripts/autopoll_state.py` + new `tests/test_autopoll_state.py` + lesson append + 2 mailbox retrofits).
- **Lesson #47 grep results:**
  - `git log --oneline --grep='autopoll'` → no prior commits (greenfield)
  - `ls briefs/archive/ | grep -i autopoll` → no prior brief
  - `grep -rn 'autopoll' scripts/ _ops/processes/ briefs/_tasks/` → no existing implementation
- **Conclusion:** Greenfield. No collision risk.

## What you're building

6 fixes/features per brief §"Fix/Feature 1-6":

1. **State-machine frontmatter** on `briefs/_tasks/CODE_*_PENDING.md` (YAML schema + 7 legal transitions)
2. **`scripts/autopoll_state.py`** helper module (~150 LOC: `read_state`, `transition_state`, `heartbeat`, `find_stale_claims`, `push_state_transition`)
3. **Slack push wiring** — reuses `outputs/slack_notifier.post_to_channel` (NO edits to slack_notifier; only IMPORT)
4. **`_ops/processes/b-code-autopoll-protocol.md`** — Phase 1-7 + hard rules (B-code reads on every wake)
5. **`_ops/processes/b-code-autopoll-startup.md`** — Director's paste-blocks for b2/b3/aihead1
6. **Lesson #50** appended to `tasks/lessons.md` (Lesson #48 window-scoped exception)

**Mailbox retrofit** of `CODE_2_PENDING.md` + `CODE_3_PENDING.md` is **deferred** — those B-codes have current dispatches; AI Head A handles retrofit post-merge directly. **You do NOT touch those files.**

## Critical pre-build EXPLORE (Lesson #44 + #47)

Before writing a line of code:

1. Read `briefs/BRIEF_B_CODE_AUTOPOLL_1.md` end-to-end (committed at `8ca8b7e`).
2. `grep -n "def post_to_channel" outputs/slack_notifier.py` — verify signature `(channel_id: str, text: str) -> bool` at line 111. Brief cites this; if signature drifts, flag and stop.
3. `grep -n "D0AFY28N030\|cockpit_channel_id" config/settings.py outputs/slack_notifier.py` — verify Director DM constant + cockpit channel default.
4. Confirm `pyyaml` in `requirements.txt` (`grep -i pyyaml requirements.txt`). If missing, add it.
5. `python3 -c "import yaml; print(yaml.__version__)"` from `~/bm-b1` to confirm yaml available locally.

## Files to modify

Create:
- `scripts/autopoll_state.py` — implement per brief §"Fix/Feature 2" + §"Fix/Feature 3" (push helper folds in)
- `tests/test_autopoll_state.py` — ≥12 pytest cases per brief §"Quality Checkpoints" #1
- `_ops/processes/b-code-autopoll-protocol.md` — full skeleton per brief §"Fix/Feature 4"
- `_ops/processes/b-code-autopoll-startup.md` — paste-blocks per brief §"Fix/Feature 5"

Update:
- `briefs/_tasks/README.md` — document state machine
- `tasks/lessons.md` — APPEND Lesson #50 (verbatim block in brief §"Fix/Feature 6")

## Files NOT to touch

Per brief §"Do NOT Touch":
- `_ops/processes/b-code-dispatch-coordination.md` — cold-start §2 still applies
- `outputs/slack_notifier.py` — only IMPORT `post_to_channel`; zero edits
- `config/settings.py` — reuse `cockpit_channel_id`; new `BAKER_OVERNIGHT_CHANNEL_ID` read via `os.getenv` directly
- `briefs/_tasks/CODE_2_PENDING.md` / `CODE_3_PENDING.md` / `CODE_4_PENDING.md` / `CODE_5_PENDING.md` — leave alone; AI Head A retrofits later
- Any production Cortex / capability / sentinel code
- `triggers/embedded_scheduler.py` — autopoll runs in B-code Claude session, not Render-side cron

## Ship gate (literal pytest mandatory — Lesson #34)

```bash
cd ~/bm-b1
pytest tests/test_autopoll_state.py -v 2>&1 | tail -40
```

Paste literal stdout into ship report. ≥12 tests pass. **NO "by inspection."**

Run also:
```bash
python3 -c "import py_compile; py_compile.compile('scripts/autopoll_state.py', doraise=True)"
```
Exit 0 required.

## Verification

Per brief §"Quality Checkpoints" 1-10. Items 1, 2, 6, 7, 8 are non-negotiable. Item 9 (PR description content) and item 10 (`/security-review`) are AI Head A's responsibility, not yours — but format your PR description so item 9 is satisfiable (include Q1-Q8 default values + Lesson #50 quote + confirmation Lesson #48 not removed).

Post-merge dry-run (brief §"Verification") — AI Head A runs after merge. You don't.

## Process

1. `cd ~/bm-b1 && git checkout main && git pull -q` (verify on `8ca8b7e` after this dispatch lands)
2. `git checkout -b b-code-autopoll-1`
3. EXPLORE per "Critical pre-build EXPLORE" above
4. Implement F1-F6 in order. F1 (frontmatter spec) is just doc; F2+F3 are the Python; F4-F5 are protocol docs; F6 is lesson append.
5. Write tests at `tests/test_autopoll_state.py` (≥12 cases — see brief §"Verification" for F2)
6. Run ship gate (literal pytest)
7. Syntax check `scripts/autopoll_state.py`
8. Commit + push, open PR titled `B_CODE_AUTOPOLL_1: state machine + autopoll protocol + paste-block startup docs`
9. PR description format:

   ```
   ## Summary
   - <bullet 1: state machine + Lesson #50>
   - <bullet 2: helper + tests + Slack wiring>
   - <bullet 3: 2 process docs (protocol + startup)>

   ## Q1-Q8 defaults locked (Director ratified 2026-04-27)
   Q1=900s, Q2=both, Q3=multi-stage, Q4=both, Q5=60min, Q6=LWW, Q7=B2+B3 first overnight, Q8=#48 window-scoped.

   ## Lesson #50
   <verbatim block from brief §"Fix/Feature 6">

   ## Ship gate
   <literal pytest stdout>

   Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   ```

10. Write ship report at `briefs/_reports/B1_b_code_autopoll_1_20260427.md` with literal pytest stdout + brief Quality Checkpoints 1-8 each filled in.
11. Mark this mailbox `status: COMPLETE` (manual edit — autopoll helper isn't live yet) on PR-merge per §3 hygiene.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Lane rule

- This is process + small Python; not Cortex feature work.
- B3 is on BAKER_MCP_EXTENSION_1 (different scope, no overlap).
- B2 just shipped WIKI_LINT_1 — idle.
- AI Head A (me) shares `~/bm-b1` with you tonight (atypical setup). I will avoid `git` ops while you build. If you need me to commit something on your behalf, surface in chat.

— AI Head A (Build-lead)
