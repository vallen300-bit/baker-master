# CODE_2_PENDING — PM_SIDEBAR_STATE_WRITE_1 — 2026-04-23

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Brief:** `briefs/BRIEF_PM_SIDEBAR_STATE_WRITE_1.md` (baker-master main commit `1abdc52`)
**Target PR:** new branch `feature/pm-sidebar-state-write-1`
**Complexity:** Medium (~3-5h)

**Supersedes:** prior `STEP5_EMPTY_DRAFT_INVESTIGATION_1` task (shipped as PR #42, merged 2026-04-23). Mailbox reset.

---

## Phase 1 of AO PM Continuity Program — Director ratified 2026-04-23

Source artefact: `_ops/ideas/2026-04-23-ao-pm-continuity-program.md` (baker-vault commit `f9f07a4`). Part H Amendment landed in canonical template + AI Head SKILL Rule 10 (baker-vault commit `dcf1c4f`). **This is the first brief authored under Amendment H — Part H §H1–H5 audit is filled inline in the brief.**

**Anchor incident:** 2026-04-23 Director discovered sidebar-door write-loop gap in live use. AO PM's Aukera thread (conversation_memory ids 397-399, high-value Patrick-warning / 1.5M / App 8 facts) is currently RAG-retrievable only; zero state extracted. This brief closes the gap AND backfills 14 days of missing extractions.

---

## Working-tree setup (B2)

Your local is 11 commits behind main — rebase first:

```bash
cd ~/bm-b2 && git fetch origin && git pull --rebase origin main
git checkout -b feature/pm-sidebar-state-write-1
```

---

## What you implement (6 deliverables — full spec in brief)

Read `briefs/BRIEF_PM_SIDEBAR_STATE_WRITE_1.md` end-to-end before starting. Summary here is orientation, not a substitute.

| Deliverable | Scope |
|---|---|
| **D1** | Refactor `_auto_update_pm_state` into module-level public `extract_and_update_pm_state(pm_slug, question, answer, mutation_source='auto', conversation_id=None)` in `orchestrator/capability_runner.py` — insert after PM_REGISTRY closing brace (line 185) / before `extract_correction_from_feedback` (line 188). Preserve CROSS-PM-SIGNALS block verbatim. |
| **D2** | Sidebar fast-path hook (`outputs/dashboard.py` `_scan_chat_capability` after line 8121) + delegate-path hook (after line 8184). Both fire-and-forget via `threading.Thread(daemon=True)`. Only triggers for `cap.slug in PM_REGISTRY`. |
| **D3** | Project labeling fix — mutate `req.project = cap.slug` when routed capability is in PM_REGISTRY (dashboard.py inside `_scan_chat_capability`, after cap_slugs assignment at :8012). |
| **D4** | `_ensure_pm_backfill_processed_table` DDL in `memory/store_back.py` (adjacent to `_ensure_scheduler_executions_table` at :544, wired into `__init__` adjacent to :151) + new `scripts/backfill_pm_state.py`. PRIMARY KEY (pm_slug, conversation_id). `ON CONFLICT DO NOTHING`. |
| **D5** | Read-only Part H §H1 audit of all 22 capabilities. Grep invocation paths per slug, classify surface + read/write state, write report to `briefs/_reports/PART_H_CAPABILITY_AUDIT_20260423.md`. Must cover `COUNT(*) FROM capability_sets` (22 per current schema). |
| **D6** | Trigger 3 relevance-on-ingest sentinel. Add `push_slack: bool = False` parameter to `flag_pm_signal` in `orchestrator/pm_signal_detector.py:118`. Wire `detect_relevant_pms_meeting + flag_pm_signal(push_slack=True)` after EVERY `store_meeting_transcript(...)` call: `triggers/fireflies_trigger.py:330, :513, :609` (3 sites), `triggers/plaud_trigger.py:350, :519` (2 sites), `triggers/youtube_ingest.py:223` (1 site). `post_to_channel` verified present at `outputs/slack_notifier.py:111`. |

---

## Mandatory compliance — AI Head SKILL Rules

You WILL fail review if any of these are missed:

- **Rule 7 (file:line verify):** every citation in your code must reference a line that exists and contains what you claim. Brief cites are already verified by AI Head; mirror exactly.
- **Rule 8 (singleton pattern):** every `SentinelStoreBack` instantiation uses `._get_global_instance()`. Pre-push hook `scripts/check_singletons.sh` enforces.
- **Rule 10 (Part H):** this brief already contains the Part H audit inline — do NOT strip it from the PR description. The audit report file (D5) is its own PR-scope file.
- **`conn.rollback()` in every `except` touching conn** (python-backend rules).
- **LIMIT on every SQL** — brief uses `LIMIT 500` on backfill, `LIMIT 1` / `LIMIT 3` on verification queries. Preserve.
- **Never batch LLM migrations** (lesson #13) — this brief doesn't migrate, but if you touch extraction call site, keep client↔model↔response triple matched (`claude-opus-4-6` + `claude.messages.create` + `resp.content[0].text`).

---

## Acceptance criteria (testable)

After your implementation, these must all pass:

### Syntax + hooks
```bash
$ python3 -c "import py_compile; \
  [py_compile.compile(f, doraise=True) for f in [
    'orchestrator/capability_runner.py',
    'outputs/dashboard.py',
    'memory/store_back.py',
    'scripts/backfill_pm_state.py',
    'orchestrator/pm_signal_detector.py',
    'triggers/fireflies_trigger.py',
    'triggers/plaud_trigger.py',
    'triggers/youtube_ingest.py',
  ]]; print('OK')"
OK

$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### Unit tests (ship gate)
```bash
$ python3 -m pytest tests/test_pm_state_write.py -v
```

Minimum 5 tests, all green. Per brief §Ship Gate:
1. `test_extract_and_update_pm_state_tags_mutation_source` — mutation_source propagates to store call
2. `test_sidebar_hook_fires_on_ao_pm` — hook called when cap.slug='ao_pm'
3. `test_sidebar_hook_skipped_for_non_pm_capability` — hook NOT called when cap.slug='finance'
4. `test_backfill_idempotency_skips_processed_rows` — second run of backfill over same rows is a no-op
5. `test_flag_pm_signal_push_slack_only_when_requested` — push_slack=False does NOT call post_to_channel; push_slack=True does

Stretch (bonus but not required):
6. `test_cross_surface_continuity_via_decomposer` — §H5 acceptance test automatable subset

### Full-suite regression delta
```bash
$ python3 -m pytest 2>&1 | tail -3
# Branch passes must be >= main passes + N (where N = your new tests)
# Branch failures MUST EQUAL main failures (zero regressions)
```

Compare against main at `1abdc52` (PR merge base). Record both numbers in your CODE_2_RETURN.md.

### Scope discipline
- Files modified must match brief §Files Modified list. No drift.
- Files in §Do NOT Touch must show zero diff lines.
- Do NOT touch `triggers/email_trigger.py:865-869` or `triggers/waha_webhook.py` signal detection blocks — those keep `push_slack=False` default.

---

## Dispatch protocol

1. Pull main on your working tree (above).
2. Branch `feature/pm-sidebar-state-write-1`.
3. Read the brief in full before first commit.
4. Commit per deliverable OR one final commit — your call. Use the standard `Co-Authored-By` trailer.
5. Push branch + open PR. PR title: `PM_SIDEBAR_STATE_WRITE_1: sidebar state-write + 14d backfill + Trigger 3`. PR body: the brief's §Scope table + your ship-gate literal output.
6. Ship report: `briefs/_reports/CODE_2_RETURN.md` on your branch (AI Head will read via `git show origin/feature/pm-sidebar-state-write-1:briefs/_reports/CODE_2_RETURN.md`). Standard 8-check format per prior returns.
7. Tag AI Head #2 in PR body: `@ai-head-2 ready for review`.

AI Head #2 runs `/security-review` + merges on APPROVE + green ship gate (Tier A). Then executes post-merge sequence per brief §Post-merge sequence (backfill run + verification SQL + Slack push to Director).

---

## Non-blocking side observation (FYI, not your problem)

During Part H §H1 enumeration you may notice `orchestrator/agent.py:2031` writes `update_pm_project_state(pm_slug, updates, summary)` without a `mutation_source` kwarg — it defaults to `'auto'`. That's a minor Part H §H4 tag-hygiene gap but NOT in this brief's scope. Note it in CODE_2_RETURN.md under "observations for follow-up" and keep moving.

---

## Hard deadline

None declared — Phase 1 ship unlocks Phase 2 brief authoring. Director's ratified sequencing: 0→1→2 sequential. No pressure but no delay either.

— AI Head #2
