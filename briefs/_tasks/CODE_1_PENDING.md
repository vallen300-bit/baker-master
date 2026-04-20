# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (morning, post-sensor-audit)
**Status:** OPEN — FEEDLY_WHOOP_KILL cleanup PR

---

## Task: FEEDLY_WHOOP_KILL — retire two dead sensors from code, docs, and watermarks

Director-authorized 2026-04-20. Whoop was retired long ago (no poller exists); Feedly is being retired now (Director: "we do not use it. Too expensive. Baker switched to direct RSS polling"). Both leave cruft across the codebase. One clean PR removes both.

Target PR: TBD. Branch: `feedly-whoop-kill`. Base: `main`. Reviewer: B2.

### Scope

**Part A — Whoop cleanup:**

1. `memory/store_back.py` — delete these dead-code blocks (no remaining callers — AI Head verified):
   - `_ensure_whoop_tables` method (around line 1434-1468)
   - `upsert_whoop_record` method (around line 3321+)
   - Any call site of `_ensure_whoop_tables` in `__init__` (grep confirms zero callers in current main — confirm before deleting)
2. `orchestrator/agent.py` — remove the two Whoop mentions (around lines 631 and 695). These are example strings in a Chrome-browsing tool description ("WHOOP 4.0 Band"). Replace the Whoop example with a neutral one (or just delete the example — context should still read cleanly).
3. `orchestrator/complexity_router.py` line 58 — remove `whoop` from the regex keyword list. The regex pattern is `\b(?:amazon|whoop|rode|microphone|product|website)\b` — drop `whoop` from the alternation.
4. **Do NOT drop the `whoop_records` table.** Data retention is fine; we just stop writing to it. Schema stays.
5. **Do NOT touch Whoop-related env vars on Render** — flag any you find in the PR description so AI Head can remove them as a separate Tier B step.
6. Add one-line migration note: `trigger_watermarks` has one stale row (`source='whoop'`). Delete it via a one-shot SQL note in the PR description so AI Head can run it post-merge. (The row is cosmetic — shows up as "stale sentinel" in health checks.)

**Part B — Feedly cleanup:**

1. Grep the entire repo for `feedly` / `Feedly` / `FEEDLY` case-insensitive. Expected hits: code comments, docstrings, maybe a triggers module. Remove each reference with context preserved (if a comment reads "polls RSS via Feedly aggregator", replace with "polls RSS feeds directly" or similar).
2. **Do NOT touch `rss_feeds` / `rss_articles` tables** — direct RSS polling continues. Only Feedly-aggregator code/comments come out.
3. Remove the `FEEDLY_API_KEY` / `FEEDLY_TOKEN` env var checks if any exist in `config/settings.py` or similar.
4. Flag any Feedly-related env vars still set on Render in the PR description — AI Head removes them as a Tier B step post-merge.

**Part C — Documentation:**

1. Repo `README.md` (if it mentions Feedly or Whoop as data sources): update to reflect 9 → 7 live sentinels (Email, ClickUp, RSS, Todoist, Dropbox, Slack, WhatsApp, Fireflies — drop Whoop entirely).
2. `CLAUDE.md` is at Director's Dropbox root — **DO NOT edit from this repo.** Just flag in PR description that CLAUDE.md at `/Users/dimitry/Vallen Dropbox/Dimitry vallen/CLAUDE.md` references both Feedly and Whoop and needs manual Director update. (AI Head will handle the Dropbox-side edit separately; per memory rule, B-codes don't touch Dropbox paths.)
3. No new docs. No migration to write. This is pure cleanup.

### Acceptance criteria

1. `grep -ri "whoop" . --exclude-dir={.git,node_modules}` returns zero matches (excluding any archived/retired folder if one exists).
2. `grep -ri "feedly" . --exclude-dir={.git,node_modules}` returns zero matches.
3. `pytest tests/` full suite green (the pre-existing `extractors.py` py3.9 landmine is out of scope — flag, don't fix).
4. No schema changes. No data migrations in this PR. `whoop_records` table and `rss_feeds` table both intact.
5. PR description lists explicitly: (a) any Render env vars to remove (AI Head's Tier B step), (b) the one-shot SQL to clean `trigger_watermarks` (AI Head runs post-merge), (c) CLAUDE.md flag for Director.

### Trust markers (lesson #40)

- **What in production would reveal a bug:** nothing visible — both sensors are already silent. Dead-code removal. Post-merge the watermark listing should show one fewer stale source (after AI Head runs the SQL note).
- **Risk of silent breakage:** low. `_ensure_whoop_tables` is only called if there's a caller in `__init__` — verify zero callers before deleting. Same for `upsert_whoop_record`.

### PR message template

```
FEEDLY_WHOOP_KILL: retire two dead sensors from code, docs, and watermarks

Whoop retired long ago (no poller); Feedly retired 2026-04-20 per Director
("too expensive, direct RSS polling only"). One PR to clean both from code
comments, orchestrator tool descriptions, complexity-router regex, dead
store_back methods, and docs.

Schema preserved. No data migration. Env var cleanup + watermark row
delete flagged as separate Tier B steps for AI Head post-merge.

Co-Authored-By: Code Brisen 1 <code-brisen-1@brisengroup.com>
```

Expected time: 30-45 min including full-repo grep pass. Ping B2 for review when CI green.
