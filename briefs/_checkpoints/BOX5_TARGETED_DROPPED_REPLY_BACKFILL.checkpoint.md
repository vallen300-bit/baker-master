# CHECKPOINT — BOX5_TARGETED_DROPPED_REPLY_BACKFILL

attempt: 2
rollover: b2 at ~92% context — clean exit; Phase 2 (greenlit #5003) deferred to successor. Artifacts current.
claim: b3 took over attempt 2 (dispatch #5010), 2026-07-01 — executing Phase 2 with the per-candidate any-key guard.
brief: bus dispatch #4999 (Director-ratified #4998). No brief file — dispatch-only.
owner: b3 · dispatched_by: lead · date: 2026-07-01

## Brief id / context
Targeted backfill of KNOWN dropped matter replies (the sink conversation-dedup bug,
now fixed + deployed). NOT a blind whole-mailbox sweep. Phase 1 read-only → report →
Phase 2 re-ingest after lead greenlight. <20 = immediate greenlight; ≥20 = hold.

## What's DONE
- Parent fix BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1: MERGED `2adb8619` (PR #453), deploy
  dep-d92lcgbrjlhs73d680sg LIVE. AC6 canary PASS — reply row + ticket id=64
  (airport-ticket-v1-3e0aa7ed8e879953388b) + bus #4994 to baden-baden-desk. Verdict #4996.
- GRAPH_INGEST_SCOPE_WIDEN_1: MERGED `a37ea4eb` (PR #450).
- **Phase 1 (this arc) COMPLETE + reported to lead (bus #5001), NO writes.**
  - Drop-log confirmed useless (gates keyword_prefilter/routing_conflict only; sink drop is upstream).
  - Scope = 1 active project BB-AUK-001 (aukera/baden-baden-desk): Aukera-domain senders
    (a.bonnewitz/p.zuechner/annaberg@aukera.ag) + 6 airport_tickets threads = 29 convos.
    Excluded as noise: keyword-ILIKE (2915), internal-sender (25929), cm@merz-recht (586).
  - DIFF (live Graph vs email_messages, non-draft + non-excluded folder): **8 dropped / 7 convos.**

## The 8 dropped (per-message ids by tail + sender + subject + date)
- ...AR4eWiAAA= | p.zuechner@aukera.ag | "Speed of intended transaction!!!" | 2026-06-16  ← EXTERNAL, high value
- ...Ac2LtJAAA= | cm@merz-recht.de | "06/2026 Lilienmatt Immobilien GmbH -Restrukturierung" | 2026-07-01 17:26 ← EXTERNAL counsel
- ...Aa2oF0AAA= | balazs.csepregi@brisengroup.com | "Annaberg Status - Closing actions" | 2026-06-29 (internal)
- ...Aa2oF2AAA= | balazs.csepregi@brisengroup.com | "FW: AB Sprint FW: Q&A / ESG / Debt Model" | 2026-06-29 (internal; thread already has ticket id=1 + canary ticket)
- ...Aa2oF3AAA= | siegfried.brandner@brisengroup.com | "AW: Annaberg Status - Closing actions" | 2026-06-29 (internal)
- ...AZ5FWEAAA= | notifications@tasks.clickup.com | "[Overdue] 2. Write financing working brief" | 2026-06-27 (AUTOMATED → REJECT_NOISE, no ticket)
- ...Aa2oGJAAA= | notifications@tasks.clickup.com | "[Overdue] 3. Open DD data room — Merz fills" | 2026-06-29 (AUTOMATED)
- ...AcJLUnAAA= | notifications@tasks.clickup.com | "[Overdue] 4. Skliar + Derkachova loan" | 2026-06-30 (AUTOMATED)
Full per-message ids: re-run the Phase-1 enumerator (below) — it prints them; the 8 are
stable. 5 would ticket to baden-baden-desk (2 external + 3 internal); 3 are automated no-ticket.

## What's LEFT (Phase 2 — GREENLIT by lead #5003, with a CORRECTNESS GUARD)

Lead GREENLIT (#5003) but caught a real defect in my Phase-1 diff: it keyed 'stored'
on the per-message id ONLY. Under the OLD scheme the FIRST message of each already-seen
conversation WAS stored as message_id=conversationId — so it looks "absent" by
per-message id but is NOT genuinely dropped. Re-ingesting it would DOUBLE-store +
double-ticket. Genuine REPLIES (2nd+ msgs) were never stored under ANY key = the real targets.

**PER-CANDIDATE GUARD (MANDATORY before writing each):** confirm the message is absent
under ANY key — check email_messages by BOTH (a) its per-message id AND (b) by
(conversationId/thread_id + sender_email + subject + received_date). Recover ONLY if
genuinely absent everywhere.

**HARD EXCLUSIONS (do NOT re-ingest/ticket):**
1. balazs "FW: AB Sprint FW: Q&A/ESG/Debt Model" 06-29 (...Aa2oF2AAA=) — it's the
   first-message stored under conversationId (holds ticket id=1 + canary id=64). SKIP.
2. the 3 ClickUp automated [Overdue] notifs (...AZ5FWEAAA=, ...Aa2oGJAAA=, ...AcJLUnAAA=)
   — REJECT_NOISE, not matter replies. SKIP entirely.

**RECOVER SET (candidates — apply the per-candidate ANY-key guard to each; drop any that
are first-messages-already-stored-under-conversationId):**
- p.zuechner@aukera.ag "Speed of intended transaction!!!" 06-16 (...AR4eWiAAA=)
- cm@merz-recht.de "06/2026 Lilienmatt Immobilien GmbH -Restrukturierung" 07-01 (...Ac2LtJAAA=)
- balazs.csepregi "Annaberg Status - Closing actions" 06-29 (...Aa2oF0AAA=)
- siegfried.brandner "AW: Annaberg Status - Closing actions" 06-29 (...Aa2oF3AAA=)

Each genuinely-absent one → per-message store + pipeline + distinct ticket (canary #4993
path), idempotent, existing tickets id=1 untouched.
REPORT to lead: final recovered count + which genuinely-new vs skipped-as-already-stored
+ the baden-baden-desk ticket ids. Emit POST_DEPLOY_AC_VERDICT v1.

## Execution recipe (proven in the #4993 canary — reuse verbatim)
Creds via `op` (NO values here): Graph M365_* from `op://Baker API Keys/wyeoa7ymygvfp5vmuqnjd5xkry/{tenant_id,client_id,cert_thumbprint}` + cert doc "M365 Graph cert PRIVATE KEY (PEM, unlocked 2026-06-03)" → M365_CERT_PATH; DATABASE_URL `op://Baker API Keys/DATABASE_URL/credential` (PARSE into POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE — the store pool reads POSTGRES_*, NOT DATABASE_URL); ANTHROPIC_API_KEY `op://Baker API Keys/API Anthropic/credential`; VOYAGE_API_KEY `op://Baker API Keys/API Voyager/credential`; QDRANT_URL + QDRANT_API_KEY `op://Baker API Keys/API Qdrant/{QDRANT_URL,credential}`; dispatcher bus key via `brisen_lab_read_terminal_key dispatcher` → export BRISEN_LAB_TERMINAL_KEY_DISPATCHER. PYTHONPATH=~/bm-b2, BAKER_USE_GRAPH=true.
Per message: Graph GET /users/{u}/messages/{id} ($select=gmt._SELECT) → gmt._to_thread(m) → triggers.email_trigger._process_email_threads([thread]) (stores per-message row; sentinel deep-pipeline may error on local 'google.genai' — harmless, row stores first). Then build EmailArrival → orchestrator.airport_ticketing_bridge.build_email_ticket(arrival, now=utcnow) (None = automated/no-keyword, skip) → issue_ticket(ticket, conn) → write_terminal_status(conn, ticket_row_id=id, terminal_status='TICKET', terminal_reason='backfill_ac6', raw_source_id=msg_id) → conn.commit(). Note: the sentinel-pipeline 'google.genai' local gap means "pipeline event" runs prod-side, not locally — report honestly.
Phase-1 enumerator logic (re-derive the 8): in-scope convos = SQL UNION of graph email_messages where lower(sender_email) in aukera-domain (a.bonnewitz/p.zuechner/annaberg@aukera.ag) + DISTINCT airport_tickets.thread_id; then Graph list per conv ($filter=conversationId eq '{conv}'), drop isDraft + parentFolderId in gmt._excluded_folder_ids(c)[0], diff per-message id vs email_messages.message_id.

## Next concrete step (Phase 2 is GREENLIT #5003 — execute with the guard above)
For each of the 4 RECOVER-SET candidates: run the PER-CANDIDATE ANY-KEY GUARD first
(email_messages by per-message id AND by conversationId+sender+subject+received_date).
Recover ONLY the genuinely-absent ones via the #4993 exec recipe (store per-message →
build_email_ticket → issue_ticket → write_terminal_status='TICKET'). SKIP the 2 hard
exclusions (balazs FW AB Sprint ...Aa2oF2AAA=; 3 ClickUp notifs) + the ESG reply
...c2Ls6AAA= (already recovered). Never touch ticket id=1. Then REPORT recovered count +
genuinely-new-vs-skipped + baden-baden-desk ticket ids + POST_DEPLOY_AC_VERDICT v1 to lead.

NOTE: likely fewer than 4 recover after the guard — the balazs "Annaberg Status" and
siegfried "AW: Annaberg Status" may themselves be first-messages/only-copies; check each.
