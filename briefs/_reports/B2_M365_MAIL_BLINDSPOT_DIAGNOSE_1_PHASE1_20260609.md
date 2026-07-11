# B2 — M365_MAIL_BLINDSPOT_DIAGNOSE_FIX_1 — Phase 1 (read-only diagnosis)

Date: 2026-06-09
Brief: `briefs/_tasks/CODE_2_PENDING.md` (dispatch 7526dff, from lead)
Phase: 1 of 2 — DIAGNOSIS ONLY. No code changed. STOP for lead greenlight before Phase 2.

## Bottom line

**Not an ingestion failure. It is a tool-surface routing bug + fail-silent UX.**
graph_mail IS ingesting Director's M365/Outlook mail into the store. The exact email
Director could not find (Spanyi, 6 Jun, hearing 10 Jun) is present and was ingested
2026-06-07. The blindspot is that `baker_gmail_search` is Gmail-OAuth-only — it queries
the dead legacy Gmail account and returns a silent empty for brisengroup mail.

## Evidence

### 1. Ingestion is LIVE (graph_mail healthy, auth clean)
- `trigger_watermarks` source `graph_mail_poll`: `last_seen = 2026-06-09 16:03:24` (advancing every cycle today).
- `check_new_graph_messages` (triggers/graph_mail_trigger.py:102) sets that watermark ONLY after a clean poll while `GraphClient.is_ready()` is True. is_ready() = `BAKER_USE_GRAPH=true AND creds present`. A 401/403/HTTP failure RAISES (poll_graph_mail:77,93) → report_failure → watermark NOT advanced. Advancing watermark ⇒ BAKER_USE_GRAPH is on, M365 cert auth is valid, polls succeed.

### 2. The store HAS the mail (Director's exact email)
Query: `email_messages` where sender `M.Spanyi@eh.at`:
```
sender_email: M.Spanyi@eh.at
subject:      Preparing for the hearing scheduled for 10 June 2026
received_date:2026-06-06 15:59:24+00   ingested_at: 2026-06-07 06:41:03
message_id:   AAQkAGEzNGM4OWM4LWZjN2YtNDg2ZS05Y2NkL...=   ← Microsoft Graph immutable ID
```
Plus 8 Jun follow-up (`AW: ...Preparing for the hearing... [EH-AT.FID1147]`), also a Graph `AAQk…` id.
- `email_messages` post-2026-06-03: 201 rows, latest received 2026-06-09 14:16, latest ingest 14:18.
- ID format split proves the source: post-migration rows carry Graph ids (`AAQk…`); pre-migration carry Gmail ids (`19e8…`) / RFC ids (`…@eh.at`). The Spanyi 6 Jun + 8 Jun rows are Graph-sourced.

### 3. The blind surface — reproduced
`baker_gmail_search "from:M.Spanyi@eh.at after:2026/06/05"` → **`match_count: 0`** (silent empty), while the mail provably exists in the store. tools/gmail.py `_search` (line 307) calls `_get_gmail_service()` (Gmail googleapiclient `users().messages().list()`) — Gmail OAuth ONLY, no path to the M365/graph store. Structurally blind to brisengroup mail post-migration.

### 4. Pipeline path (why baker_search is the right surface)
graph_mail_trigger → `_process_email_threads()` (shared sink, triggers/email_trigger.py:776) → `SentinelPipeline().run()` (Qdrant embed) + `store_email_message()` (Postgres `email_messages` mirror, store_back.py:1665). So M365 mail is both semantically indexed (baker_search) and in `email_messages`. signal_queue is NOT the mail store — post-6/3 it holds only `legacy_alert` (681 rows); that table was a red herring in the verification SQL.

## PIN-vs-desk conflict — reconciled
- PIN §A-LEAD-0607 ("M365 feed restored, graph_mail healthy, mail flowing, Peter Storer PASS") = **correct on ingestion.** graph_mail is healthy and ingesting.
- Desk evidence ("post-6/3 brisengroup mail unsearchable, Director pasted by hand") = **correct symptom, wrong cause.** The mail was ingested + searchable via baker_search; the failure was searching via `baker_gmail_search` (Gmail-only) which silently returned empty.
- Both true at different layers. The danger is the SILENCE: empty ≠ error, so every agent/desk using `baker_gmail_*` for brisengroup mail confidently misses everything.

## One open verification (not blocking the root cause)
`baker_search` AND `baker_health` MCP tools returned `Errno 111 Connection refused` from this session's MCP path, while Postgres-backed tools (raw_query, watermarks) reached prod fine. Likely a LOCAL MCP artifact (a localhost component the search/health path needs), not a prod outage — but it must be confirmed that prod `baker_search` actually returns the Spanyi mail before we tell desks "use baker_search instead." The mail is 100% retrievable via `email_messages` today regardless.

## Smallest fix plan (Phase 2 — pending lead greenlight)

Smallest change that makes Spanyi's 6 Jun email findable + kills the fail-silent:

1. **Zero-code mitigation (today):** brisengroup mail lives in the store now — desks use `baker_search` (semantic, includes M365) or read `email_messages`, NOT `baker_gmail_search`. Update the desk SOP / mail how-to.
2. **Kill the fail-silent (smallest code, one cycle):** `baker_gmail_search` / `baker_gmail_read_message` must not return a silent empty for brisengroup mail. Add a guard: when the query is brisengroup-scoped (or on any zero-result for a brisengroup `from:`/`to:`), return a LOUD structured pointer ("brisengroup mail migrated to M365 — not on the Gmail surface; use baker_search / baker_mail_search") instead of `match_count:0`.
3. **Durable surface (recommended Phase 2 core):** add a `baker_mail_search` tool that reads the merged `email_messages` store (Gmail + Graph in one place) so there is a single mail surface that sees everything. Keep `vallen300@gmail.com` personal account on Gmail (dual-source).
4. **Health alert (AC5):** add a graph_mail staleness alert in sentinel_health — fire if `graph_mail_poll` watermark is older than N hours. Currently advancing fine; the guard makes a future silent stall loud.
5. **Confirm prod baker_search** returns the Spanyi mail (closes the open verification above) — drives whether step 1's recommended surface is baker_search or a direct email_messages tool.

## Done-rubric mapping (for Phase 2)
- AC1 (Phase 1 findings on bus, command outputs) — this report + bus post.
- AC2 (Spanyi findable post-fix) — via baker_mail_search / baker_search live evidence.
- AC3 (new mail searchable within a cycle) — send test mail to dvallen@brisengroup.com, prove it appears.
- AC4 (no fail-silent) — guard in step 2.
- AC5 (graph_mail staleness alert) — step 4.

STOP — awaiting lead greenlight on the fix plan before any code.
