# CHECKPOINT — BOX5_TARGETED_DROPPED_REPLY_BACKFILL

attempt: 1
brief: bus dispatch #4999 (Director-ratified #4998). No brief file — dispatch-only.
owner: b2 · dispatched_by: lead · date: 2026-07-01

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

## What's LEFT (Phase 2 — AWAITING lead greenlight on bus #5001)
Lead to pick the set: (all 5 matter) | (2 external only: Zuechner + Merz) | (all 8 incl automated).
Then re-ingest each chosen per-message id via the #4993 canary path, idempotent
(skip any per-message id already in email_messages; never touch existing tickets id=1),
then REPORT count recovered + which landed on baden-baden-desk + emit POST_DEPLOY_AC_VERDICT v1.

## Execution recipe (proven in the #4993 canary — reuse verbatim)
Creds via `op` (NO values here): Graph M365_* from `op://Baker API Keys/wyeoa7ymygvfp5vmuqnjd5xkry/{tenant_id,client_id,cert_thumbprint}` + cert doc "M365 Graph cert PRIVATE KEY (PEM, unlocked 2026-06-03)" → M365_CERT_PATH; DATABASE_URL `op://Baker API Keys/DATABASE_URL/credential` (PARSE into POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE — the store pool reads POSTGRES_*, NOT DATABASE_URL); ANTHROPIC_API_KEY `op://Baker API Keys/API Anthropic/credential`; VOYAGE_API_KEY `op://Baker API Keys/API Voyager/credential`; QDRANT_URL + QDRANT_API_KEY `op://Baker API Keys/API Qdrant/{QDRANT_URL,credential}`; dispatcher bus key via `brisen_lab_read_terminal_key dispatcher` → export BRISEN_LAB_TERMINAL_KEY_DISPATCHER. PYTHONPATH=~/bm-b2, BAKER_USE_GRAPH=true.
Per message: Graph GET /users/{u}/messages/{id} ($select=gmt._SELECT) → gmt._to_thread(m) → triggers.email_trigger._process_email_threads([thread]) (stores per-message row; sentinel deep-pipeline may error on local 'google.genai' — harmless, row stores first). Then build EmailArrival → orchestrator.airport_ticketing_bridge.build_email_ticket(arrival, now=utcnow) (None = automated/no-keyword, skip) → issue_ticket(ticket, conn) → write_terminal_status(conn, ticket_row_id=id, terminal_status='TICKET', terminal_reason='backfill_ac6', raw_source_id=msg_id) → conn.commit(). Note: the sentinel-pipeline 'google.genai' local gap means "pipeline event" runs prod-side, not locally — report honestly.
Phase-1 enumerator logic (re-derive the 8): in-scope convos = SQL UNION of graph email_messages where lower(sender_email) in aukera-domain (a.bonnewitz/p.zuechner/annaberg@aukera.ag) + DISTINCT airport_tickets.thread_id; then Graph list per conv ($filter=conversationId eq '{conv}'), drop isDraft + parentFolderId in gmt._excluded_folder_ids(c)[0], diff per-message id vs email_messages.message_id.

## Next concrete step
Read bus for lead's greenlight on #5001 (which set). If greenlit + set chosen → run Phase 2
re-ingest for that set via the recipe above → verify email_messages rows + airport_tickets
+ baden-baden-desk bus landings → POST_DEPLOY_AC_VERDICT v1 to lead. If not yet greenlit → wait.
Idempotency: skip per-message ids already in email_messages (the ESG reply ...c2Ls6AAA= is
already recovered; do not re-touch). Never touch existing ticket id=1.
