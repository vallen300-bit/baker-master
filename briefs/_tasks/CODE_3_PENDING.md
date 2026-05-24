---
status: PENDING
dispatched_at: 2026-05-24T22:55:00Z
dispatched_by: lead
target: b3
brief: briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md
brief_id: GMAIL_ATTACHMENT_READ_2
amends: GMAIL_ATTACHMENT_READ_1 (PR #256, squash f030344)
target_repo: baker-master (single repo)
matter_slug: baker-internal
working_branch_baker_master: b3/gmail-attachment-read-2
working_dir_baker_master: ~/bm-b3
reply_to: lead
also_cc: deputy
priority: HIGH (Director-ratified 2026-05-24 ~22:55Z chat: "go")
estimated_time: 2-3h
trigger_class: SMALL
anchor_bus: deputy bus #973 (post-deploy/ac5-fail-architectural)
gate_chain:
  gate_1_architecture_review: REQUIRED (deputy, light — input-contract change only, no new credential surface)
  gate_2_security_review: REQUIRED — expected NO_FINDINGS (no new auth/credential surface; reuses existing Gmail OAuth from READ_1)
  gate_3_picker_architect: SKIP (no agent-install pattern)
  gate_4_code_reviewer_2nd_pass: REQUIRED (deputy feature-dev:code-reviewer — verify 12 mocked test cases + 1 gated E2E assert what their names claim; verify match_count + attachment_index fields populated)
  gate_5_lead_merge: REQUIRED
ui_surface_prebrief: brief §Surface contract = N/A (pure backend MCP tool — no UI surface) — gate satisfied
director_q_locks:
  - q1_match_semantics: case-sensitive exact filename match (Gmail preserves casing). Lead recommendation — locked.
  - q2_duplicate_filename_handling: 1-based attachment_index tiebreaker, default 1, error on out-of-range with match_count surfaced. Lead recommendation — locked.
  - q3_e2e_gating: skipif TEST_GMAIL_LIVE != "1"; CI auto-skip; b3 runs locally pre-merge with fixture env vars. Lead recommendation — locked.
prior_mailbox_state: CODE_3 COMPLETE on GMAIL_ATTACHMENT_READ_1 (PR #256 merged 2026-05-24 21:10Z, squash f030344). This file overwrites the prior COMPLETE state.
---

# CODE_3_PENDING — GMAIL_ATTACHMENT_READ_2 — 2026-05-24

**Brief:** `briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md`
**Target repo:** baker-master (single repo)
**Working dir:** `~/bm-b3` (baker-master)
**Pre-requisites:** READ_1 already merged + live (PR #256 squash `f030344`); Baker Gmail OAuth env live on Render post env-var DELETE redeploy (`BAKER_GMAIL_CLIENT_ID`, `BAKER_GMAIL_CLIENT_SECRET`, `BAKER_GMAIL_REFRESH_TOKEN`). For local E2E run: same three env vars in b3's shell.

## Bottom line

READ_1 shipped a tool that doesn't work for autonomous agent callers. Gmail attachment IDs are OAuth-session-scoped — they can only be resolved in the session that minted them. Agents that get an attachment_id from `claude_ai_Gmail` cannot use it against baker's Gmail session, and vice-versa. All 10 ship tests were mocked; the architectural defect surfaced only post-deploy when deputy ran a real Gmail call (bus #973).

This brief swaps the input contract from `attachment_id` to `filename`. Tool resolves the session-valid attachment ID internally by walking `messages.get(format=full)` parts and matching by filename. Optional `attachment_index` (1-based) is the tiebreaker for the rare same-filename case. Adds 1 real-Gmail E2E test gated on `TEST_GMAIL_LIVE=1` so future ship gates cannot pass on mocks alone for this surface.

Hag-desk LG Wien Forderungsanmeldung filing deadline: 2026-05-26/27. Manual Director-pull workaround runs in parallel — Tuesday filing is NOT bet on READ_2 shipping in time. But if anything goes right, capability is live before filing.

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b3 && git fetch origin main && git checkout main && git pull --ff-only`
2. `cd ~/bm-b3 && git checkout -b b3/gmail-attachment-read-2`
3. `git config core.hooksPath .githooks` (verify configured)
4. Confirm canonical brief on main: `git show main:briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md | head -10` should return frontmatter.

## Scope (2 fixes per brief)

1. **Fix 1 — `tools/gmail.py`**
   - Replace `inputSchema` (`attachment_id` → `filename` + `attachment_index`)
   - Rewrite `_attachment_read()` body — match by filename, resolve session-valid attachmentId from the matched part, then download. Full Python in brief §Fix 1 §Implementation (copy-pasteable).
   - ~80 LOC delta.

2. **Fix 2 — `tests/test_gmail_attachment_read.py`**
   - Adapt 10 existing mocked cases to the new API (rename `attachment_id` args → `filename`; assert `match_count` + `attachment_index` fields).
   - Add 2 new mocked cases: `test_duplicate_filenames_with_index`, `test_attachment_index_out_of_range`.
   - Add 1 gated real-Gmail E2E test (`test_e2e_real_gmail_attachment_read`) — skipif on `TEST_GMAIL_LIVE != "1"`. Full Python + per-case adjustments in brief §Fix 2.
   - Update file docstring (lines 1-23) to reflect new layout: "12 cases + 1 gated E2E test."
   - ~150 LOC delta.

## Hard constraints

- **Do NOT modify** `scripts/extract_gmail.py`, `baker_mcp/baker_mcp_server.py`, `triggers/email_trigger.py`, `tools/ingest/extractors.py`, `outputs/dashboard.py`. Reuse via import only.
- **No new 1Password items, no new Render env vars.** Lesson #70.
- **Filename match MUST be case-sensitive exact.** Gmail preserves casing; loose matching hides bugs.
- **Walk order for attachment_index MUST be deterministic** — the order `_collect_attachment_parts()` returns (depth-first via existing recursion in `scripts/extract_gmail.py:601-615`). Do not re-sort.
- **E2E test MUST be skipif-gated** on `TEST_GMAIL_LIVE=1`. CI must continue to pass without setting the var.
- **No "by inspection"** — literal pytest output (12 passed, 1 skipped) required in PR description.

## Acceptance criteria

Per brief §Quality Checkpoints (numbered 1-7). Highlights:

- AC1: `pytest tests/test_gmail_attachment_read.py -v` → literal output `12 passed, 1 skipped`. Paste in PR body.
- AC2: `python3 -c "import py_compile; py_compile.compile('tools/gmail.py', doraise=True)"` clean.
- AC3: `python3 -c "from baker_mcp.baker_mcp_server import GMAIL_TOOL_NAMES; print(sorted(GMAIL_TOOL_NAMES))"` returns `['baker_gmail_attachment_read']`.
- AC4: Local E2E run pre-merge — `TEST_GMAIL_LIVE=1 E2E_GMAIL_MESSAGE_ID=<id> E2E_GMAIL_FILENAME=<name> pytest tests/test_gmail_attachment_read.py::test_e2e_real_gmail_attachment_read -v` → 1 PASS. If b3 cannot run locally (Gmail OAuth env missing in b3 shell), document SKIP + reason in ship report; lead runs E2E post-merge.
- AC5: `bash scripts/check_singletons.sh` clean.
- AC6: Tool `inputSchema` validates `message_id` + `filename` required; `attachment_index` optional integer ≥ 1 default 1.
- AC7: Render `/health` returns 200 post-deploy.

## E2E fixture selection (mandatory pre-merge step for b3)

```sql
SELECT source_path FROM documents
WHERE source_path LIKE 'email:%/%.pdf'
ORDER BY ingested_at DESC LIMIT 1;
```

Run via `psql "$DATABASE_URL"`. Output looks like `email:19e2c1b1e2bdd4c0/Schadensblatt-Top4.pdf`. Extract `E2E_GMAIL_MESSAGE_ID` = substring before `/`, `E2E_GMAIL_FILENAME` = substring after `/`. Note the chosen pair in the ship report.

## Ship gate

- Literal `pytest tests/test_gmail_attachment_read.py -v` output (12 passed, 1 skipped) in PR body
- Literal E2E test output (1 passed) OR explicit skip reason in PR body + ship report
- Literal `bash scripts/check_singletons.sh` output in PR body
- `py_compile` clean on `tools/gmail.py`
- Tool-name registration smoke (`GMAIL_TOOL_NAMES` listing) clean

## Reporting (bus reply-to-sender)

One PR to open. Title: `GMAIL_ATTACHMENT_READ_2: filename-based API + real-Gmail E2E coverage`. Bus-post `lead` (deputy CC) on PR open:

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/gmail-attachment-read-2 — baker-master PR #<N> open; tools/gmail.py +X LOC + tests/test_gmail_attachment_read.py +Y LOC; AC1 12 passed + 1 skipped; AC4 E2E <PASS|SKIPPED reason>; fixture msg <id> / file <name>; awaiting deputy gate chain (1+2+4) then lead merge." \
  ship/gmail-attachment-read-2
```

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh deputy \
  "ship/gmail-attachment-read-2 — same as #N to lead; gate-chain pickup ready" \
  ship-cc/gmail-attachment-read-2
```

Lead runs Gate-5 merge after deputy PASS verdict. Post-merge: Render auto-deploys; lead curls live MCP tool against fixture pair to confirm capability; buses hag-desk on capability-live.

## References

- Brief: `briefs/BRIEF_GMAIL_ATTACHMENT_READ_2.md` (full implementation steps + 12 test cases + 1 E2E)
- Anchor bus: deputy #973 (post-deploy/ac5-fail-architectural) 2026-05-24 22:17Z
- READ_1 PR: #256 (squash f030344) — merged but non-functional in practice
- READ_1 brief: `briefs/BRIEF_GMAIL_ATTACHMENT_READ_1.md` (background; do NOT re-read implementation — superseded by READ_2)
- Lessons reference: `tasks/lessons.md:211` (mocked-only tests shipped broken — same pattern bit READ_1; E2E gate in READ_2 is the structural fix)
- Hag-desk filing deadline: 2026-05-26/27 (LG Wien Forderungsanmeldung)

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Given ~2-3h scope, expect 0-1 heartbeats.
