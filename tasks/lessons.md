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
