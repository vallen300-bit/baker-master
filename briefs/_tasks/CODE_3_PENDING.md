# CODE_3_PENDING — B3: PLAUD_SENTINEL_1 — 2026-04-26

**Dispatcher:** AI Head A (Build-lead)
**Working dir:** `~/bm-b3`
**Branch:** `plaud-sentinel-1` (create from main; B3 currently on main but may need pull).
**Brief:** `briefs/BRIEF_PLAUD_SENTINEL_1.md`
**Tier B task entry:** `briefs/_tasks/PLAUD_SENTINEL_1.md`
**Status:** OPEN — first M1-out-of-band Tier B sentinel build
**Reviewer on PR:** AI Head B (cross-team) + **B1 situational review** (3 trigger classes: secrets / external API / cross-cap state writes)

**§2 pre-dispatch busy-check** (per `_ops/processes/b-code-dispatch-coordination.md`):
- Mailbox prior state: `COMPLETE — PR #62 KBL_PEOPLE_ENTITY_LOADERS_1 merged as 5ae6545`. Idle. **This dispatch supersedes.**
- Branch prior state: main, post-#62 merge. Pre-execution `git checkout main && git pull -q` resolves.
- B1: idle, mailbox COMPLETE, on main behind 5. Available for situational review at PR time.
- B2: in flight on WIKI_LINT_1 (dispatched ec25c38). No file overlap with B3 PLAUD work.
- B4: reserved for fix-backs.
- No file overlap with B2 (different `triggers/` files; different scheduler job; different table/collection).

**Dispatch authorisation:** Director 2026-04-26: *"ok, pls give a task to AI Head to integrate Plaud now"*; AI Head A confirmed token provisioned + auth working at `op://Baker API Keys/Plaud API Token/credential` against `https://api-euc1.plaud.ai` (returns 404 on unknown paths, NOT 401 — auth layer passes).

---

## Critical pre-build heads-up

**Plaud has no public API.** The token is a web JWT scraped from `web.plaud.ai` localStorage. Endpoint paths must be reverse-engineered from DevTools network capture. Director's browser session is the source. See brief §"Token findings" for context.

**Step 0 of your build (BEFORE writing any sentinel code):**
1. `op read "op://Baker API Keys/Plaud API Token/credential"` — confirm fetch works in your worktree.
2. Smoke-test bearer auth against `https://api-euc1.plaud.ai/<some-path>` — confirm 404 (not 401) before proceeding.
3. **Endpoint discovery:** if AI Head A's probe set didn't find the recordings-list path, ask AI Head A to relay a DevTools capture from Director. Do NOT brute-force probe production for >30 min — surface the block.
4. Document discovered endpoints in `briefs/_reports/B3_plaud_sentinel_1_<YYYYMMDD>.md` Appendix A (literal request + response shape).

## Brief route (charter §6A)

`/write-brief` 6 steps applied:
1. EXPLORE — done by AI Head A:
   - Read RA spec (`baker-vault/_ops/ideas/2026-04-26-plaud-sentinel-integration.md`)
   - Verified token in 1Password — entry exists, token authenticates, region EU-Central-1
   - Probed 18 common API paths — all 404 (auth passes, paths unknown)
   - Inspected Todoist + Fireflies sentinel patterns (`triggers/*` modules) for mirror
   - Confirmed migration-vs-bootstrap drift trap (LONGTERM.md feedback) applies — `_ensure_plaud_notes_base()` MUST match migration column types
2. PLAN — embedded in brief (data plane / control plane / retrieval plane).
3. WRITE — full brief at `briefs/BRIEF_PLAUD_SENTINEL_1.md`.
4. TRACK — this mailbox + Tier B task entry at `briefs/_tasks/PLAUD_SENTINEL_1.md`.
5. DOCUMENT — PR description MUST include:
   - Discovered Plaud endpoints (Appendix A)
   - Migration-vs-bootstrap drift check output (literal grep)
   - Render env var confirmation (`PLAUD_TOKEN`, not `BAKER_PLAUD_API_TOKEN`)
6. CAPTURE LESSONS — surface any reverse-engineering pain to `tasks/lessons.md`.

## Code Brief Standards compliance

- **API version:** Plaud internal API (no public version). Token type: Bearer JWT, region EU-Central-1 (`https://api-euc1.plaud.ai`).
- **Deprecation check date:** B-code logs probe timestamp + token-fetch-from-op timestamp in commit body.
- **Fallback:** `PLAUD_SENTINEL_ENABLED=false` (default) keeps scheduler dormant. 401/403/410: log + watermark + Slack alert; never crash scheduler.
- **DDL drift:** `_ensure_plaud_notes_base()` in `memory/store_back.py` MUST match `migrations/NNN_add_plaud_notes.sql` column types EXACTLY. Test asserts type-alignment. Pre-commit grep: `grep -n "plaud" memory/store_back.py` → verify no pre-existing bootstrap with type drift.
- **Literal pytest output:** ≥20 tests across 4 test files. NO "passes by inspection".

## Verification before shipping

Brief §"Verification criteria" (1-6 items). Items 5 (PR docs: endpoint Appendix + migration grep + env var) and 6 (sentinels.md update — AI Head A handles, NOT B3) are non-negotiable PR-description items.

## Ship report path

`briefs/_reports/B3_plaud_sentinel_1_<YYYYMMDD>.md`

Must include Appendix A (discovered Plaud endpoints with literal curl outputs).

## Trigger classes hit (B1 situational review)

3 of 7 trigger classes hit per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`:
1. Secrets handling (Plaud token fetch via op CLI)
2. External API (new Plaud cloud integration)
3. Cross-capability state writes (new table + Qdrant collection + scheduler job)

→ B1 reviews PR before AI Head A runs `/security-review` + merges.

## Cross-stream

- Parallel-safe with B2 (WIKI_LINT_1) — zero file overlap.
- Parallel-safe with future RA spec deliveries for M1.3 + GOLD + M1.4.
