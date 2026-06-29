---
status: PENDING
brief_id: EMAIL_READ_REST_FALLBACK_1
to: b4
from: lead
dispatched_by: lead
dispatched_at: 2026-06-29
branch: email-read-rest-fallback-1
reply_target: lead (bus)
effort: medium
task_class: additive backend REST endpoints (read-only) + live-prod verification
gate_plan: G1 py_compile + grep no-dup-route -> codex gate-3 -> lead merge -> POST_DEPLOY_AC_VERDICT v1 to lead
full_brief: briefs/BRIEF_EMAIL_READ_REST_FALLBACK_1.md
---

# EMAIL_READ_REST_FALLBACK_1 — X-Baker-Key REST email search/read (MCP-drop fallback)

## Read this first
The complete, copy-pasteable implementation is in **`briefs/BRIEF_EMAIL_READ_REST_FALLBACK_1.md`** (on main, committed alongside this dispatch). Implement exactly as written there. This envelope carries only dispatch metadata + acceptance gates.

## Context (one paragraph)
On 2026-06-29 the claude.ai Baker MCP dropped mid-session in a desk picker → the desk was blind to brisengroup.com email while two live Balazs/Annaberg emails needed reading (bus #4588, Director-routed). Backend was healthy throughout. There is no REST email-read fallback today (only ingestion POSTs). This adds one, mirroring the proven `GET /api/whatsapp/messages` (PR #218). Director escalated to a session goal.

## Scope (locked — do NOT exceed)
- ADD exactly two routes to `outputs/dashboard.py` after the WhatsApp messages endpoint (~line 2624): `GET /api/emails/search` + `GET /api/emails/read`, both `Depends(verify_api_key)`.
- ADD two small md formatters (`_format_email_search_md`, `_format_email_read_md`).
- Logic is single-sourced from `tools.email.dispatch_email("baker_email_search"|"baker_email_read", {...})` — **write NO new SQL** against `email_messages` (its PK is `message_id`, the outlier table — lesson #211; keep that owned in `tools/email.py`).
- Read-only. No migrations, no new env vars, no new deps, no edits to `tools/email.py` or the WhatsApp endpoint.

## Acceptance criteria
- AC1: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` passes.
- AC2: `grep -nE '@app.get\("/api/emails/(search|read)"' outputs/dashboard.py` → exactly one each (no shadow — lesson #11).
- AC3: Live prod (post-deploy) — `GET /api/emails/search?query=Annaberg&format=md` with X-Baker-Key returns ≥1 match incl. the Balazs "Annaberg Status - Closing actions" email (message_id `...rb0De3zfU=`).
- AC4: Live prod — `GET /api/emails/read?message_id=<that id>&format=md` returns the body (or the `provider=graph` store-miss hint; `&provider=graph` then returns it).
- AC5: Auth gate — no X-Baker-Key → 401/403, never 200. Bad `provider=bogus` → 422.

## Done rubric
Build-done = PR merged + AC1/AC2 green. Arc-done = `POST_DEPLOY_AC_VERDICT v1` posted to lead with AC3-AC5 PASS (per `post-deploy-ac-bus-gate` SKILL). Two separate done-states — never conflate.

## Context-economy (HARD — no auto-compaction)
- Read ONLY: `briefs/BRIEF_EMAIL_READ_REST_FALLBACK_1.md`, the WhatsApp endpoint block (`outputs/dashboard.py:2543`) as template, `tools/email.py:897` `dispatch_email`. Do not read more of the 11.7k-line dashboard than needed.
- Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP.
