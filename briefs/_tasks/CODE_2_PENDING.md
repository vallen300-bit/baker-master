# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning, post-B1 FEEDLY_WHOOP_KILL ship)
**Status:** OPEN — PR #24 FEEDLY_WHOOP_KILL review

---

## Task: PR #24 review

B1 shipped at `9600168` on branch `feedly-whoop-kill`. Scope = retire two dead sensors (Whoop + Feedly): delete `_ensure_whoop_tables` + `upsert_whoop_record` from `memory/store_back.py` (zero callers), scrub Whoop examples from `orchestrator/agent.py` (3 string edits), drop `whoop` from `orchestrator/complexity_router.py` regex, remove phantom `whoop_trigger.py` line from `.claude/agents/ai-head.md`, update `.claude/agents/baker-it.md` + ai-head `MEMORY.md` sentinel count, generalize one Feedly docstring in `triggers/rss_client.py`.

Brief: `briefs/_tasks/CODE_1_PENDING.md` at `418110b`.

**PR URL:** https://github.com/vallen300-bit/baker-master/pull/24

### Verdict focus

- `grep -ri "whoop" . --exclude-dir={.git,node_modules}` → zero matches (except potentially historical files like `tasks/lessons.md`, `briefs/_handovers/`, `briefs/_reports/` which are archive/frozen and out of scope).
- `grep -ri "feedly" . --exclude-dir={.git,node_modules}` → zero matches (same archive carve-out).
- `whoop_records` table NOT dropped (schema preserved per brief).
- `rss_feeds` / `rss_articles` tables NOT touched (direct RSS continues).
- No regressions: `pytest tests/` count matches main baseline (B1 reports 16/596 same as `main@34a9648`).
- No schema changes. No migration file added.
- Other `_ensure_*` methods in `store_back.py` (Qdrant collection ensures, signal_queue ensures, etc.) MUST remain intact. Spot-check.
- The 3 Tier B items B1 flagged in the PR description (Render env-var scan, `trigger_watermarks` row delete SQL, CLAUDE.md Dropbox edit) are AI Head's post-merge responsibilities — DO NOT execute them as part of this review.

Report to `briefs/_reports/B2_pr24_review_<YYYYMMDD>.md`. APPROVE / REDIRECT / REQUEST_CHANGES. If APPROVE, AI Head auto-merges per Tier A protocol.

Expected time: 15-20 min.
