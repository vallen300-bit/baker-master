# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (evening, post-Phase-D-merge)
**Status:** OPEN — BRIDGE_HOT_MD_AND_TUNING_1

---

## Task: Implement BRIDGE_HOT_MD_AND_TUNING_1

Brief: `briefs/BRIEF_BRIDGE_HOT_MD_AND_TUNING_1.md` (this commit). Self-contained — read end-to-end. Bundles 4 fixes + 1 new feature, all in the bridge codepath.

**Why combined:** all touch `kbl/bridge/alerts_to_signal.py` + one new scheduler job + one Director-curated file. One PR pair, one deploy, one review cycle.

---

## Scope (full detail in brief)

1. **hot.md integration** — 5th axis in `should_bridge()`, populates existing `signal_queue.hot_md_match` column. Reads `baker-vault/_ops/hot.md` via the vault mirror Phase D just deployed.
2. **Stop-list patterns** from Day 1 Batch #1 noise (cigar, phone scams, fuel policy, retail turnover).
3. **Idempotency race fix** — Postgres advisory lock around the tick cycle. Alternative fallback (APScheduler `max_instances=1 + coalesce`) documented; **recommendation: advisory lock** (DB-enforced, survives scheduler restart + horizontal scale).
4. **Saturday morning hot.md nudge** — new `hot_md_weekly_nudge` APScheduler job, cron `0 6 * * SAT`, sends WhatsApp to Director via WAHA. Substrate-push per §9 of operating model.
5. **Schema migration** — `signal_queue.hot_md_match TEXT NULL`. Applied by MIGRATION_RUNNER_1 on deploy.

**baker-vault PR:** seed `_ops/hot.md` scaffold with header + comment block explaining usage. Initial priorities section blank; Director overwrites Saturday morning.

**Reviewer:** B3 (familiar with bridge internals from Phase D review that just cleared).

---

## Key constraints (from brief)

- Director-curated only — no code path writes hot.md.
- Stop-list additions are additive. Don't remove existing patterns.
- Advisory lock key must be stable (`hashtext(...)` or int constant — not mutable string).
- Short-pattern floor: 4-char minimum on hot.md entries (prevents "EU" matching everything).

---

## Pre-merge verification (NEW — per B3's N3 nit from Phase D)

Your ship report MUST include:
1. Migration applied cleanly on fresh TEST_DATABASE_URL (no duplicate-column errors).
2. Local dry-run: bridge tick against staging alerts with a sample `_ops/hot.md` → expected promote pattern + `hot_md_match` populated.
3. Advisory-lock proof: concurrent-tick test green.
4. `hot_md_weekly_nudge` job registered in APScheduler with correct cron.

AI Head will retroactively add a §Pre-merge verification block to the brief template after this ships.

---

## Paper trail

- Commit message: `feat(bridge): BRIDGE_HOT_MD_AND_TUNING_1 — hot.md axis + stop-list + dedup race + Saturday nudge`
- Co-Authored-By: your line + `AI Head <ai-head@brisengroup.com>`
- Ship report: `briefs/_reports/B1_bridge_hot_md_ship_<YYYYMMDD>.md` on baker-master
- Decision already stored: check with `mcp__baker__baker_raw_query` for `trigger_type='architectural_decision'` around 2026-04-20 evening if you want to see Director's ratification; AI Head will store a fresh decision post-merge.

## After this

Day 2 teaching fires immediately post-merge:
1. AI Head adds a test line to `_ops/hot.md`, verifies bridge sees it within 5 min.
2. AI Head generates Batch #2 (pre-flagged — Director confirms/overrides only) as soon as 5-10 new signals land.
3. Stop-list and hot.md iterate every ~12h for the convergence window.

Close tab after ship.
