---
status: PENDING
dispatched_at: 2026-05-25T09:00:00Z
dispatched_by: lead
target: b3
brief: briefs/BRIEF_GMAIL_SEARCH_AND_READ_1.md
brief_id: GMAIL_SEARCH_AND_READ_1
extends: GMAIL_ATTACHMENT_READ_2 (PR #257, squash 89008e0a — merged 2026-05-24 23:16:47Z; capability live 2026-05-25 08:28Z post retry-deploy)
target_repo: baker-master (single repo)
matter_slug: baker-internal
working_branch_baker_master: b3/gmail-search-and-read-1
working_dir_baker_master: ~/bm-b3
reply_to: lead
also_cc: deputy
priority: HIGH (Director-ratified 2026-05-25 ~09:00Z chat: "go" — give desks full Gmail reach ahead of recurring future need + Tuesday LG Wien filing window)
estimated_time: 3-5h
trigger_class: SMALL-MEDIUM
anchor_bus: lead bus #997 (audit-trail/gmail-attachment-read-2-shipped) + #1004 (gate-chain/gmail-attachment-read-2-scheduler-correction)
gate_chain:
  gate_1_architecture_review: REQUIRED (deputy, light — two new MCP tools mirroring proven READ_2 pattern, same OAuth singleton, no new credential surface)
  gate_2_security_review: REQUIRED — expected NO_FINDINGS (no new auth/credential surface; reuses _get_gmail_service; search query is parameterized into Gmail API `q=` not concatenated into shell/SQL/eval)
  gate_3_picker_architect: SKIP (no agent-install pattern, no desk-picker SKILL.md changes wired in this brief — desks pick up new tools via auto MCP tools/list)
  gate_4_code_reviewer_2nd_pass: REQUIRED (deputy feature-dev:code-reviewer — verify (a) the 12 EXISTING attachment_read tests still pass after the factory rewrite [regression guard], (b) all 12 new mocked cases assert what their names claim, (c) hard caps enforced both schema + server-side, (d) per-message metadata-fetch errors are non-fatal)
  gate_5_lead_merge: REQUIRED
ui_surface_prebrief: brief §Surface contract = N/A (pure backend MCP tool — no UI surface) — gate satisfied
director_q_locks:
  - q1_cap_max_results: 50 hard, default 20. Lead recommendation — locked. Why: 50 results × 5 quota units (metadata fetch) + 5 units (list call) = 255 units against Gmail's 250/sec per-user limit. Sequential loop is the rate-limit guardrail.
  - q2_body_text_cap: 50,000 chars + truncation marker, `body_truncated` boolean field. Lead recommendation — locked. Why: long forwarded threads otherwise blow caller token budgets.
  - q3_attachment_bytes_in_read_message: NO. Read returns metadata only ({filename, mime_type, size}); bytes via existing `baker_gmail_attachment_read`. Lead recommendation — locked. Why: split responsibilities, don't double-source attachment delivery.
  - q4_metadata_fetch_failure_handling: NON-FATAL per-message. Failed metadata entry includes `error` field, search returns all other matches. Lead recommendation — locked. Why: one rate-limited / deleted message must not poison the whole search response.
  - q5_e2e_gating: skipif TEST_GMAIL_LIVE != "1" (mirror READ_2 pattern). CI auto-skip; b3 runs locally pre-merge if creds present, else lead runs post-merge. Lead recommendation — locked.
prior_mailbox_state: CODE_3 COMPLETE on GMAIL_ATTACHMENT_READ_2 (PR #257 merged 2026-05-24 23:16:47Z, squash 89008e0a; live 2026-05-25 08:28Z; E2E PASS lead-side against hag-desk fixture). This file overwrites the prior PENDING state.
---

# CODE_3_PENDING — GMAIL_SEARCH_AND_READ_1 — 2026-05-25

**Brief:** `briefs/BRIEF_GMAIL_SEARCH_AND_READ_1.md`
**Target repo:** baker-master (single repo)
**Working dir:** `~/bm-b3` (baker-master)
**Pre-requisites:** READ_2 already merged + live (PR #257 squash `89008e0a`); Baker Gmail OAuth env live on Render (verified live 2026-05-25 08:28Z via E2E PASS against hag-desk fixture). Same env vars (`BAKER_GMAIL_CLIENT_ID`, `BAKER_GMAIL_CLIENT_SECRET`, `BAKER_GMAIL_REFRESH_TOKEN`). For local E2E run: same env vars in b3's shell.

## Bottom line

After READ_2 shipped, desks can pull a Gmail attachment IF they already know the message_id + filename. They cannot SEARCH Gmail and they cannot READ a message body via MCP. They currently get message_ids only via the auto-poll pipeline (5-min lag + noise filters drop counterparty mail) or Director paste-in.

This brief adds two MCP tools — `baker_gmail_search` (wraps `messages.list` with Gmail's full query syntax, returns metadata for ≤50 matches) and `baker_gmail_read_message` (wraps `messages.get(format=full)`, returns headers + body_text + attachment metadata). Both reuse the same OAuth singleton and dispatch table as READ_2. The combined tool surface (search + read body + read attachment) gives desks full Gmail reach.

Continues lesson-211 anti-pattern guard: 2 new gated real-Gmail E2E tests + 1 gated E2E carried from READ_2 = 3 total. Every Gmail-surface change must exercise a live-Gmail call before claiming green.

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b3 && git fetch origin main && git checkout main && git pull --ff-only`
2. `cd ~/bm-b3 && git checkout -b b3/gmail-search-and-read-1`
3. `git config core.hooksPath .githooks` (verify configured)
4. Confirm canonical brief on main: `git show main:briefs/BRIEF_GMAIL_SEARCH_AND_READ_1.md | head -10` should return frontmatter.
5. Read brief end-to-end. The 3-fix structure + per-test-case adjustments are all there; this PENDING is the dispatch envelope, not a re-summary.

## Scope (3 fixes per brief)

1. **Fix 1 — `tools/gmail.py` (search tool)**
   - +1 Tool entry in `GMAIL_TOOLS` (`baker_gmail_search`)
   - +1 dispatch branch in `dispatch_gmail()`
   - +1 internal function `_search()` (~90 LOC)
   - Hard cap `_SEARCH_MAX_RESULTS_HARD_CAP = 50` constant
   - Sequential N+1 metadata fetch (DO NOT parallelize — rate-limit guardrail)
   - Non-fatal per-message metadata errors

2. **Fix 2 — `tools/gmail.py` (read_message tool)**
   - +1 Tool entry in `GMAIL_TOOLS` (`baker_gmail_read_message`)
   - +1 dispatch branch in `dispatch_gmail()`
   - +1 internal function `_read_message()` (~60 LOC)
   - Body cap `_BODY_TEXT_CAP_CHARS = 50_000` + truncation marker + `body_truncated` boolean
   - Attachment metadata only — bytes via existing READ_2 tool

3. **Fix 3 — tests**
   - `git mv tests/test_gmail_attachment_read.py tests/test_gmail.py` (preserve history)
   - Extend `_build_service_mock()` factory: add `list_response`, `list_raises`, `metadata_responses`, `metadata_raises`, `full_message_response`, `full_message_raises` kwargs + format-aware `get()` router (~60 LOC delta)
   - **REGRESSION GUARD STEP — run `pytest tests/test_gmail.py -v -k attachment_read` AFTER the factory rewrite, BEFORE adding new tests. Must show 12 passed, 1 skipped. If any of the 12 attachment_read tests fail, fix the factory before continuing.**
   - +6 mocked cases for `baker_gmail_search` (Fix 3c table)
   - +6 mocked cases for `baker_gmail_read_message` (Fix 3d table)
   - +2 gated E2E tests (`test_e2e_real_gmail_search`, `test_e2e_real_gmail_read_message`)
   - Update module docstring to reflect 24 mocked + 3 gated E2E

## Hard constraints

- **Do NOT modify** `scripts/extract_gmail.py`, `baker_mcp/baker_mcp_server.py`, `triggers/email_trigger.py`, `outputs/dashboard.py`. Reuse via import only. Name-based registration auto-picks-up new tools.
- **No new 1Password items, no new Render env vars.** Lesson #70.
- **`max_results` hard cap = 50 at BOTH layers:** schema (`maximum: 50`) AND server-side defensive clamp (`_SEARCH_MAX_RESULTS_HARD_CAP`).
- **DO NOT parallelize the search metadata fetch loop, DO NOT swap to Gmail batchRequest, DO NOT cache.** Premature optimization. v1 ships sequential; complexity added only on real load signal.
- **DO NOT add `include_bytes` flag to `baker_gmail_read_message`.** Bytes responsibility stays with `baker_gmail_attachment_read`. Single source per concern.
- **E2E tests MUST be skipif-gated** on `TEST_GMAIL_LIVE=1`. CI must continue to pass without setting the var.
- **No "by inspection"** — literal pytest output (24 passed, 3 skipped) required in PR description.
- **Factory rewrite is the breaking-change zone.** Run regression guard before any new test is added; if attachment_read tests fail, factory is wrong, fix before continuing.

## Acceptance criteria

Per brief §Quality Checkpoints (numbered 1-11). Highlights:

- **AC1:** `pytest tests/test_gmail.py -v` → literal output `24 passed, 3 skipped`. Paste in PR body.
- **AC2:** `pytest tests/test_gmail.py -v -k attachment_read` → literal output `12 passed, 1 skipped` (regression guard).
- **AC3:** `python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"` clean.
- **AC4:** `python3 -c "from baker_mcp.baker_mcp_server import GMAIL_TOOL_NAMES; print(sorted(GMAIL_TOOL_NAMES))"` returns `['baker_gmail_attachment_read', 'baker_gmail_read_message', 'baker_gmail_search']`.
- **AC5:** Both new tools' `inputSchema` validate (Fix 1a / Fix 1a inline schemas).
- **AC6:** `_SEARCH_MAX_RESULTS_HARD_CAP = 50` and `_BODY_TEXT_CAP_CHARS = 50_000` constants present in `tools/gmail.py`.
- **AC7:** Local E2E run pre-merge if possible — `TEST_GMAIL_LIVE=1 pytest tests/test_gmail.py -v -k e2e` → 3 PASS. If b3 cannot run locally, document SKIP + reason in ship report; lead runs E2E post-merge.
- **AC8:** `bash scripts/check_singletons.sh` clean.
- **AC9:** Render `/health` returns HTTP 200 post-deploy (note: body may read `"scheduler": "stopped"` on some calls due to known multi-worker health-visibility defect — that's pre-existing, not introduced by this PR; verify scheduler IS running by hitting `/health` 5×; ≥1 must return `"scheduler": "running"`).

## Ship gate

- Literal `pytest tests/test_gmail.py -v` output (24 passed, 3 skipped) in PR body
- Literal `pytest tests/test_gmail.py -v -k attachment_read` output (12 passed, 1 skipped) in PR body — regression guard
- Literal E2E test output (3 passed locally OR explicit skip-reason for each) in PR body + ship report
- Literal `bash scripts/check_singletons.sh` output in PR body
- `py_compile` clean on `tools/gmail.py`
- Tool-name registration smoke (`GMAIL_TOOL_NAMES` listing) clean

## Reporting (bus reply-to-sender)

One PR to open. Title: `GMAIL_SEARCH_AND_READ_1: baker_gmail_search + baker_gmail_read_message MCP tools`. Bus-post `lead` (deputy CC) on PR open:

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/gmail-search-and-read-1 — baker-master PR #<N> open; tools/gmail.py +X LOC + tests/test_gmail.py +Y LOC (renamed from test_gmail_attachment_read.py); AC1 24 passed + 3 skipped; AC2 regression-guard 12+1 PASS; AC7 E2E <3 PASS local|SKIPPED reason>; tool count 47 → 49 expected post-deploy; awaiting deputy gate chain (1+2+4) then lead merge." \
  ship/gmail-search-and-read-1
```

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh deputy \
  "ship/gmail-search-and-read-1 — same as ship-post to lead; gate-chain pickup ready (gates 1 + 2 + 4 required; gate 3 skip)" \
  ship-cc/gmail-search-and-read-1
```

Lead runs Gate-5 merge after deputy PASS verdict. Post-merge: Render auto-deploys; lead curls live MCP for `tools/list` (assert 49 tools, both new tool names present) + sanity calls (`baker_gmail_search` with `from:me`, `baker_gmail_read_message` with a returned msg id); buses desks via SKILL.md update path on capability-live.

## References

- Brief: `briefs/BRIEF_GMAIL_SEARCH_AND_READ_1.md` (full implementation steps + 24 mocked-test specs + 2 E2E)
- Predecessor brief: `briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md` (READ_2 — proven pattern this brief extends)
- READ_2 PR: #257 (squash `89008e0a`) — merged 2026-05-24 23:16:47Z; live 2026-05-25 08:28Z
- READ_2 ship report: `briefs/_reports/B3_gmail_attachment_read_2_20260525.md`
- Anchor bus: lead #997 (READ_2 audit-trail) + #1004 (READ_2 scheduler-correction)
- Lessons reference: `tasks/lessons.md:211` (mocked-only tests shipped broken — same pattern bit READ_1; 3 E2E tests in this brief continue the structural fix)
- Gmail query syntax: https://support.google.com/mail/answer/7190
- Director directive 2026-05-25 ~09:00Z: "give desks full Gmail reach" + ~3-5h time estimate ratification

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Given ~3-5h scope, expect 0-1 heartbeats.
