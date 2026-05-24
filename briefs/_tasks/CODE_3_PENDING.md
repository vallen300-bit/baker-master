---
status: COMPLETE
completed_at: 2026-05-24T21:10:07Z
pr_url: https://github.com/vallen300-bit/baker-master/pull/256
completion_report: briefs/_reports/B3_GMAIL_ATTACHMENT_READ_1_20260524.md
brief: briefs/BRIEF_GMAIL_ATTACHMENT_READ_1.md
brief_id: GMAIL_ATTACHMENT_READ_1
target_repo: baker-master (single repo)
matter_slug: baker-internal
dispatched_at: 2026-05-24T15:50:00Z
dispatched_by: deputy (Director-ratified b3/b4 deputy lane 2026-05-24 chat)
target: b3
working_branch_baker_master: b3/gmail-attachment-read-1
working_dir_baker_master: ~/bm-b3
reply_to: lead
also_cc: deputy
priority: HIGH (Director-ratified "build now, live during sessions" 2026-05-24)
estimated_time: 2-3h
trigger_class: SMALL
gate_chain:
  gate_1_architecture_review: REQUIRED (deputy, light — pattern parity with ClaimsMax + Grok defensive-import block)
  gate_2_security_review: REQUIRED — expected NO_FINDINGS (no new auth/credential surface; reuses existing Gmail OAuth)
  gate_3_picker_architect: SKIP (no agent-install pattern)
  gate_4_code_reviewer_2nd_pass: REQUIRED (deputy feature-dev:code-reviewer, light — verify 10 test cases assert what their names claim)
  gate_5_lead_merge: REQUIRED
prior_mailbox_state: superseded — WRITE_BRIEF_SOP_ENFORCER_HOOK_1 shipped 2026-05-24 mid-morning via PR #253 (commit 915c075); b3 idle since
ui_surface_prebrief: brief §Surface contract = N/A (pure backend MCP tool — no UI surface) — gate satisfied
director_q_locks:
  - q1_include_bytes_default: false (text-only default; opt-in for bytes via include_bytes=true). Deputy recommendation — locked.
  - q2_image_scope_v1: text-extractable types only (pdf/docx/xlsx/csv/txt/md/json). Image support deferred to follow-up brief GMAIL_ATTACHMENT_READ_IMAGES_2. Deputy recommendation — locked.
---

# CODE_3_PENDING — GMAIL_ATTACHMENT_READ_1 — 2026-05-24

**Brief:** `briefs/BRIEF_GMAIL_ATTACHMENT_READ_1.md`
**Target repo:** baker-master (single repo)
**Working dir:** `~/bm-b3` (baker-master)
**Pre-requisites:** Gmail OAuth credentials already provisioned (Render Secret File `/etc/secrets/gmail_credentials.json` + `gmail_token.json`); existing polling pipeline operational. No new secrets, no new env vars.

## Bottom line

Director ratified 2026-05-24 "start building the capability to read attachments of emails now, live during sessions." Lead delegated authoring to deputy (bus #907). Director then ratified b3/b4 as deputy lane (chat "use b3 and b4, I will reserve b1 and b2 for lead").

Single-repo, ~80 LOC new + ~120 LOC tests, low complexity. Wraps existing poll-time attachment extractor (`scripts/extract_gmail.py:618 extract_attachments_text`) as a new on-demand MCP tool `baker_gmail_attachment_read`. Reuses Gmail OAuth singleton — no new credential surface. Pattern parity with ClaimsMax + Grok defensive-import blocks in `baker_mcp/baker_mcp_server.py:949-971`.

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b3 && git fetch origin main && git checkout main && git pull --ff-only` — sync baker-master.
2. `cd ~/bm-b3 && git checkout -b b3/gmail-attachment-read-1`
3. `git config core.hooksPath .githooks` (verify configured).
4. Confirm canonical brief is on main: `git show main:briefs/BRIEF_GMAIL_ATTACHMENT_READ_1.md | head -10` should return frontmatter.

## Scope (2 features per brief)

1. **Fix/Feature 1 — `tools/gmail.py` (NEW) + 2 edits to `baker_mcp/baker_mcp_server.py`**
   - `tools/gmail.py`: GMAIL_TOOLS + GMAIL_TOOL_NAMES + dispatch_gmail + _attachment_read (full Python in brief §Implementation Step 1.1, copy-pasteable).
   - `baker_mcp/baker_mcp_server.py`: defensive-import block after Grok block (around line 971); dispatch route in `_dispatch()` after Grok elif (around line 2127). Both snippets copy-pasteable in brief §Implementation Step 1.2.
2. **Fix/Feature 2 — `tests/test_gmail_attachment_read.py` (NEW)**
   - 10 cases covering: happy path text-only, happy path include_bytes, missing message_id, missing attachment_id, attachment_id not found, oversize (>10MB), unsupported extension (e.g. `.png` in v1), empty Gmail data response, Gmail API exception on message.get(), Gmail API exception on attachments.get().
   - Mirror mock-pattern from `tests/test_grok_client.py:450+`.
   - Cover EMAIL-ATTACH-FIX-1 path (nested multipart, forwarded email scenario) in at least 1 test.

## Hard constraints

- **Do NOT modify** `scripts/extract_gmail.py`, `triggers/email_trigger.py`, `tools/ingest/extractors.py`, `outputs/dashboard.py`. Reuse via import only.
- **No new 1Password items, no new Render env vars.** Per Lesson #70.
- **Sync tool, no internal asyncio** — matches ClaimsMax + Grok pattern.
- **Build per Director-Q locks** in frontmatter (Q1=text-only default, Q2=text-extractable types only). Do NOT relitigate; lead bus-pings you only if Director redirects in the 15-min window after dispatch.
- **No "by inspection"** — literal pytest output required in PR description.

## Acceptance criteria

Per brief §Quality Checkpoints (numbered 1-7). Highlights:
- AC1: `pytest tests/test_gmail_attachment_read.py -v` → 10/10 PASS, literal output in PR body.
- AC2: `from baker_mcp.baker_mcp_server import TOOLS; len(TOOLS)` incremented by 1 vs main.
- AC3: `bash scripts/check_singletons.sh` clean.
- AC4: py_compile clean on `tools/gmail.py` + `baker_mcp/baker_mcp_server.py`.
- AC5: Post-deploy live smoke (deputy will supply real message_id + attachment_id pair after deploy).
- AC6: Render `/health` returns 200 post-deploy.
- AC7: Tool listed in `tools/list` MCP response (curl in brief).

## Ship gate

- Literal `pytest tests/test_gmail_attachment_read.py -v` output (10/10 PASS) in PR body
- Literal `bash scripts/check_singletons.sh` output in PR body
- Literal tool-registration smoke output in PR body
- `bash -n` syntax clean on `tools/gmail.py`
- `py_compile` clean on `tools/gmail.py` + `baker_mcp/baker_mcp_server.py`

## Reporting (bus reply-to-sender)

One PR to open. Bus-post `lead` (with `deputy` CC) on PR open:

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh lead \
  "ship/gmail-attachment-read-1 — baker-master PR #<N> open; tools/gmail.py +X LOC + baker_mcp_server.py +Y LOC + tests/test_gmail_attachment_read.py +Z LOC; AC1-AC4+AC7 verified literal 10/10 PASS; awaiting deputy gate chain (1+2+4) then lead merge." \
  ship/gmail-attachment-read-1
```

```bash
BAKER_ROLE=b3 ~/bm-b3/scripts/bus_post.sh deputy \
  "ship/gmail-attachment-read-1 — same as #N to lead; gate-chain pickup ready" \
  ship-cc/gmail-attachment-read-1
```

`lead` runs Gate-5 merge after deputy PASS verdict. Post-merge: Render auto-deploys; deputy runs AC5 live smoke + AC7 tool-list curl.

## References

- Brief: `briefs/BRIEF_GMAIL_ATTACHMENT_READ_1.md` (full implementation steps + 10 test cases)
- Director ratification: chat 2026-05-24 "build now, live during sessions" + "use b3 and b4"
- Lead delegation: bus #907
- Hag-desk capability gap: bus #882
- Deputy → lead priority bump: bus #902
- Director (a)-then-(b) authorization: bus #888 (via hag-desk relay)
- ClaimsMax pattern reference: `baker_mcp/baker_mcp_server.py:949-960`
- Grok pattern reference: `baker_mcp/baker_mcp_server.py:962-971`
- Test mock-pattern reference: `tests/test_grok_client.py:450+`

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Given ~2-3h scope, expect 0-1 heartbeats.
