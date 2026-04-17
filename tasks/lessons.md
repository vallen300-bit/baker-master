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
