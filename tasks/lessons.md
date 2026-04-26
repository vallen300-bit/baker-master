# Lessons Learned

Review at session start. Add new lessons after any correction. Remove stale ones.

---

## Frontend

### 1. Don't use HTML5 Drag API in scrollable containers
**Mistake:** Used HTML5 Drag API (`draggable="true"`, `dragstart/dragover/drop`) for cards inside `.grid-cell-body` with `overflow-y: auto`. The browser cancelled the drag immediately — `dragstart` fired then `dragend` with zero `dragover` events.
**Root cause:** Browsers interpret mouse movement in scrollable containers as scroll intent, killing the drag.
**Rule:** Never use HTML5 Drag API inside scrollable containers. Use pointer events (mousedown/mousemove/mouseup) instead. Start drag from a grip handle, use a threshold (8px) before activating, create a floating ghost clone with `position: fixed`. This is how Todoist and other production apps do it.

### 2. Always verify DB schema matches code
**Mistake:** `set_critical()` and `get_critical_items()` referenced `is_critical` and `critical_flagged_at` columns that didn't exist in the deadlines table. Functions silently failed (try/except swallowed errors). The Critical section showed empty for weeks.
**Rule:** When code references a DB column, verify it exists before shipping. Run `SELECT column_name FROM information_schema.columns WHERE table_name = 'X'` to confirm. Never trust that a migration ran — check.

### 3. Column name mismatches are silent killers
**Mistake:** `doc_type` referenced in code but actual column is `document_type`. Same pattern as `is_critical`. Both caused features to silently fail — try/except swallowed the errors, user saw "Failed to load" or empty sections.
**Rule:** When writing SQL in Python, always verify column names first: `SELECT column_name FROM information_schema.columns WHERE table_name = 'X'`. Don't assume — check.

### 4. CSS cache busting
**Rule:** Always bump `?v=N` on both CSS and JS in index.html when modifying either file.

---

## Cloudflare

### 3. Cloudflare Access for Pages sites
**Mistake:** Tried to protect a Pages site via Zero Trust self-hosted app wizard. The subdomain/domain fields doubled the hostname. Wasted 30+ minutes.
**Rule:** For Cloudflare Pages, enable Access through: Pages project → Settings → General → Access Policy → Enable. This auto-creates the correct Access app. Then add a second hostname (empty subdomain) to also cover the production root domain.

### 4. Cloudflare react-select dropdowns
**Mistake:** Spent time trying to automate Cloudflare's react-select dropdowns via Chrome MCP. They don't respond to standard fill/click.
**Rule:** Don't fight Cloudflare's UI automation. For anything beyond simple clicks/text, prefer CLI tools (wrangler) or ask the Director to do a manual step. Budget 2 min for the Director, not 20 min debugging dropdowns.

### 5. Cloudflare Pages deployment
**Mistake:** Tried uploading individual files. Cloudflare Pages requires a single folder or zip.
**Rule:** Always zip the folder first: `cd /path && zip -r /tmp/output.zip .` Then have the Director drag the zip. Or drag the folder itself from Finder, not the files inside it.

### 6. Wrangler CLI needs API token
**Mistake:** Tried `wrangler pages deploy` without auth. Non-interactive mode requires `CLOUDFLARE_API_TOKEN` env var.
**Rule:** We don't have a Cloudflare API token stored anywhere. The Director must drag-deploy via browser. If we ever create one, store it in `.zshrc` and memory.

---

## Chrome MCP

### 7. Chrome file uploads
**Mistake:** Chrome MCP `upload_file` doesn't reliably handle folder uploads to Cloudflare's drag-and-drop area.
**Rule:** For file uploads to web UIs, prefer asking the Director to do it manually (Finder → drag). Give exact Finder path using `/private/tmp` (not `/tmp`) for macOS.

---

## General

### 8. Verify before marking done
**Mistake:** Shipped DRAG-DROP-1 and called it complete without testing in the live dashboard. The drag didn't work because onclick conflicted with draggable — a bug a staff engineer would have caught.
**Rule:** Never mark a task complete without proving it works. Before committing:
- Test the actual user flow, not just syntax
- For frontend: load the page, try the interaction, check console for errors
- For backend: call the endpoint, verify the response
- Ask: "Would a staff engineer approve this PR?"

### 9. Try simplest approach first
**Mistake:** Multiple times went down complex automation paths (API tokens, react-select hacking) when a simple manual step would have worked.
**Rule:** Before spending >5 min automating a one-time action, ask: can the Director do this in 30 seconds manually? If yes, give clear step-by-step instructions instead.

### 9. GitHub repos — check before deleting
**Rule:** Before deleting a public repo, always check forks (`gh repo view --json forkCount`). If forks exist from unknown accounts, flag it — forks survive source deletion.

### 10. Git history rewrite for sensitive data
**Rule:** Use `git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch file1 file2' --prune-empty -- --all` then `git push --force`. Always verify with `git log --oneline --name-only | grep filename` returns 0 matches before force-pushing.

### 11. Check for duplicate API endpoints before adding new ones
**Mistake:** Added `GET /api/people` at line 8867 but an existing endpoint at line 3037 shadowed it. FastAPI registers the first match. People sidebar showed empty because it was hitting the old endpoint returning contacts, not issues.
**Rule:** Before adding a new endpoint, `grep -n "the/path" dashboard.py` to check for existing routes at the same path.

### 12. Push before declaring done
**Mistake:** Made local code changes and told the Director "it's done" — but changes weren't pushed to GitHub, so Render never deployed them. Director reloaded and saw no changes.
**Rule:** Local edits mean nothing until `git push`. Don't tell the user changes are live until Render has deployed.

### 13. Never batch-migrate LLM call sites — one file at a time
**Mistake:** GEMINI-MIGRATION-1 wave 2 changed 17 call sites across 13 files in one commit. Introduced 19 bugs: deleted client variables but left references, changed response access patterns incorrectly (`.content[0].text` → `.text` on Anthropic responses), passed Gemini model names to Anthropic client, dropped system prompts from `call_flash()` calls. Dashboard was completely broken.
**Rule:** When migrating LLM providers, change ONE file at a time. For each file: (1) verify the current call pattern, (2) migrate, (3) syntax check, (4) test the specific endpoint. Never bulk-replace across files. Three things that MUST stay consistent: client type ↔ model name ↔ response access pattern.

### 14. Auto-expand sidebar sections with content
**Mistake:** People section was `defaultExpanded=false`. After saving issues, the count updated but the section stayed collapsed — user couldn't see their saved items.
**Rule:** After loading data into a collapsible sidebar section, auto-expand it if items exist. Don't rely on the user knowing to click the arrow.

### 15. Gemini call_flash() requires messages list and .text extraction
**Mistake:** `compile_knowledge_digest()` in `rss_trigger.py` called `call_flash(prompt, system=...)` passing a plain string as the first arg. `call_flash` expects `messages: list[dict]`. Also assigned the GeminiResponse object directly to `digest_md` instead of extracting `.text`. Feature silently crashed every RSS poll for days — no digests ever compiled.
**Rule:** Every `call_flash()` / `call_pro()` call MUST use `messages=[{"role": "user", "content": text}]` — never a bare string. Return value is a `GeminiResponse` object — always extract `.text` (or `.text.strip()`). This is Lesson #13's cousin: the three-way match is client ↔ call signature ↔ response access pattern.

### 16. Git-track implementation briefs to avoid "pending" confusion
**Mistake:** 100+ briefs accumulated in `briefs/` but were never `git add`'ed. Code Brisen saw 22 untracked `??` files and reported them all as "pending work" — when only 3 were genuinely unbuilt. Wasted a full audit cycle to separate done from pending.
**Rule:** `git add briefs/` after writing or completing a brief. Tracked briefs disappear from `git status`. Only truly new briefs show as untracked. Agents can instantly see what's new vs historical.

### 17. Brief code snippets must be verified against actual function signatures
**Mistake:** BRIEF_KNOWLEDGE_DIGEST_1 included `call_flash(prompt, system=...)` — passing a bare string as the first arg. The actual signature is `call_flash(messages: list, ...)`. Code Brisen implemented the brief exactly as written. Feature silently crashed for days. The bug was in the brief, not the implementation.
**Rule:** Before putting a code snippet in a brief, **read the actual function signature** (`Grep` for `def function_name`). Never assume you remember the API. This is the brief-writing equivalent of Lesson #2 (verify DB schema): verify call signatures before writing copy-pasteable code. Brief writer owns the bug if the snippet is wrong.

### 18. Verify FastAPI imports — JSONResponse is NOT auto-imported
**Mistake:** `JSONResponse` was used in 10+ endpoints across `dashboard.py` but never imported from `fastapi.responses`. The "Save to Dossiers" button returned 500 (`name 'JSONResponse' is not defined`) on every click. Other endpoints using it were also silently broken.
**Rule:** When adding an endpoint that returns `JSONResponse(...)`, check line 22 of `dashboard.py` — verify it's in the import. FastAPI auto-imports `Response` but NOT `JSONResponse`. One-line fix, hours of mystery.

### 19. Cloudflare Access: zero policies ≠ bypass — it means BLOCK
**Mistake:** Created an Access app for `ollama.brisen-infra.com` with zero policies, expecting it to be open. Cloudflare returned 302 redirect to login page. With no policies, Access defaults to blocking all traffic.
**Rule:** To make a tunnel hostname publicly accessible, do NOT create an Access app for it at all. An Access app with zero policies = blocked. No Access app = open. If you need selective bypass, add an explicit Bypass policy — don't leave the policy list empty.

### 20. Cloudflare tunnel: set originRequest.httpHostHeader for local services
**Mistake:** Added `ollama.brisen-infra.com` tunnel route pointing to `http://localhost:11434`. Got 403 — Ollama rejected requests because the `Host` header was `ollama.brisen-infra.com` but Ollama only accepts `localhost`.
**Rule:** When tunneling to a local service that validates the Host header, add `originRequest.httpHostHeader: localhost` to the ingress rule in `~/.cloudflared/config.yml`.

### 21. Chrome blocks HTTP fetch from HTTPS pages (mixed content)
**Mistake:** Expected `https://baker-master.onrender.com` to fetch `http://localhost:11434` (Ollama). Chrome hard-blocks this — `ERR_FAILED`, no CORS headers even matter.
**Rule:** HTTPS pages cannot fetch HTTP localhost. Solutions: (a) proxy through HTTPS tunnel (Cloudflare), (b) serve the page from HTTP localhost, or (c) use a Chrome extension (which runs in a different security context). `targetAddressSpace: "local"` doesn't help yet.

### 22. Slack @mention vs natural language — code must handle both
**Mistake:** Director typed "Baker, please remember..." in Slack (natural language). Code only checked for `<@U0AFJLAP1BR>` (Slack @mention format). 8 Director messages over 2 weeks were ingested but never processed or replied to. Director thought Baker was ignoring him.
**Rule:** When building a chat bot trigger, always handle BOTH the platform's mention syntax AND natural language name mentions. Check: `is_mention OR (is_director AND "baker" in text.lower())`. The Director will not always use @mentions — especially on mobile.

### 23. RSS feeds auto-disable after 6 consecutive failures — monitor and re-enable
**Mistake:** 4 RSS feeds (AI Technology + Longevity) hit 6 consecutive failures (likely temporary site downtime) and auto-disabled. The Media sidebar silently lost entire categories. Director noticed weeks later.
**Rule:** The auto-disable threshold (6 failures) is a safety feature but needs monitoring. Add to briefing: if any feed transitions from active→inactive, flag it. Also: when re-enabling, test the feed URL first (`curl -s -o /dev/null -w "%{http_code}" URL`) — the URL may have genuinely changed.

### 24. Run periodic health audits — silent failures accumulate
**Mistake:** Multiple issues accumulated unnoticed: Slack not replying (2 weeks), RSS feeds disabled (days), WhatsApp backlog (35 days), Whoop dead (22 days), JSONResponse broken (unknown duration). Each was non-fatal and silent — no alerts, no errors visible to the Director.
**Rule:** Run `baker_raw_query` health checks periodically: (a) `SELECT source, status, consecutive_failures FROM sentinel_health WHERE status != 'healthy'`, (b) `SELECT type, COUNT(*) FROM trigger_log WHERE processed = false GROUP BY type`, (c) `SELECT category, COUNT(*) FROM rss_feeds WHERE is_active = true GROUP BY category`. Flag anything anomalous in the briefing.

### 25. Startup backfills are OOM bombs — never embed/analyze during catch-up
**Mistake:** `backfill_fireflies()` ran `pipeline.run()` (Claude + Gemini) for 50 transcripts AND embedded each to Qdrant twice on every deploy. `backfill_whatsapp()` fetched 500 chats with media downloads + Qdrant embedding. Combined: 400MB → 3.2GB → OOM in 10 minutes. Service crashed in a restart loop.
**Rule:** Startup backfills must be PG-only (store data for safety net). Never run `pipeline.run()`, Qdrant embedding, or LLM analysis during backfill — the regular scheduler poll handles that for genuinely new items. If two memory-heavy backfills run sequentially, they compound. Use PostgreSQL advisory locks (e.g., `pg_try_advisory_lock(867531)`) to prevent concurrent backfills during Render deploy overlap. Test memory after changes: `GET /api/health/scheduler` should show stable memory <800MB for first 10 minutes.

### 26. Wrong import path = feature silently dead since day one
**Mistake:** `compile_knowledge_digest()` in `rss_trigger.py` imported `from llm.gemini_client import call_flash`. No `llm/` directory exists — actual path is `orchestrator.gemini_client`. The outer try/except caught the `ModuleNotFoundError` and logged it as a generic error. Knowledge digests were empty since the feature shipped (KNOWLEDGE-DIGEST-1). Director found it weeks later.
**Rule:** After shipping any feature with a lazy import (`from x.y import z` inside a function), verify it works on the actual server — not just locally. Lazy imports inside try/except are invisible killers: they fail silently every time. `grep -rn "from llm\." triggers/ orchestrator/` would have caught this in 2 seconds. This is Lesson #17's cousin: verify the import path, not just the function signature.

### 27. WAHA session needs store config on recreation
**Mistake:** WAHA session corrupted (bad decrypt errors). Deleted and restarted it without `config.noweb.store.enabled=True`. Session worked for sending but backfill couldn't fetch chats — returned 400 "Enable NOWEB store". Had to delete + restart AGAIN with store config, requiring another QR scan.
**Rule:** When recreating a WAHA session, ALWAYS include store config: `{"name": "default", "config": {"noweb": {"store": {"enabled": true, "fullSync": true}}}}`. Without it, `list_chats()` and message history APIs fail.

### 28. WhatsApp @lid format — don't filter, normalize
**Mistake:** WhatsApp migrated chat IDs to `@lid` format. Baker's `list_chats()`, contact sync, and backfill all had `@lid` filters that silently dropped these messages. Messages from contacts like Constantinos and Sergey were invisible for days.
**Rule:** Never filter out `@lid` chat IDs. WhatsApp is migrating to this format. Accept all formats (`@c.us`, `@s.whatsapp.net`, `@lid`). Future improvement: normalize `@lid` → `@c.us` using WAHA's contact lookup API.

### 29. Claude Code web (claude.ai/code) runs on cloud VM, not the Mac Mini
**Mistake:** Assumed Code Brisen via claude.ai/code ran directly on the Mac Mini. Tried to run `brew install`, `hostname`, GUI apps — all failed. The environment is a Linux cloud VM that syncs the repo via git. Cannot install apps, run GUI, or access local network.
**Rule:** claude.ai/code = cloud VM (Linux). It can: edit files, git operations, run Python/Node. It cannot: install macOS apps, access GUI, reach local network, run MCP servers locally. For Mac Mini physical operations, need Supremo/VNC/physical access.

### 30. MCP connectors in Claude Code web load at session start only
**Mistake:** Added Baker MCP as a custom connector in Claude Code web settings, then tried to use it in the existing session. ToolSearch returned "No matching deferred tools found". Wasted time retrying.
**Rule:** MCP connectors are loaded when a session starts. Adding a connector mid-session has no effect. Must start a NEW session for new connectors to be available.

### 31. SSE MCP transport — session ID mismatch on reconnect
**Mistake:** Baker MCP SSE endpoint works on first connection (ListToolsRequest processed). But when Claude Code web reconnects (which it does frequently), it gets a new SSE session with a different session_id. POST messages to the old session_id return 404. Tools appear stuck "connecting".
**Rule:** SSE transport with MCP has a reconnection problem. Each GET /mcp/sse creates a new session. Use Streamable HTTP transport instead (stateless JSON-RPC, no sessions). Fixed in commit `0c0b7e5`.

### 32. Claude Code web sandbox blocks outbound HTTP to custom domains
**Mistake:** Built a working Streamable HTTP MCP endpoint at `POST /mcp` on baker-master.onrender.com. Verified with curl from MacBook (25 tools, all working). Added `.mcp.json`, custom connector, and `claude mcp add` — none worked. Spent 2+ hours trying 4 different approaches. The sandbox proxy blocks all outbound connections to `baker-master.onrender.com` — both MCP and curl return "host not allowed" / exit code 56.
**Rule:** Claude Code web (claude.ai/code) runs in a sandboxed cloud VM with a network proxy allowlist. Custom domains like `baker-master.onrender.com` are NOT on the allowlist. Neither MCP tools, curl, nor any HTTP client can reach them. Don't build features that depend on Claude Code web calling custom endpoints. Only the CLI version of Claude Code (running on Mac Mini or any local machine) can reach arbitrary URLs. Plan accordingly — if Code Brisen needs Baker data, it must run as CLI, not web.

### 33. Vault structure: optimize for machine retrieval, not human navigation
**Mistake:** Director's instinct was matter-first vault structure (matching his Dropbox `1_ACTIVE_PROJECTS/` layout). Each matter would contain its own raw/wiki/schema layers. This mirrors how humans think — "everything about Aukera in one place."
**Root cause:** Neither the filer (Tier 2) nor the retriever (Tier 2/Tier 3) is human. Both are Claude. Claude doesn't navigate folders visually — it searches by filename, greps content, follows `[[links]]`. A cross-matter document (e.g., contract between AO and Movie) would need to be duplicated or arbitrarily assigned to one matter.
**Rule:** When designing storage structure for AI-operated systems (vault, PG schema, file trees), optimize for the reader — which is a machine. Karpathy three-layer at top (raw/wiki/schema) prevents filing ambiguity and duplication. Wiki pages carry matter context via `[[links]]`, not folder hierarchy. The human (Director) never sees the structure — only the results.

### 34. Structural verification ≠ integration verification (2026-04-17)
**Mistake:** `scripts/build_eval_seed.py` shipped with only structural tests: AST parse (syntax) pass, dry-run on empty-label JSONL pass, validator-on-malformed-row expected-fail pass. All "verified clean" per the author's report. On first real execution against production PG, it failed immediately: SQL CTE referenced `email_messages.id`, but the actual PK column is `message_id` (Gmail API string ID, not SERIAL). `whatsapp_messages` and `meeting_transcripts` both use `id` — `email_messages` is the outlier. Bug sat for hours until Director's labeling session needed the seed and B3 ran the script against real DB.
**Root cause:** structural tests prove the script has valid Python syntax and handles malformed inputs. They don't prove the script can execute its business logic against production-shape tables. Per-table PK conventions drift across Baker's schema (email = `message_id` string from Gmail API; WA/meetings = `id` SERIAL from Baker's own inserts) — a single `id` assumption is wrong on 1 of 3 source tables.
**Rule:** For any script that reads/writes Baker's PG tables, acceptance criteria MUST include at least ONE real-data smoke test before the script is marked "verified":
- `SELECT <columns> FROM <table> LIMIT 1` — executes the actual query against production shape
- Verify column names with `SELECT column_name FROM information_schema.columns WHERE table_name = 'xxx'` BEFORE writing the SQL, not after it fails
- Don't trust column names from memory — they drift per table (Gmail `message_id` ≠ WhatsApp `id`)
Structural tests catch syntax/import/dispatcher bugs. Integration smoke tests catch schema bugs. Both required; neither sufficient alone. Cousin of Lesson #17 (verify function signatures) — same pattern at schema layer.

### 35. Migrations shipped in PRs were never applied to production Neon (2026-04-19)
**Mistake:** 9 migration files landed across PRs #7-#16 over two days. Every PR merged green. Nobody was responsible for running `psql -f migrations/*.sql` against Neon. `signal_queue` stuck at 25 columns (expected 35+), `kbl_cost_ledger` + `kbl_log` tables missing entirely. Surfaced only when Phase 1 shadow mode went live and AI Head hit `/api/kbl/cost-rollup` — got `relation "kbl_cost_ledger" does not exist`. Every Step 1-6 would have crashed on first real signal.
**Root cause:** migration files were tracked as code but not as deployable artifacts. No CI check, no startup hook, no human gate. "Merging a migration" silently meant "the SQL now exists in the repo" — not "the SQL has run on the DB."
**Rule:** Any codebase with file-based migrations needs one of: (a) migration runner at service startup that auto-applies (this is what `MIGRATION_RUNNER_1` / `config/migration_runner.py` now does), (b) CI step that runs migrations in a test env, or (c) explicit human deployment gate with checklist. Pick one. Never leave migrations in the "hope someone remembered" category.

### 36. `DATABASE_URL` vs split `POSTGRES_*` env convention drift (2026-04-19)
**Mistake:** Same production Neon database, two different env-var conventions. `config/settings.py` (Baker proper) reads six split keys: `POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE`. `kbl/db.py:27` reads single `DATABASE_URL`. Mac Mini `~/.kbl.env` has `DATABASE_URL` set → KBL code works locally. Render had only the six split keys → KBL code crashed with `KeyError: 'DATABASE_URL'` on every call. Dashboard `/api/kbl/*` + the new `pipeline_tick` scheduler job BOTH failed silently on Render until AI Head noticed.
**Root cause:** two modules in the same codebase evolved independent env conventions. Neither was "wrong" — both are standard Render patterns. The divergence was silent because local dev + Mac Mini happen to have both, and Render CI didn't exercise the `DATABASE_URL` code path.
**Rule:** When a codebase touches Postgres from multiple modules, pick ONE env convention and stick to it. If two conventions exist (legacy + new), the newer module must build the other layout from the one that's canonical on your hosting platform. For Render+Neon: `POSTGRES_*` split is canonical; `DATABASE_URL` if needed must be derived. Either make `kbl/db.py` read `POSTGRES_*` OR set `DATABASE_URL` as a derived env var on Render (AI Head did the latter as the unblock; root-cause fix is a polish PR).

### 37. DDL embedded in Python `_ensure_*()` functions never runs on Render (2026-04-19)
**Mistake:** `memory/store_back.py:6505` (`_ensure_kbl_cost_ledger`) and `:6552` (`_ensure_kbl_log`) contain `CREATE TABLE IF NOT EXISTS` + indexes as Python-executable SQL. Written with the intent of "run on store init so tables exist." But on Render, `_init_store()` in `outputs/dashboard.py` does NOT call these `_ensure_*` methods — they're invoked lazily elsewhere (possibly never on the current code path). `_init_store` has warn-swallow on any PG error, so silent skip was doubly masked.
**Root cause:** mixing two schema-management strategies (migration files + Python DDL) without a contract for which one owns what. Both existed; neither was canonical. DDL in Python is also harder to track — you can't `git log migrations/` to see schema history.
**Rule:** schema belongs in `migrations/*.sql`, not in Python `_ensure_*()` methods. If a table's DDL is currently in Python, promote it to a migration file on first opportunity (AI Head did this for `kbl_cost_ledger` + `kbl_log` tonight at `migrations/20260419_add_kbl_cost_ledger_and_kbl_log.sql`). Keep `store_back.py` _ensure methods as a TEMPORARY belt-and-braces until migration runner has claimed the file; then delete them.

### 38. `((ts::date))` is VOLATILE; modern Postgres rejects it in index expressions (2026-04-19)
**Mistake:** `CREATE INDEX idx_cost_ledger_day ON kbl_cost_ledger ((ts::date))` — copied verbatim from `memory/store_back.py:6529` — rejected by Neon (Postgres 16+) with `functions in index expression must be marked IMMUTABLE`. `TIMESTAMPTZ → date` cast depends on session timezone setting, so it's VOLATILE; expression indexes must be deterministic.
**Root cause:** older Postgres versions were more permissive. `((ts::date))` worked on whatever version `store_back.py` was originally tested against.
**Rule:** for daily-bucket indexes on `TIMESTAMPTZ` columns, use `((<col> AT TIME ZONE 'UTC')::date)` — semantically identical (day bucket in UTC), IMMUTABLE because the timezone name is a literal. Or simpler: index on the bare `TIMESTAMPTZ` column and write queries as `WHERE ts >= date_trunc('day', NOW())` — btree on ts handles range scans fine. Follow-up: `memory/store_back.py` still has the old bare form and will hit this error when its code path runs on Render.

### 39. Render env-var PUTs do NOT auto-restart the service (2026-04-19)
**Mistake:** Set `DATABASE_URL` on Render via PUT `/v1/services/{id}/env-vars/DATABASE_URL` → HTTP 200. Expected service to auto-restart and pick up the new env. No restart. Re-queried `/health`: new env NOT in effect. Wasted ~5 min verifying before realizing.
**Root cause:** Render's dashboard UI auto-redeploys on env changes. The REST API does NOT — you set the value, and the NEXT deploy (whether triggered by a commit push or an explicit POST `/deploys`) picks it up. Otherwise the value sits in the env-var table without being injected into any running container.
**Rule:** after any Render env-var PUT, POST `/v1/services/{id}/deploys` with `{"clearCache":"do_not_clear"}` to force the restart that loads the new env. Expect ~2-4 minute build + live transition. Documented at `/Users/dimitry/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/reference_render_api_ops.md`.

### 40. Brief premises that reference Mac-Mini-disk-only state are unverifiable from the repo (2026-04-19)
**Mistake:** AI Head wrote `KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` with the architectural premise "Mac Mini poller.py is Step-7-only." True in production, but `poller.py` lives on Mac Mini disk (installed via `MAC_MINI_LAUNCHD_PROVISION`) and is NOT tracked in the `baker-master` repo. B2 correctly flagged S1: "premise unverifiable from repo alone — if Mac Mini's plist actually invokes `kbl.pipeline_tick.main()`, this PR orphans Step 7."
**Root cause:** brief writer assumed reviewer could verify all claims by reading the repo. When a claim depends on live infrastructure state (installed scripts on remote hosts, Render env, DNS, etc.), the reviewer has no way to check.
**Rule:** when a brief references state that is NOT in the repo (Mac Mini scripts, Render env, external service config, 1Password vault shape), the brief MUST include a `§Scope.N Pre-merge verification` section with the exact ssh/curl/op commands the reviewer runs and pastes output into the PR. AI Head or B1 runs these BEFORE merge. See PR #18's §Scope.6 as the working template (3 ssh checks on poller plist + wrapper + imports, with explicit BLOCK-merge + recut-prerequisite-brief fallback).

### 41. FastAPI `@app.on_event("startup")` marks `/health` green before async hook completes (2026-04-20)
**Mistake:** After merging `MIGRATION_RUNNER_1` (PR #20), Monitor waited for Render deploy status `live` then ran a single-shot `schema_migrations` check — got `relation does not exist`. Panicked, diagnosed DATABASE_URL mismatch. A few minutes later: re-ran same query, table existed with all 11 migrations. Monitor false alarm.
**Root cause:** FastAPI's startup lifespan is async; the service can transition to "ready for requests" (and Render marks the deploy `live`) while the startup hook is still running. `_run_migrations()` took a few seconds more after `/health` went green.
**Rule:** post-deploy verification that depends on startup-hook side effects must poll for up to ~60s after `live`, not single-shot check. Use `until <cond>; do sleep 5; done` pattern with a deadline. For migration verification specifically: `SELECT COUNT(*) FROM schema_migrations` with retry-until-non-zero is the right shape.

### 42. Dashboard fixture-only tests can't catch schema drift (2026-04-19/20)
**Mistake:** PR #17 shipped 4 new `/api/kbl/*` endpoints + 8 tests. All tests used `_FakeCursor` fixtures with injected rows — never hit a real table. Column-name bug (`created_at` vs `ts` on `kbl_cost_ledger`) slipped through both B1 implementation and B2 PR review. Broke `/api/kbl/cost-rollup` on first real use. PR #19 hotfix retrofit added `test_kbl_cost_rollup_sql_uses_canonical_ts_column` — captures emitted SQL via cursor monkey-patch and double-asserts (`"WHERE ts" in q AND "created_at" not in q`). Caught the regression direction that fixtures couldn't.
**Root cause:** fixture tests validate code handles returned shapes correctly, not that the SQL sent TO the DB is correct against the real schema. Column-name typos produce valid-looking SQL that fails only at execution time against a live table.
**Rule:** for any endpoint that writes SQL against a real table, include at least ONE of: (a) TEST_DATABASE_URL-gated real-DB smoke test (pytest-postgresql or Neon ephemeral branch), OR (b) SQL-assertion test that captures `cursor.execute` args and asserts expected canonical column names. B1's PR #19 pattern (`_FakeCursor.execute` monkey-patch + `"WHERE ts" in q AND "created_at" not in q`) is the cheap version. Cousin of Lesson #34 (structural vs integration verification) — same root pattern at SQL-string layer.

### 43. Source-directory deletion needs a legacy-reference sweep (2026-04-22)
**Mistake:** BRIEF_AO_PM_EXTENSION_1 deleted `data/ao_pm/` after vault migration shipped, but `memory/store_back.py:_seed_wiki_from_view_files` (line 2509) and `scripts/seed_wiki_pages.py:136` still list the deleted path. Both are dormant (seeder only fires on empty `wiki_pages`; helper is one-shot and never auto-invoked), so no runtime break — but the references become time-bombs if `wiki_pages` is ever reset: seeder would re-seed stale content or silently no-op with a confusing warning. B4 caught this during ship-report review and added an operational note, but it should have been in the brief's Do-NOT-Touch or a dedicated "Legacy reference sweep" section.
**Root cause:** brief's Do-NOT-Touch section enumerated live code paths, not dormant-but-referenced paths that activate only on specific recovery scenarios.
**Rule:** when a brief deletes a source directory or file referenced elsewhere in the codebase, `grep -r` for the directory/file name first and either (a) update all references to point at the new canonical path (preferred), or (b) explicitly list the dormant references in the brief with an operational note on the correct restore path. Cousin of Lesson #2/#3: verify all dependents before mutating shared state. The pattern extends to dormant code paths, not just column names.

### 44. `/write-brief` REVIEW step catches what informal exploration misses (2026-04-22)
**Observation:** BRIEF_AO_PM_EXTENSION_1 had informal exploration (function signatures grep-verified, table-name correction on `baker_corrections`, APScheduler pattern matched to existing `wiki_lint` job). That pass was solid but missed three items the formal `/write-brief` REVIEW caught: (1) invented table `decomposer_decisions` in the routing diagnostic — doesn't exist, real path is `capability_runs` WHERE `capability_slug='decomposer'`; (2) `wiki_pages` slug format mismatch — existing convention is `{pm_slug}/{base}` per `_seed_wiki_from_view_files` at `memory/store_back.py:2544-2547`, bare stems would have broken `_load_wiki_context`'s `slug LIKE '%/index'` lead-page ordering; (3) missing `matter_slugs` array + `updated_by` audit column in the ingest INSERT.
**Root cause:** informal exploration optimizes for "can I write the code snippet correctly?" Formal REVIEW optimizes for "does the code snippet match existing conventions + actual schema?" The second lens is cheap but separate.
**Rule:** for any brief that touches a shared table / schema / seeding pattern, invoke `/write-brief` REVIEW formally even after thorough informal exploration. Specifically check: (a) every table name mentioned exists (grep for `CREATE TABLE`), (b) every insert matches existing seed/writer conventions (grep for `INSERT INTO <table>` and compare column sets), (c) every diagnostic SQL hits real tables with real columns. All three are Lesson #2/#3 cousins — the REVIEW pass is the forcing function.

### 45. Briefs that chain endpoint calls must validate the chained endpoint's contract (2026-04-24)
**Mistake:** BRIEF_PROACTIVE_PM_SENTINEL_1 Rev 3 specified that `/api/sentinel/feedback` (new) returns `rethread_hint.turn_id_hint = None` (hardcoded null) on the `wrong_thread` dismiss preset, with the JS layer chain-calling `/api/pm/threads/re-thread` (Phase 2, already deployed) using that null value. Brief shipped, B2 implemented to spec, AI Head #2 /security-review CLEAN, B1 second-pair review GREEN. After merge, B1 flagged as a non-blocking note that `/api/pm/threads/re-thread` guards `if not turn_id: return 400` at `outputs/dashboard.py:11241` — so the wrong_thread chain is broken end-to-end on the very first Director click. Required PR #60 fix-back: server-side `SELECT turn_id FROM capability_turns WHERE thread_id=%s ORDER BY created_at DESC LIMIT 1` to populate the hint, plus a JS guard for the empty-thread edge.
**Root cause:** brief design verified the new endpoint's behavior in isolation but did not trace the full chain through to the existing endpoint's contract. The `re-thread` endpoint's `turn_id` requirement was discoverable in 30 seconds with `grep -A 30 '/api/pm/threads/re-thread' outputs/dashboard.py`. Brief writer skipped that grep because the chained endpoint was "already deployed" and felt out-of-scope.
**Rule:** when a brief specifies that one endpoint returns a hint the client passes to ANOTHER endpoint, the brief MUST include the chained endpoint's required-field contract verbatim — copied from a fresh grep — and the new endpoint's hint payload must match. If the hint can be null, the chained endpoint must accept null (verify, do not assume). For `/write-brief`: add a checklist item to step EXPLORE — *"For every chained `fetch()` / `bakerFetch()` in the new code, grep the receiving endpoint and copy its required-field guard into the brief's data-flow section."* Cousin of #34 / #40 / #42 / #44 — the verification step that catches the bug is fast and skippable; the bug is real and fix-back-grade.

### 46. `§2` busy-check doesn't catch same-task duplicate dispatch across different B-codes (2026-04-25)
**Mistake:** Director asked AI Head #2 to dispatch B2 to second-pair-review PR #61 (PROMPT_CACHE_AUDIT_1, B1's build). AI Head #2 ran the ratified `§2` busy-check on B2's mailbox (`briefs/_tasks/CODE_2_PENDING.md`) — header `COMPLETE — merged 5611f43`, B2 idle, dispatch authorized. Mailbox written, committed, pushed (`43d1be2`), wake-paste surfaced. But AI Head #1 had ALREADY dispatched B3 for the same review at commit `2cb7eb6` minutes earlier; B3's verdict landed at `7280adc`, and AI Head #2's dispatch was retired as duplicate. No real damage (B2 was never woken) but a wasted dispatch turn.
**Root cause:** `§2` of `_ops/processes/b-code-dispatch-coordination.md` checks whether *the target B-code* is busy (mailbox + branch state). It does NOT check whether *the task itself* is already dispatched to a different B-code. Same-task dispatch collision is a different failure mode than same-B-code preemption.
**Rule:** before any dispatch, additionally scan recent dispatch commits across all B-code mailboxes — `git log --oneline --since='2 hours ago' -- briefs/_tasks/CODE_*_PENDING.md briefs/_reports/B*_review*` — for the same PR # / brief name / task slug. If hit, route to Research Agent `§6C` traffic control instead of dispatching. `§2` amendment candidate logged for Monday 2026-04-27 audit (`SCRATCH_MONDAY_AUDIT_20260427.md`). Cousin of `§6C` rule 2 (*"a dispatch pattern will stall silently"*) — this is the breadth analogue: a dispatch pattern can also *duplicate silently*.

### 47. `§2` busy-check doesn't catch redundant dispatch against shipped feature (2026-04-26)
**Mistake:** Director authorized PLAUD_SENTINEL_1. RA drafted the spec without grepping the codebase. AI Head A drafted brief, ran `§2` busy-check (B-code mailboxes + worktree state — all clean), and dispatched B3 (commit `eb68dca`). B3's pre-build audit caught it: `triggers/plaud_trigger.py` (599 LOC) ALREADY shipped at commit `2f5675c` (PLAUD_INGESTION_1), brief archived at `briefs/archive/BRIEF_PLAUD_INGESTION_1.md`, scheduler job `plaud_scan` already registered, `PlaudConfig` in `config/settings.py:139-141`, full pipeline integration (PM signal, contacts, deadlines, commitments, meeting_pipeline async) live. The new brief's Q3 ratification ("new `plaud_notes` table") was made on incomplete information — existing implementation chose `meeting_transcripts source='plaud'`. HOLD pushed (`f44d35c`). Branch never created, no files modified. Memory gap was system-wide: RA didn't grep, Director didn't recall, AI Head A didn't grep.
**Root cause:** `§2` busy-check (per `_ops/processes/b-code-dispatch-coordination.md`) verifies B-code availability, NOT feature pre-existence. Mailbox state + worktree state + recent-dispatch-collision (Lesson #46) all answer "is this B-code/task slot free?" — none answer "does this feature already exist as shipped code?" The catch happened only because the brief mandated B3 read existing sentinel patterns at Step 0 of build (for endpoint discovery on what AI Head A wrongly believed was an undocumented API). B3's nuance: *"the catch wasn't volunteered, it surfaced because the brief itself routed me through `triggers/` first. If `§2` promotes those checks to dispatch-time, dispatchers don't have to rely on the build brief structuring discovery the same way every time."*
**Rule:** before drafting any new sentinel / capability / pipeline brief, AI Head MUST run at dispatch time (not rely on B-code's build process to surface): (a) `git log --oneline --grep='<feature_name>'` against full repo, (b) `ls briefs/archive/ | grep -i '<feature_name>'`, (c) `grep -rn '<feature_name>' triggers/ kbl/ orchestrator/ memory/ config/` (case-insensitive). If ANY of (a)/(b)/(c) hits, halt drafting and triage: existing-feature-with-deltas vs greenfield. RA spec drafting must include the same grep. Ghost-cite checks (e.g., `2026-04-21-gold-comment-workflow-spec.md` ghost-cite caught earlier today) extend to "ghost-greenfield": a spec describing a feature as new when shipped code already implements it. `§2` amendment candidate to fold with Lesson #46 at Monday 2026-04-27 audit.

### 48. Every dispatch MUST surface a paste-block same turn — B-codes don't poll (2026-04-26)
**Mistake:** AI Head B dispatched B3 to GOLD_COMMENT_WORKFLOW_1 (mailbox `briefs/_tasks/CODE_3_PENDING.md` overwritten). AI Head A (in active Director chat lane) saw the dispatch via system-reminder but did NOT produce the b3 trigger paste-block. Dispatch sat dormant — B3 worktree had no signal to wake. Director surfaced gap with: "pls always give me the task for codes, they are not polling."
**Root cause:** AI Heads conflate "mailbox written" with "dispatch live". Mailbox file alone is dormant — B-codes don't poll filesystem or git for new mailboxes. The wake-mechanism is Director pasting a `cd ~/bm-bN && git checkout main && git pull -q && cat briefs/_tasks/CODE_N_PENDING.md` trigger into the named tab. No paste-block in chat = no wake.
**Rule:** EVERY dispatch turn — regardless of which AI Head wrote the mailbox — the AI Head in the active Director chat lane MUST surface the paste-block formatted as:

```
**Paste to: b<N>**

cd ~/bm-b<N> && git checkout main && git pull -q && cat briefs/_tasks/CODE_<N>_PENDING.md
```

Same applies to AI Head ↔ AI Head dispatches (use `aihead1`/`aihead2` labels per `00_WORKTREES.md`). NEVER assume a B-code or peer agent will pick up work from a mailbox without an explicit Director-pasted wake. Cousin of Lesson #46 (busy-check) — both are dispatch-coordination invariants. §6C orchestration mode amendment candidate for Monday 2026-04-27 audit.

### 49. Verify what a B-code is busy ON before re-routing — same-task collision risk (2026-04-26)
**Mistake:** Director said "b3 is busy, pls instruct b2, he is idle". AI Head A interpreted "busy" as "on other work" and re-routed GOLD_COMMENT_WORKFLOW_1 from B3 → B2 (commit `1c4dfab`). Reality: B3 was busy ON GOLD itself (AI Head B had paste-blocked the dispatch directly to B3 via the `aihead2` lane, outside AI Head A's chat lane visibility). The re-route created a same-task duplicate dispatch — exact Lesson #46 failure mode. Director surfaced gap; rollback at `6831d0b`.
**Root cause:** AI Head A inferred B3's task from the SUPERSEDED-mailbox-edit alone, not by checking what B3 was actually executing. When dispatch happens directly via paste-block (not via mailbox-only), the task may not be reflected in any mailbox AI Head A can see. Cross-AI-Head dispatch-state visibility is incomplete.
**Rule:** Before any re-route, AI Head MUST verify the busy B-code's CURRENT TASK by one of: (a) explicit ask to Director ("what is B3 busy on?"), (b) check recent paste-block history in shared chat lane, (c) check git log for recent dispatch commits naming that B-code by exact tab label, (d) inspect the B-code's current branch checkout via worktree. If any signal indicates the busy B-code is on the SAME task we're trying to re-route, halt and ask. Cousin of Lesson #46 (busy-check) — same coordination invariant, different visibility gap. §6C orchestration mode amendment candidate for Monday 2026-04-27 audit.
