# Code Brisen #4 — Pending Task

**From:** AI Head (ai-head-term-2026-04-22)
**To:** Code Brisen #4 (session tag `code-4-2026-04-22`)
**Task posted:** 2026-04-22 (re-routed from B2 → B4 on Director instruction)
**Status:** D1 + D3 + routing diagnostic SHIPPED. GO on D2. Proceed to D2 + D5 + cleanup.

---

## GO/NO-GO signal from AI Head — 2026-04-22 ~11:55 UTC

**Verdict: GO on Deliverable 2.**

Routing diagnostic (your `briefs/_reports/B4_AO_ROUTING_DIAGNOSTIC_20260422.md`, commit `ad9e3d2`): A=14, B=22, C=14 over 21d → case (d) routing works. Verdict accepted.

**Vault D1 coordination resolved.** Your local baker-vault commit `664918d` is pushed to `origin/main` as `91b63c5` (cherry-picked onto latest origin — 2 older orphan `ops:` commits from Director's Apr 21 work are preserved on local branch `backup-local-20260422` in `~/baker-vault`; they are not in this push and stay Director's call). Render's `baker-vault-mirror` needs to sync before you run the Deliverable 2 ingest — verify presence with:

```bash
# on Render service shell post-deploy
ls /opt/render/project/src/baker-vault-mirror/wiki/matters/oskolkov/ | head
# expect: _index.md, psychology.md, investment-channels.md, etc.
```

If mirror is stale at ingest time, wait for next sync or investigate the mirror-update mechanism before inserting stale rows into `wiki_pages`.

## Follow-up flag — RETIRED 2026-04-22 ~12:00 UTC

The 10-day ao_pm silence since Apr 12 was flagged in an earlier draft of this signal. Director confirmed: **expected, not an anomaly.** No post-ship investigation needed. Drop from the Ship Report.

## Schema corrections you flagged

Noted in your diagnostic:
- `email_messages` uses `sender_email` / `full_body` / `received_date`
- `whatsapp_messages` uses `timestamp`

Fold these into your ingest script's error paths if any (unlikely — ingest doesn't touch those tables). Also fold into Ship Report's "brief corrections captured" section so future dispatches use the right columns.

## Remaining work (in order)

4. **Deliverable 2 — Runtime wiring.** `_resolve_view_dir` helper + `_load_pm_view_files` call site + `PM_REGISTRY["ao_pm"]` path flip + hyphenated filenames + sub-matter on-demand loader + `PM_REGISTRY_VERSION` bump to 2. Add `scripts/ingest_vault_matter.py` (new). Ship the code deploy. Then **immediately run `python3 scripts/ingest_vault_matter.py oskolkov` once on Render** — mandatory. Verify wiki_pages row count matches vault file count.

5. **Deliverable 5 — Weekly vault lint + scheduler wiring.** `scripts/lint_ao_pm_vault.py` (new) + `_run_ao_pm_lint` helper + APScheduler job in `triggers/embedded_scheduler.py` (Sunday 06:00 UTC, piggyback the pattern at line 221 `wiki_lint`).

6. **Cleanup.** After Deliverable 2 Quality Checkpoint 11 passes in production, `git rm -r data/ao_pm/`.

7. **Ship report** — `briefs/_reports/B4_AO_PM_EXTENSION_1_20260422.md` with QC 1-14 + the 10-day silence flag + the schema-correction note.

---

## Lane rule (scope lock)

You are **Cortex-isolated**. Stay in the AO PM lane. B1 / B2 / B3 + primary AI Head are on Cortex unblock — do not touch Cortex / KBL / CHANDA / signal_queue / PR #38–40 fallout or `kbl_log`-driven work. If anything in this brief surprises you as Cortex-adjacent, stop and flag AI Head (this one) before proceeding.

---

## Task

Read and execute `briefs/BRIEF_AO_PM_EXTENSION_1.md`. Full scope; ~6h; Medium complexity. No tonight deadline — take the time to do it right.

### Order of work

1. **Deliverable 1 — Vault migration** (`baker-vault/wiki/matters/oskolkov/`). 8 files `cp`/rename + frontmatter, 7 new scaffolds, 3 Gold shells, `ao_pm_lessons.md` (Deliverable 4 folded in here), `interactions/README.md` stub. Commit in the vault repo. Do NOT delete `data/ao_pm/` yet.

2. **Deliverable 3 — System prompt Part C addendum.** Edit `AO_PM_SYSTEM_PROMPT` literal in `scripts/insert_ao_pm_capability.py` to append the `ON DATES AND TIMESTAMPS — TACTICAL (MANDATORY)` block. Rerun the script against prod. Verify via SQL. No code deploy needed; DB-only update.

3. **BLOCKING GATE — Pre-deploy staleness diagnostic** (30 min). Run the 4 SQL queries (A, B, C, D) in the brief. File `briefs/_reports/B4_AO_ROUTING_DIAGNOSTIC_20260422.md` with the inputs-vs-fires delta and a verdict per the 3-branch decision tree (routing works / routing broken / quiet matter). Report **must exist before Deliverable 2 deploys**.

4. **Deliverable 2 — Runtime wiring.** `_resolve_view_dir` helper + `_load_pm_view_files` call site + `PM_REGISTRY["ao_pm"]` path flip + hyphenated filenames + sub-matter on-demand loader + `PM_REGISTRY_VERSION` bump to 2. Add `scripts/ingest_vault_matter.py` (new). Ship the code deploy. Then **immediately run `python3 scripts/ingest_vault_matter.py oskolkov` once on Render** — mandatory. Without ingest, `wiki_pages` serves stale 8-row content and the migration is silent no-op.

5. **Deliverable 5 — Weekly vault lint + scheduler wiring.** `scripts/lint_ao_pm_vault.py` (new) + `_run_ao_pm_lint` helper + APScheduler job in `triggers/embedded_scheduler.py` (Sunday 06:00 UTC, piggyback the pattern at line 221 `wiki_lint`).

6. **Cleanup.** After Deliverable 2 Quality Checkpoint 11 passes in production (AO PM invocation reads vault content), `git rm -r data/ao_pm/`.

### Deployment order and rollback paths are in the brief (§"Deployment Order" + §"Rollback").

## Deliverable

- Ship report: `briefs/_reports/B4_AO_PM_EXTENSION_1_20260422.md` — covering all 5 deliverables + Quality Checkpoint 1-14 + `data/ao_pm/` deletion timestamp + any residual work recommendations.
- Routing diagnostic report: `briefs/_reports/B4_AO_ROUTING_DIAGNOSTIC_20260422.md` — separate file, written before Deliverable 2 ships.
- Vault repo commit (Deliverables 1 + 4, folded into one commit per brief).
- baker-code repo commits (Deliverables 2, 3, 5 — separate commits OK for review readability).

## Pass criteria

- All 14 Quality Checkpoints in the brief pass.
- Routing diagnostic verdict recorded and honored (if "routing broken" → Deliverables 2 + 5 held; ship D1 + D3 + D4 only and flag AI Head).
- `capability_sets.system_prompt` for `ao_pm` contains `'ON DATES AND TIMESTAMPS'`.
- `wiki_pages` rows for `agent_owner='ao_pm'` match vault file count after ingest. Slugs follow `{pm_slug}/{base}` convention per `_seed_wiki_from_view_files` (see brief §Key Constraints on Deliverable 2).
- Post-deploy AO PM invocation surfaces dated citations per Part C format (informal smoke test by Director; escalate to AI Head if it doesn't).

## Key corrections from `/write-brief` exploration + REVIEW passes (don't re-discover)

- **Table name:** `baker_corrections`, NOT `capability_corrections`. The v3 ideas file has the wrong name; brief uses the real name (`memory/store_back.py:508`).
- **Slug convention:** `{pm_slug}/{base}` where base is lowercased with `_`→`-`, `_index` or `schema` → `index`. Per `_seed_wiki_from_view_files` at `memory/store_back.py:2544-2547`. `_load_wiki_context` orders by `slug LIKE '%%/index'` — hitting that is load-bearing.
- **`wiki_pages` schema:** columns are `slug, title, content, agent_owner, page_type, matter_slugs (TEXT[]), backlinks, generation, updated_at, updated_by`. Ingest sets `matter_slugs=['ao','hagenauer']` for ao_pm + `updated_by='ingest_vault_matter'`.
- **Decomposer logging:** there is no `decomposer_decisions` table. Decomposer runs land in `capability_runs` WHERE `capability_slug='decomposer'`. Routing diagnostic Query D is corrected in the brief.
- **`data/ao_pm/` has 8 files, not 7.** `ftc-table-explanations.md` is on disk but was missing from PM_REGISTRY's `view_file_order`. Brief adds it.
- **`wiki_pages` (Postgres) wins over filesystem** when `cortex_config.wiki_context_enabled='true'` (`orchestrator/capability_runner.py:844-859`). That's the current prod state. Ingest is mandatory.
- **APScheduler pattern** for Deliverable 5: copy the existing `wiki_lint` pattern at `triggers/embedded_scheduler.py:221` — do not invent a new scheduler style.
- **`baker-vault` and `baker-code` are separate git repos.** Vault commits in `~/baker-vault`; code commits in your baker-code working copy.

## Do NOT

- Do NOT modify `orchestrator/pm_signal_detector.py` — routing patterns already correct for AO PM.
- Do NOT modify `_load_wiki_context` priority logic (line 844-859). Dual-run stays; ingest handles staleness.
- Do NOT change `cortex_config.wiki_context_enabled` flag.
- Do NOT touch MOVIE AM (`PM_REGISTRY["movie_am"]` or `data/movie_am/`) — separate brief.
- Do NOT delete `data/ao_pm/` until Deliverable 2 Quality Checkpoint 11 passes in production.
- Do NOT skip the BLOCKING GATE. Diagnostic report filed first.

## Lessons to apply (from `tasks/lessons.md`)

- **#2 / #3:** verify DB schema + column names — the brief already did the legwork; trust the brief over any stale reference doc. If you hit an unknown table/column anyway, `SELECT column_name FROM information_schema.columns WHERE table_name='X'` first.
- **#17:** verify function signatures before adding code. The brief's code snippets are grep-verified; if you extend them, grep again.
- **#12:** push before declaring done. Local edits mean nothing until Render deploys.
- **#16:** `git add briefs/` after writing or finishing. This dispatch is tracked via commit a4e540c (brief).
- **#13 / #15:** three-way LLM match — N/A, this brief adds zero LLM call sites.

## Working dir

`~/bm-b4/01_build`. Before starting:

```bash
cd ~/bm-b4/01_build && git pull -q
cd ~/baker-vault && git pull -q
```

## Ship report target

`briefs/_reports/B4_AO_PM_EXTENSION_1_20260422.md` (not B2 — session re-routed).

— AI Head (ai-head-term-2026-04-22)
