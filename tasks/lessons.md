# Lessons Learned

Review at session start. Add new lessons after any correction. Remove stale ones.

---

## Operations

### Env-var wipe demands a forensic completeness audit (2026-05-20 anchor)

**Mistake (2026-05-17, surfaced 2026-05-20):** Catastrophic Render env-var wipe on `baker-master` reduced 50 env vars to 22. Eleven keys were restored via single-key PUT the same night ("partial recovery"). Twenty-nine keys stayed missing for THREE DAYS because:

1. Every external API call in Baker is wrapped in fault-tolerant `try/except` — so `GEMINI_API_KEY not set` errors fired hundreds of times in Render logs without surfacing as a sentinel alert. Resilience became a silencer.
2. No "env-var presence" sentinel exists. Sentinel-health tracks symptoms (WAHA inbound silence, RSS disabled, Gmail stuck), never the env layer itself.
3. The recovery checklist focused on keys that would 500 the dashboard immediately (DB / Anthropic / Tavily / Qdrant). It did NOT diff "pre-wipe key list (50) vs post-restore key list (22)" before declaring recovery complete.
4. Director-facing surfaces (Cortex panel, Director Card, dashboard, bus, Pending tab) don't depend on the wiped keys. The system looked fine from the outside; ingestion + outbound layers degraded silently.

**Rule:** every env-wipe / env-restore incident MUST end with a literal `pre_count` vs `post_count` diff AND a per-key audit (have-value / vendor-regen-needed / intentionally-retired) committed alongside the recovery. Recovery is not "done" until the diff is zero or every gap is explicitly classified.

**Anchor:** 2026-05-20 night restoration sweep. 27 keys restored (1P + Todoist BAKER-PROJECT > API KEYS & PW + Chrome MCP → Google AI Studio for Gemini). Final Render count 60. Bus #579 dispatched DIRECTOR_CARD_V1_1 only after Gemini key was confirmed live + Render deploy succeeded. Director directive: "why nobody noticed this" — caught the silent-degradation class of failure.

**Operational follow-up queued:**
- `briefs/BRIEF_ENV_PRESENCE_SENTINEL_1.md` (TBD) — daily cron diffs Render env-var key list against checked-in `expected_keys.yml`, alerts on missing.
- `config/.env.backup.render` (Director-suggested, Envars.png note 2026-05-20) — snapshot on Mac, refreshed after any env mutation.
- 1Password coverage: every Render env key now has a 1P home (`API Gemini`, `Bluewin IMAP` items created same session; `API Dropbox` + `API Whoop` updated with refresh tokens; `API Apollo` annotated as `LINKEDIN_API_KEY` alias).

### Never use Render's array-form `PUT /v1/services/{id}/env-vars` (2026-05-17 anchor, reinforced 2026-05-20)

Already in `tools/render_env_guard.py` + `.claude/rules/python-backend.md`. Reinforced here as scar context: the 2026-05-17 wipe was caused by an array-body PUT replacing the entire env set. Always use single-key path `PUT /env-vars/{KEY}` with body `{"value": "..."}`. The 2026-05-20 restoration used 27 successful single-key PUTs with zero collateral damage as live proof the safe path works.

### Deliberate env-var retirements (2026-05-20)

Some env vars in the pre-wipe AID April snapshot are deliberately NOT restored — they reflect retired integrations. Recovery audits should leave these absent (not "missing"). Current list:

| Env var | Reason retired |
|---|---|
| `OLLAMA_HOST` | Ollama is local-Mac-only (Director's hardware via `localhost:11434` for agent picker brainstorm via `local-research-via-gemma` skill). Baker production code never had an Ollama call path on Render — Gemini API covers cheap-tier; Anthropic covers high-stakes. Restore only if `BRIEF_DOMAIN_SLM_PERSISTENT_INFERENCE_1` (queued 2026-05-20 for Director ratification) ratifies Part A — that swaps `classify_intent()` to local SLM via Tailscale to Mac Mini, which would re-introduce `OLLAMA_HOST` as `tailscale://mac-mini:11434`. |
| `BLUEWIN_PASS` / `BLUEWIN_USER` | RE-STORED 2026-05-20 (not retired; was wiped + recovered from Todoist). Active per `triggers/bluewin_poller.py`. |
| `EXCHANGE_PASS` | NOT retired — genuinely lost. Only EVOK can reset via Florian Bourqui. Director email queued for morning send 2026-05-21. |

**Rule:** any deliberate retirement gets a row in this table. Future env audits MUST treat the table as the source of truth for "missing-by-design vs missing-by-accident".

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

### 3b. Column-existence check belongs in the BRIEF, not the build
**Mistake (CORTEX_RUN_SCAN_UI_RENDER_1, 2026-04-30):** AI Head A's brief specified a SELECT including `aborted_reason` from `cortex_cycles`, sourced from the in-memory cycle object's terminal-SSE shape. B1 implemented the brief verbatim; tests passed because the test fixture stubbed cursor results without verifying actual schema; deploy succeeded because import works fine. Endpoint then 500-errored on every real call: `column "aborted_reason" does not exist`. `aborted_reason` lives only on the Python object returned by `maybe_run_cycle`, not in `cortex_cycles`. Hotfixed in PR #91.
**Rule:** Brief author owns column verification. Before writing any SELECT in a brief, run `SELECT column_name FROM information_schema.columns WHERE table_name = '<name>'` and paste the actual list of columns into the brief's "DB schema verified" section. Don't infer column names from in-memory object attributes, SSE event shapes, or other downstream payloads — those can have fields that exist only at the Python layer.

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

### 50. Review-in-flight pre-check before writing CODE_N_PENDING for review work (2026-04-26)
**Mistake:** PR #66 review dispatch race — AI Head B wrote `briefs/_tasks/CODE_1_PENDING.md` for B1 to review PR #66 (commit `d1c9418`) at the same window B1 had self-initiated the review. `§2` busy-check missed it because review-in-flight signal lives in PR comments + `briefs/_reports/B1_pr<N>*` file existence, not B-code mailbox. Self-initiated review (commit `e51a7d6`) landed; AI Head B's dispatch was effectively superseded.
**Root cause:** `§2` busy-check (per `_ops/processes/b-code-dispatch-coordination.md`) reads B-code mailbox + branch state. For review-class work, the actual signal lives in (a) `gh pr view N --json reviewDecision`, (b) `ls briefs/_reports/B*_pr<N>*`, (c) recent PR comments by reviewer-class agents. None of those are in the canonical busy-check.
**Rule:** before writing `CODE_N_PENDING` for review work specifically, run the augmented pre-check: `gh pr view <N> --json reviewDecision` AND `ls briefs/_reports/B<N>_pr<PR>*` AND `git log --oneline --since='2 hours ago' -- briefs/_reports/B*_pr*`. If any signals work-in-flight, abort or stage. Hardcoded into PR #68 dispatch flow successfully (`c9eb165`). RA-22 ratified as Lesson #50; folds into `§2` amendment candidate at Monday 2026-04-27 audit. Cousin of Lessons #46 + #49 — all three are dispatch-coordination invariants where `§2` reads the wrong signal.

### 51. Rule 0 retroactive validation — pre-Rule-0 briefs need EXPLORE pass before dispatch (2026-04-26)
**Mistake:** BRIEF_AMEX_RECURRING_DEADLINE_1 was authored inline (commit `820fa9a`) before SKILL.md Rule 0 (`/write-brief` mandatory) ratification 2026-04-26 PM. Inline draft carried 3 defects: (1) wrong API names — `mark_completed/dismissed` invoked but real API is `complete_deadline`/`dismiss_deadline`/`confirm_deadline` + 2 raw-UPDATE paths in `clickup_trigger.py:535` + `models/deadlines.py:387` (Amendment H); (2) missing `python-dateutil` dependency in `requirements.txt`; (3) auto-dismiss race window — `_auto_dismiss_overdue_deadlines` (line 672) and `_auto_dismiss_soft_deadlines` (line 706) would 3-day-overdue-dismiss recurring rows mid-respawn unless excluded via `AND recurrence IS NULL`. All 3 defects survived to dispatch-ready state; only caught when post-PR-#66 retroactive EXPLORE happened (`030604a` brief amendment).
**Root cause:** `/write-brief` Rule 0 enforcement is forward-looking. Pre-Rule-0 briefs in `briefs/BRIEF_*.md` carry latent defects that pass code-review-readiness checks (compile clean, tests greenfield) but mismatch real production code paths.
**Rule:** any pre-Rule-0 brief in `briefs/BRIEF_*.md` MUST get a retroactive EXPLORE pass before promoting to `CODE_N_PENDING`. EXPLORE checks: (a) every function name mentioned exists at the cited file:line, (b) every dependency mentioned is in `requirements.txt`, (c) every shared-state writer named in the brief is enumerated against actual call sites via `grep -rn`. RA-22 ratified as Lesson #51. Pre-Rule-0 briefs flagged for batch audit: VIP_BACKFILL_1, DEADLINE_EXTRACTOR_QUALITY_1, BRANCH_HYGIENE_1. Cousin of Lessons #2/#3/#34/#42/#44/#45 — verification step that catches the bug is fast and skippable; the bug is real and fix-back-grade.

### 52. `/security-review` skill invocation MANDATORY for lane-owner merges — manual diff-read is not substitute (2026-04-26)
**Mistake:** PR #66 (GOLD_COMMENT_WORKFLOW_1, MEDIUM-trigger-class) and PR #68 (AMEX_RECURRING_DEADLINE_1, MEDIUM-trigger-class) were both merged 2026-04-26 evening under manual diff-read review only — `/security-review` skill was NOT invoked on either. RA-22 mandated retroactive coverage. PR #68 retroactive pass clean; **PR #66 retroactive pass surfaced 3 real authorization bypasses on `_check_caller_authorized` at `kbl/gold_writer.py:752-759`**: (1) thread/process boundary bypass via `inspect.stack()` only walking current thread (HIGH, conf 9), (2) `__name__` mutation bypass via `frame.f_globals['__name__']` reading mutable module dict (HIGH, conf 9), (3) `__main__` evasion when cortex code runs as direct script (MEDIUM, conf 7). All 3 are concrete exploit paths on the PR's stated security boundary. Manual review missed all 3.
**Root cause:** manual diff-read review optimizes for code-quality + correctness against brief acceptance criteria. It does NOT systematically check authorization boundaries, deserialization paths, SQL parameterization across all touched modules. `/security-review` skill orchestrates a structured pass against 5 security categories with confidence-scoring and false-positive filtering — disciplined coverage manual review does not produce.
**Rule:** `/security-review` skill invocation MANDATORY for ALL lane-owner Tier A merges. Apply to all Tier A merges going forward. Manual diff-read is not substitute. RA-22 ratified as Lesson #52, anchor case = PR #66's caller-stack guard. Codify in SKILL.md §Security Review Protocol on next AI Head consolidation pass; flag for SKILL.md amendment. Cousin of Lesson #44 (`/write-brief` REVIEW catches what informal exploration misses) — both are formal-skill discipline rules where the skill catches what informal pass misses.

### 53. Autopoll mode supersedes Lesson #48 *only within defined autopoll window* (2026-04-27)

> **Numbering note:** originally drafted as Lesson #50 in `BRIEF_B_CODE_AUTOPOLL_1` ship branch (B1 build). Renumbered to #53 on rebase 2026-04-28 to resolve collision with main's already-ratified #50/#51/#52 (RA-22 numbering). Authority: AI Head A rebase resolution, PR #69 merge.

**Rule:** B-codes opted into autopoll (per `_ops/processes/b-code-autopoll-startup.md`) self-wake on mailbox commits during the window — paste-block NOT required for fresh dispatches. Outside the window, Lesson #48 fully applies (paste-block mandatory same turn as dispatch).

**Window definition:** active when (a) Director has pasted the start-protocol per startup doc, AND (b) `OVERNIGHT_AUTONOMY_UNTIL` deadline not yet passed, AND (c) B-code's loop has not exited via idle count or `STOP AUTOPOLL`.

**Frontmatter signal:** mailbox `autopoll_eligible: true` indicates AI Head expects autopoll mode pickup. `autopoll_eligible: false` (default) means cold-start paste-block still required even if window is active.

**Why both modes coexist:** highest-traffic dispatches (overnight build cycles) get autopoll; sensitive dispatches (HIGH trigger class, Director-eyeball needed, ambiguous brief) stay paste-block-driven so Director sees the dispatch live.

**Anchor:** BRIEF_B_CODE_AUTOPOLL_1 (Director ratified 2026-04-27 "ratified all" on 8 open Qs).

### 54. `gh pr list --state open` immediately before drafting any dispatch — even on a 60-second gap (2026-04-30)
**Mistake:** Q1-flip Brief 3 dispatch sequencing inversion. AI Head A merged vault PR #37 + #40 at 20:48:13Z + 20:48:17Z, then drafted dispatch PR #130 (`B4 → Brief 3 CORTEX_PHASE6_REFLECTOR_1`) without re-listing open PRs. Meanwhile a B-code had already opened PR #129 (the actual Brief 3 build) at 20:48:49Z — 30 seconds AFTER the last vault merge, while AI Head A was already typing the dispatch mailbox. PR #130 landed post-hoc to a build that was already in flight. End state was consistent (mailbox correctly described what would happen), but the dispatch was redundant and the sequencing inverted.
**Root cause:** "fresh state" feels valid for a stretch. After a successful merge cluster, AI Head A's mental cache says "I just verified the world; safe to draft for ~5 minutes." But B-code activity (autopoll mode per Lesson #53, or human-paste-driven dispatches from another AI Head lane) can open PRs in seconds. The cache is invalid the moment any tool other than AI Head A's own session can write to the repo. `§2` busy-check (Lesson #46) reads the mailbox; it doesn't enumerate open PRs; an in-flight build with no mailbox entry is invisible to mailbox-only checks.
**Rule:** `gh pr list --state open --limit 20` MUST run as the first step of any dispatch draft, regardless of how recently AI Head A last verified state. Specifically required when (a) drafting `CODE_N_PENDING.md` content, (b) before any `git checkout -b aihead/dispatch-*` branch creation, (c) inside the busy-check `§2` flow as an additional gate. Cousin of Lesson #46/#47/#49/#50 — all five are dispatch-coordination invariants where `§2` reads the wrong / incomplete signal. `§2` amendment candidate: add open-PR enumeration to the canonical busy-check sequence.

### 55. Render's default Python is 3.14.x as of 2026-05 — pin via `.python-version` (2026-05-01)
**Mistake:** First brisen-lab deploy from `vallen300-bit/brisen-lab@main` failed at runtime with `ImportError: undefined symbol: _PyInterpreterState_Get` from `psycopg2._psycopg.so`. The repo's `requirements.txt` pinned `psycopg2-binary==2.9.9` (validated against Python 3.12). Render auto-selected Python 3.14.3 since no version was pinned, and 2.9.9's pre-built wheels do not include 3.14 ABI.
**Root cause:** Render's "we pick a sensible default" behavior moves forward each Python release. A package set that works locally on the Director's macOS Python (3.12.x at the time of brisen-lab build) silently breaks at deploy. No CI catches this — there is no CI for brisen-lab.
**Fix:** `.python-version` file at repo root with `3.12.7`. Render reads it and pins build-time Python.
**Rule:** every new Python service deployed to Render MUST commit a `.python-version` file with a known-good interpreter version. Never rely on Render's default. Cousin of Lesson #20 family (env-version-drift bites at deploy-time, not commit-time).
**Anchor:** brisen-lab `vallen300-bit/brisen-lab@8d5db20` (BRISEN_LAB_1 close, B5 build).

### 56. macOS TCC blocks launchd-spawned processes from `~/Desktop` without explicit Files-and-Folders grant (2026-05-01)
**Mistake:** brisen-lab forge-agent launchd daemon (`com.brisen.lab-agent`) snapshots b1-b4 successfully (`git_branch`, `git_head_sha`, `git_head_subject` populated) but lead+deputy snapshots show `git_branch=null` etc. Symptom in `~/forge-agent/agent.err.log`: `fatal: Unable to read current working directory: Operation not permitted` from every git invocation against `~/Desktop/baker-code`.
**Root cause:** macOS Transparency-Consent-Control (TCC) protects `~/Desktop`, `~/Documents`, `~/Downloads` against headless processes. launchd-spawned binaries don't have a foreground app context, so they don't inherit GUI-granted permissions. The git binary running inside the daemon's venv-Python subprocess is blocked silently by the kernel.
**Fix:** Director-side, GUI-only — System Settings → Privacy & Security → Files and Folders → enable Desktop access for `/Users/dimitry/forge-agent/.venv/bin/python3` (or the wrapping Python interpreter). Then `launchctl kickstart -k gui/$(id -u)/<label>` to reload.
**Rule:** any launchd agent that needs to read files in `~/Desktop`, `~/Documents`, or `~/Downloads` MUST have its Python (or other interpreter) binary explicitly granted in Files-and-Folders. Document this in the brief's "Director-side prerequisites" so it's set up at provisioning time, not discovered post-deploy.
**Anchor:** BRISEN_LAB_1 lead+deputy snapshot degradation (B5 build, post-Director-provisioning 2026-05-01).

### 57. `~/.zshrc` surgical inject pattern — preserve existing function body when adding env-var prefix (2026-05-01)
**Mistake-as-near-miss:** BRISEN_LAB_1 brief L859-864 specified literal-replacement zshrc shell functions for `aihead1`/`aihead2`, e.g. `function aihead1() { printf "\033]0;Lead\007"; FORGE_TERMINAL=lead claude "$@"; }`. The Director's existing `aihead1`/`aihead2` functions carried `cd ~/Desktop/baker-code && claude --name "AI Head A" --append-system-prompt "<persona>"` — the persona-flag system that drives bank-model session-init per `_ops/processes/ai-head-autonomy-charter.md`. A literal replacement would have wiped persona flags, silently breaking AI Head session-start protocol.
**What B5 did instead:** surgical inject — kept the entire existing function body and only added `FORGE_TERMINAL=<alias>` as an env-var prefix to the `claude` invocation. AI Head B endorsed the divergence; AI Head A ack pending on next session.
**Rule:** when modifying `~/.zshrc` (or any shell rc) to add new env-var injection or new behavior to existing functions:
1. **`grep`-verify the function exists with full body BEFORE editing** (e.g., `grep -n -A 10 "^function aihead1" ~/.zshrc`).
2. **Preserve every existing flag** (`--name`, `--append-system-prompt`, `cd`, tab-title escapes). Even if the brief's suggested replacement omits them.
3. **Only inject the new prefix in front of the binary call** (e.g., `FORGE_KEY=$key FORGE_TERMINAL=$alias claude "$@"`).
4. **Backup at `~/.zshrc.bak.YYYYMMDD`** before editing.
5. **`zsh -n ~/.zshrc`** syntax-check after.
6. **Flag the divergence in the build report** if the brief specified literal replacement that would have lost behavior.
**Anchor:** BRISEN_LAB_1 zshrc shell-function injection for 6 watched terminals (B5 build, 2026-05-01).

### 58. Path-encoding helpers — verify against real filesystem before shipping (2026-05-01)
**Mistake:** brisen-lab forge-agent's `_project_dir_for(worktree)` at `~/forge-agent/agent.py:141-144` produced `--Users-dimitry-bm-b1` (double-dash prefix) instead of `-Users-dimitry-bm-b1` (single-dash, the actual Claude Code project-dir convention). Code was `encoded = "-" + str(worktree).replace("/", "-")` — but `str(worktree)` already starts with `/`, which becomes the leading `-` after replacement. Adding the explicit prefix `"-"` doubled it. Result: agent's `discover_jsonl_loop` never found ANY project dir for ANY watched terminal. JSONL discovery → tail → buffer → drain → `/api/event` was completely non-functional from launch. `forge_events` stayed empty until B5 found the bug during live QC sweep.
**Why static smoke tests missed it:** B5 build report claimed "project-dir encoding (`/Users/dimitry/bm-b1` → `-Users-dimitry-bm-b1`)" — but the smoke test verified the INTENT, not the implementation; running the actual code never happened against a real `~/.claude/projects/` directory. Symptom-free until live deploy.
**Symptom:** `forge_events` only contains events posted directly via curl (test events). No events from real Claude Code sessions tailed by the daemon. QC #19 (buffer-survives-restart) returned 0 rows until bug was found.
**Fix:** `encoded = str(worktree).replace("/", "-")` — drop the `"-" +` prefix. Verified by `(Path('~/.claude/projects').expanduser() / str(wt).replace('/', '-')).exists() == True`.
**Rule:** for any path-encoding helper that maps an absolute path to a derived form, write a positive `.exists()` test against a real Director-machine path BEFORE shipping. Static smoke tests that re-derive the encoding from the same code never catch the bug. Cousin of Lesson #8 (compile-clean ≠ done; exercise the actual flow).
**Anchor:** `~/forge-agent/agent.py:141-144` (BRISEN_LAB_1 close, B5 fix during live QC sweep, 2026-05-01).

### 59. Brief expected-test-count drift across architect-reviewer passes (2026-05-03)
**Mistake:** BRIEF_FLEET_ROADMAP_HTML_RENDER_1 V0.3.1 dispatch mailbox said "13/13 pytest pass" but the brief body still said "12 passed" (V0.2 had 12 tests; V0.3 added two; V0.3.1 polished; B3 added a 13th `test_gate_status_pill_classes_present`). B1 caught the 12-vs-13 drift during second-pair review. Not blocking — just doc-state drift between brief AC text and dispatch.
**Why it happened:** Each architect-reviewer pass added/renamed tests, but I updated the count in only one place ("12 passed" → "12 passed" → "12 passed") instead of incrementing across §"Tests" run command line + AC #8 + Quality checkpoint 1. Each pass-fix was surgical; the cumulative count never got re-summed.
**Rule:** when adding/removing tests in a brief patch, do `grep -nE "[0-9]+ passed|[0-9]+/[0-9]+ pytest" brief.md` and update EVERY occurrence in one edit. Add a "test count" field to the version-log header so the count is part of the brief's structured metadata (not free-text scattered across §Tests / AC / Quality checkpoints). Lesson cousin: #47 (literal pytest output, no "by inspection") — the literal output is the source of truth; brief copy must match.
**Anchor:** BRIEF_FLEET_ROADMAP_HTML_RENDER_1 V0.3.1; B1 PR #152 second-pair review verdict 2026-05-03.

### 60. Schema-version dispatch — string version footgun (2026-05-03)
**Mistake:** `scripts/render_cortex_roadmap.py` `render()` does `version = yml.get("version", 4); if isinstance(version, int) and version >= 5: ...`. If a future YAML has `version: "5"` (string) or `version: 5.0` (float — PyYAML parses bare `5.0` as float), the `isinstance(version, int)` guard returns False and dispatch falls back to v4 silently. No error, just wrong layout. Brief V0.3.1 didn't specify type-coercion behavior; B3 implementation added the `isinstance(int)` check defensively but didn't normalize.
**Why it happened:** YAML's loose scalar typing — quoted vs unquoted version numbers parse to different Python types. v4 production YAML had bare `version: 4` (int). Migration kept bare `version: 5` (still int). But future hand-edits could quote it.
**Rule:** for schema-version dispatch where the version is a YAML scalar, normalize at load time: `try: version = int(yml.get("version", 4)) except (TypeError, ValueError): raise ValueError("version must be int-coercible")`. Then the dispatch comparison is unambiguous. Capture as follow-up brief if the bug is theoretical-only (currently is); fix in same PR if shipping.
**Anchor:** B1 PR #152 review observation 2026-05-03; deferred as non-blocking — follow-up brief queued if Director ratifies.

### 61. Brief acceptance criteria must not assert third-party HTTP codes without empirical probe (2026-05-08)
**Mistake:** `BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md` v0.3 §"Re-enable sequence" smoke #2 specified "WAHA returns 422 / chat-not-found ... `success=False`, `http_status=422`". Live smoke against `9999999999@c.us` returned `http_status=201`, `success=True`. WAHA accepts arbitrary chat IDs uncritically and forwards downstream — there is no upstream phone-number validation. The ACTUAL load-bearing assertion (`path_taken == "resolver_returned_clean"`) was correct, but the secondary HTTP-code assertion was incompatible with reality.
**Why it happened:** Brief author assumed WAHA validates phone numbers as part of the send pipeline. WAHA is a thin wrapper over WhatsApp's web protocol — it doesn't validate, it forwards. The brief assertion was inferred from "common sense" rather than an empirical probe.
**Rule:** when authoring smoke / acceptance criteria that gate on third-party HTTP behavior:
1. **Probe the third-party with a real call FIRST** (e.g., `curl` to WAHA with a deliberately invalid chat ID) and capture the actual response.
2. **Distinguish load-bearing assertions from descriptive ones.** Load-bearing = block merge / re-enable on failure. Descriptive = inform analyst but don't gate. The HTTP-code assertion in this brief was descriptive but framed as load-bearing.
3. **Prefer assertions on internal state** (`path_taken`, `actual_chat_id`, audit-row presence) over external HTTP codes — internal state is yours to define.
4. If you must assert on a third-party code, cite the third party's documented behavior + the date you verified it.
**Anchor:** `BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md` v0.3 §"Re-enable sequence" #6, smoke verification 2026-05-08T~09:35Z, baker_actions row 860 (PR #173 incident fix).

### 62. Local Python 3.9 (MacBook default) breaks PEP 604 type syntax in baker-master code (2026-05-08)
**Mistake-as-near-miss:** during PR #173 smoke verification, ran `python3 -c "from outputs.whatsapp_sender import send_whatsapp; ..."` from MacBook. Default `python3` on MacBook is `/usr/bin/python3` = Python 3.9.6. PR #173's `_lid_belongs_to_phone` uses `Optional[bool]` written as `bool | None` (PEP 604, Python 3.10+). Module import succeeded for `send_whatsapp` (the failing function annotation was lazy-evaluated), but `_log_send_to_baker_actions`'s reach into `_lid_belongs_to_phone` triggered the type-eval at runtime, which raised `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`. The audit row didn't write. The send DID go through (returned True from WAHA). Smoke #1 looked successful (Director got the message) but baker_actions had no path_taken row — verification gap.
**Why it happened:** Baker-master's prod runtime is Python 3.11+ (per `CLAUDE.md` §Stack). MacBook default `python3` is 3.9 (system Python). Mac Mini default also 3.9. Only `/opt/homebrew/bin/python3.12` (and `python3.14`) on MacBook supports PEP 604.
**Fix:** rerun smoke with `/opt/homebrew/bin/python3.12`. Audit rows wrote correctly (rows 859, 860).
**Rule:** for any LOCAL execution of baker-master code (smoke tests, one-off scripts, debugging), explicitly use `/opt/homebrew/bin/python3.12` (or higher), NEVER bare `python3`. Better: write a wrapper script `scripts/baker-py` that resolves to `/opt/homebrew/bin/python3.12` and use that in all docs / briefs / handovers. Add a CI guard that rejects `python3` (no version) in shell-script paths under `scripts/`.
**Anchor:** PR #173 smoke verification 2026-05-08T~09:34Z; baker_actions rows 859 (py3.12 success) vs failed local row attempt at 09:25Z (py3.9 audit fail).

### 63. No public surface for ad-hoc `send_whatsapp` invocation — incident smoke needs a documented trigger path (2026-05-08)
**Mistake:** brief §"Re-enable sequence" specified `send_whatsapp(text=..., chat_id=...)` smoke calls but did not specify HOW to inject those calls into the running prod system. No public API endpoint accepts arbitrary text+chat_id (`/api/whatsapp/backfill` is for ingest, not send). No Render Shell tool wired to the MCP. AH2-T improvised: SSH to Mac Mini for `DATABASE_URL`, source `config/.env` for `WAHA_BASE_URL` + `WHATSAPP_API_KEY`, run local Python pointing at prod DB. Worked, but fragile — required tribal knowledge about env-var locations across two machines.
**Why it happened:** Smoke design assumed an obvious trigger path; reviewer didn't probe "HOW does AH2 actually run this?" during brief review.
**Rule:** for any incident-fix brief that specifies live smoke tests against a prod side effect:
1. **Spec the trigger surface** in the brief: name the endpoint / shell command / script that AH2 will use to invoke the smoke. If none exists, the brief must spec building one (temporary debug endpoint behind `X-Baker-Key`, or Render Shell exec docs link).
2. **Verify the trigger surface in the brief review pass** — reviewer must answer "can I run this smoke from a fresh terminal in <5 min?" If no, brief is incomplete.
3. **Fallback options ranked**: (a) public API endpoint behind auth, (b) Render Shell exec command in the runbook, (c) local Python with prod env vars (document which env-var lives where), (d) pytest-equivalent (only acceptable for non-load-bearing or operationally-invasive paths, like the LID-DB outage in this brief's smoke #3).
**Anchor:** `BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md` v0.3 smoke verification 2026-05-08; AH2-T improvised local-Python-with-prod-env path.

### 64. f-string with backslash-escaped quotes inside expression braces is a SyntaxError on Python <3.12 (2026-05-11)
**Mistake:** `BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1.md` V0.2 §Implementation embedded a `python3 -c '...'` script that used `f"... {d[\"detail\"]} ..."` / `f"... {m[\"id\"]} ..."` patterns throughout. Backslash-escaped quotes inside an f-string expression brace is a SyntaxError on Python 3.9-3.11 ("f-string expression part cannot include a backslash"). PEP 701 lifted this restriction only in Python 3.12. The hook would have parsed cleanly on Director's Mac (Python 3.12.12) but every downstream call would have errored — except `python3 -c` swallowed the SyntaxError into a non-zero exit, the SessionStart hook then emitted no `additionalContext`, and ALL drain attempts would have failed silently. No status line, no traceback, no audit trail. The feature would have shipped looking-working but doing nothing.
**Pattern that fails:**
```python
print(f"... {d[\"key\"]} ...")    # SyntaxError on Python 3.9-3.11
print(f"... {m[\"id\"]} ...")     # same
```
**Fixes (both work):**
```python
print("... {} ...".format(d["key"]))      # .format() syntax
# OR alias first:
v = d["key"]; print(f"... {v} ...")        # drop the inner quote
```
**Why it happened:** Brief author wrote the embedded script in a context where Python 3.12 was assumed available. `feature-dev:code-reviewer` brief-review pass did not catch the f-string-backslash-quote pattern — the review caught 4 other blockers + 1 token-budget note but missed this one. B2 hit the SyntaxError live during the first test run (`bash -x` exposed `SyntaxError: f-string expression part cannot include a backslash`), diagnosed, refactored every offending line to `.format()`, and shipped. Saved a silent-failure deployment.
**Rule:** add to the brief-review checklist:
```
[ ] grep for f-strings with backslash-escaped quotes inside expression
    braces in any embedded `python3 -c '...'` block; rewrite via
    .format() OR alias the dict access to a local variable first
```
Pattern to grep: `f".*{[^}]*\\\\"` inside any embedded Python.
**Anchor:** `BRIEF_BRISEN_LAB_TERMINAL_BUS_DRAIN_ON_SESSION_START_1.md` V0.2; PR #183 (2026-05-11); B2 implementation pass caught what the brief-reviewer pass missed.

### 65. Cross-lane / security review: verify claimed defenses against threat-model scenarios, not test names (2026-05-16)
**Mistake:** PR #210 (`AO_PM_READ_CURATED_WIKI_1`) ship report listed 8 security defenses; defense #4 = *"Path resolution containment — string-prefix match on resolved paths defeats symlink escape."* AH2 cross-lane review (#301) green-lit because `test_symlink_escape_rejected` existed and `matter_dir.resolve()` + prefix-check was present in code. AH1 `/security-review` pass surfaced a NEW MEDIUM: per-file `is_file()` + `read_text()` follows file-level symlinks without re-validating containment. The directory-level defense was tested; the file-level was claimed-but-not-tested. AH2 missed it because the test name + code pattern matched the case the test exercised — not the broader "defeats symlink escape" claim.
**Why it happened:** Reviewer verified "each claim → matching test name → present" rather than enumerating the threat scenarios each claim should cover and tracing code-vs-tests against the full enumeration. Tests verify what was thought of, not what was claimed.
**Rule:** when reviewing a PR that lists numbered "security defenses" or "threat-model defenses":
1. Read each numbered claim wording exactly.
2. Enumerate the threat-model scenarios that wording covers — there will usually be MORE than one (directory-level symlink, file-level symlink, nested-link chain, parent-dir relative, etc.).
3. Read the code path that implements the defense. Trace whether ALL enumerated scenarios are handled.
4. Cross-check tests cover each enumerated scenario, not just the obvious one.
5. If code covers fewer scenarios than the claim wording implies, flag it — the brief is overclaiming.

Claim wording like "defeats X attack," "prevents Y," "handles Z" promises broader coverage than a single specific test case. Verify the breadth.

When in doubt: ask "what's the file-level / nested-link / edge-case version of this claim's threat?" — and read whether the code handles it.

Don't outsource the threat-model enumeration to the brief author. They were already in the code; they may have only thought of the scenario they tested.

Applies to: AH1 + AH2 `/security-review`, cross-lane review, picker-architect, feature-dev:code-reviewer on PRs with security claims.
**Anchor:** AH1 #306 post-merge analysis 2026-05-16 ~13:24Z on PR #210 (BRIEF_AO_PM_READ_CURATED_WIKI_1) — file-level symlink containment gap missed by AH2 cross-lane (#301) but caught by AH1 `/security-review`. Director ratified codification 2026-05-16 ~13:35Z.

### 66. AH1 math-transcription error in numeric brief specs — compute, don't transcribe (2026-05-17)
**Mistake:** AH1 dispatched a B2 amendment for PR #214 (GROK_API_CAPABILITY_1) specifying the expected per-call cost smoke value as `0.0000000012345` (8 zeros after the decimal = 1.2345e-9). The arithmetic is `12345 / 10**10 = 1.2345e-06` — 5 zeros, three orders of magnitude off. B2 ran the calculation independently while implementing, caught the discrepancy in bus #367, and asked AH1 to confirm. AH1 verified by `python3 -c "print(12345 / 10**10)"`, acknowledged the error in bus #368, and the corrected value shipped.
**Why it happened:** AH1 wrote the decimal literal from intuition instead of from arithmetic — eyeballed "many zeros plus the digits" without counting. Brief reviewer didn't recompute; computer didn't either. Only the implementing B-code, who actually had to use the number, did the math.
**Rule:** when dispatching numeric specs (expected values, thresholds, decimal literals, fixed-point comparisons), COMPUTE the value via `python3 -c` (or equivalent) and paste the literal output into the brief. Never transcribe from intuition. For any decimal literal with >3 zeros after the point, treat as a red flag and re-verify before sending the brief.
**Applies to:** all AH-authored briefs containing decimal constants, cost expectations, time thresholds, version-rank integers, percent values.
**Anchor:** AH1 → B2 PR #214 amendment dispatch 2026-05-17; bus #367 (B2 catch) + #368 (AH1 confirm).

### 67. B-code pre-flight doc claims are INPUT to AH1 audit, not trusted-by-default output (2026-05-17)
**Mistake:** PR #214 (GROK_API_CAPABILITY_1) pre-flight phase: B2 surfaced 4 divergences between the original brief §Scope and xAI's current docs (bus #347), framing the first divergence as "native xAI pattern is `search_parameters` dict on `/v1/responses`". AH1 greenlit the framing in bus #351 without independently fetching the xAI doc URL B2 had cited. Three gates later, `feature-dev:code-reviewer` flagged HIGH severity that newer xAI docs describe an `Agent Tools API` (`tools[]` array) and `search_parameters` is deprecated. A live smoke against `/v1/responses` returned HTTP 410 "Live search is deprecated. Please switch to the Agent Tools API" on the `search_parameters` shape, confirming gate-4 was right and AH1's #351 greenlight was wrong. Same failure pattern as #330 (AID schema-doc trust issue Director flagged earlier the same session).
**Why it happened:** AH1 treated B-code's "I checked the vendor doc" as a trusted output instead of as a research input requiring independent verification. The doc URL was sitting right there in the bus message; AH1 had to fetch it themselves to know what it actually said.
**Rule:** when a B-code's pre-flight surfaces vendor-doc citations, spec mismatches, or proposed wire-format resolutions, AH1 must independently fetch + read the cited doc URL before greenlight. Treat B-code doc-claims like AID design proposals — engineering inputs to be audited, not trusted-by-default. Same skepticism rule as `feedback_aid_proposals_need_engineer_verification.md`. If the doc URL is paywalled or behind a wall, dispatch via the appropriate channel (Perplexity Ask for synthesis, WebFetch for direct fetch); do NOT greenlight on hearsay.
**Applies to:** all AH1 → B-code pre-flight reply chains where the B-code cites external vendor docs, spec mismatches, deprecation warnings, or API-shape decisions.
**Anchor:** AH1-T #351 greenlight on B2 #347 framing → gate-4 FAIL on PR #214 → live smoke HTTP 410 confirms gate-4 → AH1-T self-audit honestly in bus #369.

### 68. Cost-governor wiring pattern is a reusable template for external-API capabilities (2026-05-17)
**Lesson type:** validated pattern (NOT a scar — capture for future reuse before it rots).
**Pattern:** for any external-API capability added to Baker, wire cost governance at the dispatch boundary in this shape:
1. **Pre-call:** `check_circuit_breaker(source)` — returns boolean / raises if budget exceeded for the day/month/window. Wrapped in `try/except` so an instrumentation failure does NOT block the dispatch (fail-open).
2. **Post-call:** `log_api_cost(model, input_tokens, output_tokens, source, matter_slug)` at the dispatch boundary, after the vendor call returns successfully. Wrapped in `try/except` for the same fail-open reason.
3. **Three dedicated tests:** (a) happy-path (call fires, cost logged, breaker untouched); (b) breaker-tripped (pre-call raises, dispatch refuses gracefully, no vendor call made); (c) import-fail (instrumentation module unavailable, dispatch proceeds without crash, error swallowed to logs).
4. **Matter-slug attribution is mandatory** — every external call surface accepts `matter_slug: str` and threads it into `log_api_cost`. Cost attribution per matter is the load-bearing operational invariant; without it the `/api/cost/today` aggregation is meaningless.
**Why it matters:** PR #214 (Grok) shipped with this pattern and gate-3 `code-architecture-reviewer` validated the M2 cost-governor RESOLVED finding via the three dedicated tests. Prod smoke confirmed cost attribution works end-to-end (3 calls, `grok-4.3` model + `grok_realtime` source + `theailogy` matter, all correctly attributed in `/api/cost/today`). Pattern survives the 4-gate review chain and the live-smoke validation — that's the criterion for "validated template."
**Rule:** when AH1 drafts a brief for a NEW external-API capability (post-Grok candidates: extended Anthropic cache-tier, OpenAI, Perplexity-sibling, Gemma SaaS variants), the brief §Implementation MUST include this 4-element cost-governor block as a Standards item. Skipping it is a brief-review blocker — same severity as the singleton-pattern check (Standard #8) or the migration-vs-bootstrap DDL check (Standard #4) in SKILL.md §Brief Authoring Standards.
**Applies to:** every external-API integration brief touching `/v1/...` (vendor LLM APIs), `/api/...` (vendor SaaS APIs), or analogous metered surfaces. NOT for internal MCP tool surfaces (those are governed by ClickUp BAKER-Space write cap + S2 atomic-logging invariant — different governance model).
**Anchor:** PR #214 gate-3 M2 fold (commit `c21f02ce`); 3 cost-governor tests in `tests/test_grok_capability.py`; live-prod smoke 2026-05-17 ~16:00Z showing `/api/cost/today` correctly attributing `grok_realtime` calls to `theailogy` matter.

### 69. Webhook subscription change requires handler-guard update — they are NOT orthogonal (2026-05-20)
**Mistake:** BRIEF_WAHA_OUTBOUND_CAPTURE_1 (PR #235) lifted the `fromMe=true` filter in the WAHA webhook handler to enable Director outbound capture. Brief §Fix 2 said *"Keep the `event_type != 'message'` guard (orthogonal)."* It wasn't orthogonal. WAHA's `message` event is inbound-only; capturing fromMe in real-time also requires switching the WAHA session subscription from `message` to `message.any`. Once the subscription was flipped (post-merge), the handler at `triggers/waha_webhook.py:830` returned `{"status":"ignored","event":"message.any"}` for every real Director outbound — silent drop. Architect verdict didn't catch it (Q3 only addressed re-attribution); gate-3/4 didn't catch it (no behavioral test against `message.any` event_type); live smoke caught it.
**Why it happened:** the brief author (AH1) wrote the guard rationale based on the CURRENT subscription (`message`), not considering that achieving Fix 2's goal (real-time fromMe capture) requires a coordinated subscription change on the WAHA side. The guard and the subscription are tightly coupled — flipping one without the other silently breaks the capture path.
**Rule:** when a brief modifies a webhook handler's behavior in a way that changes WHICH event types should be processed, the brief MUST also enumerate the required webhook-subscription configuration on the upstream service AND verify they remain consistent. For WAHA-shaped systems: brief MUST cite both (a) the handler-guard's accepted event_type set, and (b) the WAHA session config `webhooks[].events` value, and (c) demonstrate they cover the same set of events. Mismatch = silent capture drop, hardest-to-debug failure class.
**Applies to:** WAHA, but also Slack Events API, GitHub webhooks, Render webhooks, Stripe webhooks, Linear webhooks — any push-event integration where the upstream subscription and the downstream handler-guard must agree.
**Hot-fix:** `triggers/waha_webhook.py:830` now accepts `event_type in ("message", "message.any")` for forward + backward compat. WAHA session config flipped to `["message.any", "session.status"]` 2026-05-20.
**Anchor:** PR #235 merged `0e08ce5` 2026-05-20; smoke failed; hot-fix commit landed same session; brief author = AH1 (own scar).

### 70. 1Password "Baker API Keys" vault — item titles don't follow `<VARNAME>` convention; field names vary per item (2026-05-23)
**Mistake:** Ran `scripts/backfill_substack_archive.py --apply` post-PR-#251-merge with the natural-feeling env-source pattern `op read 'op://Baker API Keys/<VARNAME>/credential'` — got 3 `could not get item Baker API Keys/<VARNAME>` errors back-to-back for `VOYAGE_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`. Same wall hit earlier in the session on `RENDER_API_KEY`. Burned one foreground run + had to `op item list --vault "Baker API Keys"` to discover the actual item titles. Then ran a second time with corrected paths — script failed deep in the qdrant-client stack with `httpx.LocalProtocolError: Illegal header value` because the JWT pulled from 1P had **trailing whitespace** preserved by `op read` (qdrant_api_key had `Ek  ` with 2 trailing spaces), and `httpx` rejects header values with control/whitespace chars per RFC 9110. Third run with `tr -d '[:space:]'` strip succeeded.
**Two findings, one lesson:**

1. **1P item title convention is "API <Vendor>" not "<VARNAME>".** And the field name inside the item varies — sometimes `credential` (single secret), sometimes a custom field matching the env-var name (e.g. `API Qdrant` has BOTH `credential` AND `QDRANT_API_KEY` AND `QDRANT_URL` as separate fields). Correct paths observed this session:

   | env var consumed | 1P item title | field name |
   |---|---|---|
   | `RENDER_API_KEY` | `API Render` | `credential` |
   | `VOYAGE_API_KEY` | `API Voyager` | `credential` |
   | `QDRANT_URL` | `API Qdrant` | `QDRANT_URL` |
   | `QDRANT_API_KEY` | `API Qdrant` | `QDRANT_API_KEY` |
   | `SUBSTACK_COOKIE_natesnewsletter` | `SUBSTACK_COOKIE_natesnewsletter` | `credential` |

   The Substack item DOES follow the `<VARNAME>` title convention (because cowork-ah1 created it fresh this session per the `BRIEF_OP_TERMINAL_KEY_CREATE_SCHEMA_GUARD_1` schema we were just standardizing). The vendor API items predate that convention and have not been retitled. **There is no machine-readable manifest in the vault that maps env-var → 1P-item — `Baker — Render env-var map (manifest)` exists as a note but isn't structured for automated `op read`.**

2. **`op read` preserves trailing whitespace from 1P field values.** If anyone ever fat-fingered a key into 1P with a trailing space (or copy-paste from a wrapped UI did it for them), every consumer that uses the value as an HTTP header gets `httpx.LocalProtocolError: Illegal header value` — opaque, deep in the stack, miles from the actual cause. The qdrant-client error path doesn't say "your API key has whitespace" — it just prints the raw bytes with the trailing space at the end. Took ~30s of diff-staring to spot.

**Rules:**
- **For any new script that sources from "Baker API Keys" vault:** introspect first via `op item list --vault "Baker API Keys" --format json | jq` (or `op item get <title> --vault "Baker API Keys"` to inspect fields) — do NOT assume the item-title-equals-env-var-name pattern. The convention only holds for vault items created in 2026-05 onward (post-Director-ratification 2026-05-22 of the `BRIEF_OP_TERMINAL_KEY_CREATE_SCHEMA_GUARD_1` pattern); pre-existing vendor API items use `API <Vendor>` titles.
- **Always whitespace-strip `op read` values used as HTTP headers or URL components.** Standard pattern: `VAR="$(op read 'op://...' | tr -d '[:space:]')"`. Apply uniformly even when the secret "looks clean" — a 1P field UI that wraps long values can introduce trailing newlines/spaces on save without visual signal.
- **Future hygiene candidate:** a `Baker — Render env-var map (manifest)` 1P item already exists as a note. If we extend that to structured (title + 1P-item + field-name + strip-needed bool) per env var, an `~/.local/bin/baker-env-source <varname>` wrapper could replace ad-hoc `op read` everywhere — turns this lesson into infra. Queue as `BRIEF_OP_ENV_SOURCE_WRAPPER_1` if the same scar happens a third time.

**Applies to:** every operator-run script or B-code that sources secrets from the "Baker API Keys" vault. Most acute for scripts that consume API keys as HTTP headers (the failure mode is dropped deep in the client library; surface symptom is unrelated to the actual cause).
**Anchor:** 2026-05-23 PM2 post-PR-#251-merge backfill — wasted ~2 foreground runs (one on item-title mismatch + one on whitespace-in-JWT) before clean run completed at 20:08:18Z with 558/569 indexed, second idempotent retry catching 10 transient Voyage timeouts → 568/569 final coverage.

### Two-layer harness enforcement for mandatory SOPs (WRITE_BRIEF_SOP_ENFORCER_HOOK_1, 2026-05-24)

When a memory/skill mandate keeps getting forgotten, single-point enforcement
isn't enough. Pattern parallels render_env_guard.py (Layer 2 wrapper) +
.githooks/pre-commit Part 4 (Layer 3 audit):

- **Layer 2 (in-session):** PreToolUse hook blocks at the tool-call boundary.
  Bypass via env var (friction-free, stderr-logged for audit).
- **Layer 3 (git-time):** pre-commit hook scans staged content. Bypass via
  commit-msg trailer (audit-permanent in git log) OR env var for `-m`/`-F`.

Belt-and-braces. Layer 2 catches the Claude-Code path; Layer 3 catches `vim`,
`scp`, manual edits, bypass-env-set edits, edits from non-AH pickers.

**Implementation gotcha (caught at first test-run, not by inspection):** under
`set -u` + `trap ... ERR` (the same defensive posture used in
`ui-surface-prebrief-check.sh`), a `jq -e` returning non-zero inside `$(...)`
trips the ERR trap and the hook silently fails open. That defeats the gate
without warning. Fix: drop `-e` from the jq call and use plain stdout
("true"/"false") + a `|| echo "false"` fallback to make the assignment never
fail. Always test the **block** path explicitly; do not assume the **pass**
path covers it.

**Layer 3 trailer-bypass design gap (open for AH2 gate review):** the trailer
mechanism (`Brief-SOP-bypass: <reason>` in commit message) cannot fire reliably
from a pre-commit hook because git writes `.git/COMMIT_EDITMSG` at the
commit-msg stage (step 6 of git's commit sequence), AFTER pre-commit (step 2).
First-commit-of-fresh-repo + every `-m`/`-F` invocation: hook sees no
COMMIT_EDITMSG. Subsequent editor-flow commits: hook reads the PREVIOUS
commit's message (semantically wrong). The env-var bypass is the only path
that fires correctly across `-m`/`-F`/editor flows. Trailer code is kept in
the hook for future migration to a commit-msg-stage companion or for the
rare editor-flow archival commit; surfaced in WRITE_BRIEF_SOP_ENFORCER_HOOK_1
ship report for gate-1 architecture-review verdict.

Apply this two-layer pattern when:
- Director repeatedly reminds about a process rule
- Single mandate location (memory/skill/docs) is observably not enforcing
- Scar incident exists (render_env_guard: 2026-05-17 wipe; brief-SOP: weekly
  Director reminder cycle)

Anchor: Director chat 2026-05-23 evening; AH2 bus #788 (Layer 2) + bus #790
(Layer 3 amendment); B3 ship 2026-05-24.

**Fix-pass v2 amendments (bus #799 — lead REQUEST_CHANGES 2026-05-24):**
- **PreToolUse hook entries need explicit `timeout: 10`** — same convention as
  SessionStart hooks. Without it a hung hook blocks Claude Code indefinitely.
  Apply to every new PreToolUse hook entry going forward.
- **Hook install pattern = canonical + untracked symlinks**, not picker-side
  file copies. Source-of-truth lives at `~/baker-vault/_ops/hooks/<name>.sh`
  (committed); each picker installs via untracked symlink at
  `<picker>/.claude/hooks/<name>.sh -> ~/baker-vault/_ops/hooks/<name>.sh`.
  File copies drift on first patch; symlinks don't. Mirrors
  `ui-surface-prebrief-check.sh` precedent (2026-05-19). DO NOT commit hook
  scripts to baker-master `.claude/hooks/` — only the vault canonical is
  tracked.
- **Pre-commit section regex must be literal `^## `, not `^##?`.** The
  optional `?` quantifier accepts H1 (`# `), which violates the spec that
  requires H2. Caught by AH2 gate-4 with HIGH confidence on
  WRITE_BRIEF_SOP_ENFORCER_HOOK_1 v0.1. Add an H1-only regression test
  case whenever shipping a `^##` content-shape gate.
- **`settings.local.json` is gitignored local-override — do NOT install
  enforcement hooks there.** Use `settings.json` (or `.claude/settings.json`
  per picker). Enforcer wired in settings.local.json will not survive
  re-provisioning + may be hidden from collaborators.

### 71. Slugs bundling counterparty + entity name need AND-gate classifier rules (2026-05-24)
**Mistake:** `hagenauer-rg7` slug combines counterparty (`hagenauer`) + project entity (`rg7`). The matter classifier at `orchestrator/pipeline.py:_match_matter_slug` is OR-scored (each keyword hit = 2pts, threshold ≥3). Transcripts mentioning both `hagenauer` AND `rg7` in *unrelated* contexts (e.g. RG7 corporate-finance discussion with no dispute angle) scored 4pts and got tagged `hagenauer-rg7`. Hag-desk audit (bus #831, 2026-05-24) found 6 of 33 transcripts mistagged this way.
**Why it happened:** the slug name encodes two distinct entities. OR-scoring treats them as independently sufficient evidence. The dispute lexicon (Konkurs/Insolvenz/Forderungsanmeldung/Mangel/ClaimsMax/Schlussabrechnung) is what actually disambiguates "Hagenauer-the-dispute" from "Hagenauer-the-name mentioned in passing" or "RG7-the-SPV-in-corporate-finance-context."
**Rule:** for any matter slug whose name bundles a counterparty name + an entity name (or two ambiguous tokens), add a `classifier-keywords.yml` overlay at `baker-vault/wiki/matters/<slug>/` declaring `rule: require_all_groups` + multiple `groups`. Each group's keywords are OR'd internally; groups are AND'd across. Activated by `_match_matter_slug` automatically (no code change per-slug). Candidate slugs to audit for the same pattern: any slug containing a dash separator where both sides are independently meaningful tokens.
**Applies to:** transcript classification, future signal_queue classification, future deadline classification — anywhere `_match_matter_slug` is wired.
**Brief-authoring foot-gun corollary (b2 pre-flight 2026-05-24):** brief Step-1 exploration MUST cross-check every slug referenced in migration UPDATEs against `baker-vault/slugs.yml` AND every title-ILIKE predicate against actual prod row titles. b2 caught 4 brief slips before merge — `ao-holding` vs canonical `ao`, plus 3 ILIKE typos that missed commas/colons/missing-words in real titles. Pre-flight SELECT against prod with `HIT COUNT` per WHERE-clause is the cheap insurance.
**Anchor:** PR HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1, ship 2026-05-24. Source bus #831 + #839 + Director ratification 2026-05-24 + b2 pre-flight bus #860 (ao slug) + #864 (ILIKE typos).

### 72. CLI-agent installs need disk-file credential fallback — env-var inheritance unreliable across sandboxes (2026-05-29)
**Mistake:** codex full-harness install Phase 1 fold + Phase 2 used the canonical pattern of "picker function pre-fetches credentials from 1P in AH1's authenticated shell + exports as env vars + execs the CLI." Director relaunched codex 5+ times across 90 min before bus inbox helper returned a non-empty result. Codex's bash-tool sandbox strips parent process env, even with `[shell_environment_policy] inherit = "all"` set explicitly in `~/.codex/config.toml`. Symptom: helper "exited 1, no output" + AGENTS.md text said "BRISEN_LAB_TERMINAL_KEY_codex not in env."
**Why it happened:** codex (and likely other non-Claude-Code CLI agents — gemini-cli, anthropic-cli) executes tool subprocesses in a security sandbox that whitelists env vars rather than inheriting them. Config-level `inherit = "all"` declares INTENT but doesn't guarantee implementation. Disk-file fallback at `~/.<agent>/runtime-env` (mode 600) is the load-bearing path — env-var path is best-effort.
**Rule:** every CLI-agent picker function MUST write all required credentials to a 600-mode disk file at `~/.<agent>/runtime-env`, AND every helper script MUST source that file as Tier-2 fallback between env-var (Tier 1) and live `op read` (Tier 3). Three-tier resolution is the canonical pattern.
**Applies to:** any non-Claude-Code CLI agent install (codex today; gemini-cli, anthropic-cli, openai-cli when shipped). NOT applicable to Claude Code pickers (they execute helpers in the user's shell, env inheritance works).
**Anchor:** baker-master commit `fd29a75` Fold-1.7 disk-file fallback; SOP codified at `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` §Sixth-pass codify; full lived foot-guns at `~/baker-vault/_ops/agents/codex/INSTALL.md` §Lived foot-guns 2.

### 73. `set -euo pipefail` + missing binary = silent exit 127 (use command-v guard) (2026-05-29)
**Mistake:** codex bus-inbox helper used `set -euo pipefail` + `KEY="$(op read 'op://...' 2>/dev/null)"` for the credential-fallback path. In codex's sandbox (no `op` in PATH), the command-not-found triggered `set -e` at exit 127 BEFORE the empty-KEY error handler emitted any diagnostic. Codex UI showed "exited 1, no output" with zero stderr — undiagnosable without reproducing in a pristine `env -i` shell.
**Why it happened:** `set -e` fires on the failed assignment immediately; the `2>/dev/null` only redirects stderr, doesn't suppress the non-zero exit code. The subsequent `if [[ -z "$KEY" ]]` check + helpful echo never run.
**Rule:** every optional `op read` (or any optional command that may be absent from PATH) MUST be guarded with `command -v <cmd> >/dev/null 2>&1 &&` BEFORE the call, AND the call itself MUST end with `|| true` (or be wrapped in `if ... fi`). Same pattern for any optional CLI binary in shell scripts under `set -e`: `gh`, `psql`, `curl`, `jq`, `python3`, etc. Pre-flight in any helper-script review.
**Applies to:** any helper script under `set -euo pipefail` that has a fallback to a non-guaranteed binary. Particularly load-bearing in scripts called from sandboxed CLI agents.
**Anchor:** baker-master commit `09c6c21` Fold-1.6 guard; SOP at `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` §Sixth-pass codify; foot-gun 3 at `~/baker-vault/_ops/agents/codex/INSTALL.md`.

### 74. Audit all CLI-agent plugins for hook-injection on install — non-Claude-Code hook schemas are incompatible (2026-05-29)
**Mistake:** codex install Phase 2 left `[plugins."hookify@claude-plugins-official"] enabled = true` and `[plugins."security-guidance@claude-plugins-official"] enabled = true` per the codex-bundled defaults. Both plugins register Stop / UserPromptSubmit / PostToolUse hooks using the Claude Code JSON schema (`{decision: "block", reason: ...}` + `additionalContext`). Codex rejects the schema with `Stop hook (failed) error: hook returned invalid stop hook JSON output` on every reply. Six relaunches before surfaced + diagnosed.
**Why it happened:** Claude-Code-flavoured plugins assume Claude Code's hook contract. Non-Claude-Code CLI agents (codex, future gemini-cli) have different contracts. Plugin loaders don't check compatibility — they just register what's enabled.
**Rule:** for any non-Claude-Code CLI agent install, audit ALL `[plugins."*"]` entries in the agent's config for hook injection. Disable any plugin that registers Stop / UserPromptSubmit / PostToolUse hooks (the three Claude-Code-Director-facing hook points). SessionStart hooks are usually safe (and useful for bus drain) — keep enabled. Document the disabled plugins inline in config.toml with the reason + date so re-enables are deliberate.
**Applies to:** codex now; same audit on gemini-cli / anthropic-cli / openai-cli installs when they ship. Also applies any time Director adds a new Claude Plugins Official marketplace plugin in the CLI agent's config.
**Anchor:** `~/.codex/config.toml` 2026-05-29 disable comments at hookify + security-guidance entries; SOP at `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` §Sixth-pass codify §Plugin-hygiene; foot-gun 4 at `~/baker-vault/_ops/agents/codex/INSTALL.md`.

### 75. CLI loader description caps differ from Claude Code — pre-flight skill descriptions before propagation (2026-05-29)
**Mistake:** propagated 6 strategic-framework skills (`three-horizons`, `jtbd`, `wardley-mapping`, `pyramid-principle`, `helmer-7-powers`, `youtube-analyze`) to codex's `~/.agents/skills/` from `~/baker-vault/_ops/skills/` canonical via the standard sync pattern. Codex CLI's skill loader caps `description:` frontmatter at 1024 chars; all six were 1100-1300 chars (Claude-Code-tuned without that constraint). Codex silently skipped all six with `⚠ Skipped loading 6 skill(s)` startup banner. Functionally degraded — those 6 strategic frameworks unavailable inside codex sessions.
**Why it happened:** Claude Code's skill loader is permissive on description length; codex's is strict. The skill authors didn't know about codex's stricter limit because it wasn't documented in the harness-setup or skill-installation SKILL.md files.
**Rule:** before propagating ANY skill to a non-Claude-Code CLI agent, run a one-line check: `python3 -c "import re; [print(s,len(re.search(r'description:\s*\|?\n?((?:(?!^name:|^type:|^---).)+)',open('${SKILL}').read(),re.M|re.S).group(1).strip())) for s in [<slug>]]"`. Anything ≥1024 chars must be trimmed before sync. Drop the redundant "Use whenever" 3rd paragraph from frontmatter description (the SKILL.md body retains the detail; MANDATORY TRIGGERS line preserved).
**Applies to:** any CLI agent with a stricter skill loader than Claude Code. Codex confirmed today; gemini-cli + anthropic-cli unknown but likely similar.
**Anchor:** baker-vault commit `2f7e808` (6-skill trim); `harness-setup` SKILL.md Layer 1(c) now references this cap; foot-gun 1 at `~/baker-vault/_ops/agents/codex/INSTALL.md`.

### 76. Terminal.app plist rename — Cmd+Q + relaunch needed for menu cache refresh (2026-05-29 re-anchor)
**Mistake:** renamed codex Terminal profile "Codex 5.5" → "codex" via plistlib + `killall cfprefsd`. Confirmed via `defaults read` that disk + cfprefsd state was updated. Director opened "Shell → New Window" menu — entry still showed "Codex 5.5" because Terminal.app's in-process profile cache wasn't refreshed.
**Why it happened:** known but under-documented in the canonical SOP — Terminal.app reads its profile list at app launch + caches in-memory for the lifetime of the process. plistlib edit + cfprefsd flush updates disk + system preferences daemon, but NOT Terminal.app's RAM cache. Cmd+Q + relaunch reloads. Documented in HAG_WORKERS_PROFILE_INSTALL fourth-pass foot-gun (2026-05-24) as foot-note 4a but NOT enforced in every plist-mutating brief.
**Rule:** every install brief that mutates `~/Library/Preferences/com.apple.Terminal.plist` MUST end its ship report with a "Director Cmd+Q Terminal.app + relaunch" step + a verification line that the menu shows the new entry. AH1 cannot drive this step programmatically — it requires Director-side keyboard input. Confirm BEFORE declaring the install AC complete.
**Applies to:** ANY agent install involving a Terminal.app profile rename, command change, or add. Especially install briefs that change CommandString from one zshrc function to another (most common silent failure case).
**Anchor:** SOP §AC3 + §Known foot-guns 4a; 2026-05-29 codex install hit the same gap; foot-gun 5 at `~/baker-vault/_ops/agents/codex/INSTALL.md`.
