# Handover — AI Head #1 — 2026-04-23 MORNING (Team 1 post-GUARD_1 ship + Mac Mini install)

**Date:** 2026-04-23 ~07:30 UTC
**From:** AI Head #1 (outgoing — Team 1 / meta-persistence lane this session)
**To:** Fresh AI Head #1 instance
**Director:** Dimitry Vallen
**Supersedes:** `briefs/_handovers/AI_HEAD_20260422_AFTERNOON.md`
**Your immediate job:** continue M0 quintet drafting — LEDGER_ATOMIC_1 + KBL_SCHEMA_1 next. No in-flight PRs; queue fully drained.

---

## 🚨 Read first — charter is unchanged

Canonical: `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md`.
TL;DR: Director is CEO. AI Head executes ALL technical work autonomously, consulted only on the 13 named Cortex Design prerogatives in §4. Post-facto plain English, no re-explanation in chat, report on close. Charter §2 bank-client frame re-invoked this session ("See for yourself what works better") — Director does not want tactical questions; route like a bank handling a wire transfer.

**Active session rules** (from Session 2):
- Parallel-teams pattern ratified 2026-04-23. Team 1 (you) = meta + M0 quintet. Team 2 = MOVIE AM (CLOSED as of this handover).
- Triplet write authority: Team 1. Team 2 was logging to scratch; scratch merged + retired this session.
- Relay-tag `[TEAM-1]` prefix on asks / reports to Director for parallel-team disambiguation.
- B-code lane rule: **don't invent lane models.** Route to whichever Brisen is proven + idle. Lesson captured this session (Director corrected b5 dispatch → b1 in <2 min).

---

## 🎯 What landed this session (3 PRs merged + 1 hook install + 1 scratch retirement)

### PRs shipped — all Team 1

| # | PR | Merge | Shape |
|---|----|-------|-------|
| #45 | CHANDA_ENFORCEMENT_1 | `3b60b0d` 05:04 UTC | Pure-insert `CHANDA_enforcement.md` at repo root (76 lines, §1–§7, amendment log). First of CHANDA detector sub-briefs. |
| #48 | AUDIT_SENTINEL_1 | `5831c77` 06:34 UTC | First-fire observability for `ai_head_weekly_audit`. New `scheduler_executions` PG table, extended `_job_listener`, new cron `ai_head_audit_sentinel` Mon 10:00 UTC. **Pre-merge rebase required** — PR #47 MOVIE_AM landed overlapping `triggers/embedded_scheduler.py` job-registration block; kept both additions; `--force-with-lease` to PR branch only. |
| #49 | AUTHOR_DIRECTOR_GUARD_1 | `679a684` 07:19 UTC | CHANDA detector #4 (pre-commit hook) + §7 amendment-log entry. Intent-based commit-signing mechanism (hook checks message for `Director-signed:` quote marker). Second of CHANDA detector sub-briefs. |

### Post-merge SSH install (this session, autonomous per charter §3)

**CHANDA invariant #4 is LIVE on Mac Mini baker-vault.** Installed at `~/baker-vault/.git/hooks/pre-commit` (3562 bytes, exec bit preserved). Smoke-tested both paths:
- Reject without `Director-signed:` marker → exit 1 + CHANDA #4 rejection message.
- Allow with marker → exit 0.

Baker-master belt-and-braces install deferred — requires Director's local machine action (out of AI Head reach).

### MOVIE AM scratch merged

`SCRATCH_MOVIE_AM_20260423.md` merged into canonical triplet (`ARCHIVE.md` Session 2 block + `OPERATING.md` refresh + `SKILL.md` rules 7-9 appended + `actions_log.md` entry). Baker-vault commit `f7c0176`. Scratch file retired.

### SKILL.md §Brief Authoring Standards now has 9 rules

Rules 7-9 added this session (from MOVIE AM close + own PR #48 experience):
7. `file:line` citations must be verified by reading source, not brief-quoted code blocks.
8. Singleton pattern `._get_global_instance()` mandatory (SentinelStoreBack, SentinelRetriever). `scripts/check_singletons.sh` is SoT.
9. Post-merge scripts invoked from working tree need `git pull --rebase origin main` immediately before run.

---

## 🔥 Current state at handover (~07:30 UTC)

### PRs: **0 open.** Queue fully drained. No review in flight.

### Infra all green
- **baker-master main:** `679a684` (PR #49 merge + ship report `76d2daa`).
- **baker-vault main:** `faee568` (Research Agent pre-mortem ratification) > `6db0ce2` (pre-mortem stage) > `f7c0176` (triplet merge this session).
- **Render deploy:** Baker live at `baker-master.onrender.com`. Next deploy (post PR #49 merge) carries CHANDA detector #4 hook script into the baker-master repo (but hook ONLY fires on baker-vault commits since Mac Mini is the single writer per CHANDA #9).
- **Weekly audit cron (PR #44):** `ai_head_weekly_audit`, Mon 09:00 UTC, first fire `2026-04-27T09:00:00Z`. Env kill-switch `AI_HEAD_AUDIT_ENABLED`. PG table `ai_head_audits`.
- **Sentinel cron (PR #48):** `ai_head_audit_sentinel`, Mon 10:00 UTC (1h offset). Env kill-switch `AI_HEAD_AUDIT_SENTINEL_ENABLED`. PG table `scheduler_executions`. Clean confirm silent; miss → Slack DM `D0AFY28N030`.
- **CHANDA detector #4 (PR #49):** hook LIVE on Mac Mini baker-vault. Script content in baker-master at `invariant_checks/author_director_guard.sh`.

### Brisens
- **b1** — idle. Proven this session (3 ships: CHANDA_ENFORCEMENT + AUDIT_SENTINEL + AUTHOR_DIRECTOR_GUARD).
- **b3** — idle. Did 3 reviews (PR #45 APPROVE + PR #48 APPROVE + PR #49 APPROVE). All clean.
- **b5** — idle, fresh clone at `~/bm-b5` (HEAD `63af5b1` at time of clone — need `git pull` before first use). Never used; CODE_5_PENDING.md deleted this session.
- **b2 / b4** — Team 2's Brisens (MOVIE AM). Team 2 closed MOVIE AM end-to-end. Don't dispatch to b2/b4 without Team 2 coordination (or Director reassignment).

### Vault hooks state
- Mac Mini `~/baker-vault/.git/hooks/pre-commit` — CHANDA invariant #4 installed, tested.
- Baker-master `.git/hooks/pre-commit` — NOT installed (requires Director-local action).
- Other invariant hooks: NOT yet installed. Detectors #2 (ledger atomic) + #9 (Mac Mini writer audit) are the next 2 CHANDA sub-briefs to ship.

---

## 🎯 Critical path (your first 15 minutes)

1. Read the charter — `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md` (unchanged).
2. Read OPERATING.md at `/Users/dimitry/baker-vault/_ops/agents/ai-head/OPERATING.md` (rewritten this session — reflects post-GUARD_1 state).
3. Skim ARCHIVE Session 2 block at `/Users/dimitry/baker-vault/_ops/agents/ai-head/ARCHIVE.md` (appended this session — Team 1 + Team 2 composite).
4. Read this handover end to end.
5. `cd "/Users/dimitry/Vallen Dropbox/Dimitry vallen/Baker-Project/15_Baker_Master/01_build" && git pull -q && git log --oneline -5`
6. `gh pr list --repo vallen300-bit/baker-master --state open` — should be empty (0 PRs open at handover).
7. Check weekly audit first-fire status — if time is past Mon 2026-04-27 09:00 UTC:
   ```sql
   SELECT ran_at, slack_cockpit_ok, slack_dm_ok FROM ai_head_audits ORDER BY ran_at DESC LIMIT 3;
   SELECT job_id, fired_at, status FROM scheduler_executions WHERE job_id IN ('ai_head_weekly_audit', 'ai_head_audit_sentinel') ORDER BY fired_at DESC LIMIT 6;
   ```
8. `mcp__baker__baker_raw_query` or via curl JSON-RPC (see `CLAUDE.md` Baker API Access block).

---

## 🧨 Pending at handover

### In flight
**None.** Queue fully drained.

### Queued — ready to draft autonomously per charter §3

1. **`BRIEF_LEDGER_ATOMIC_1`** (CHANDA detector #2 — runtime DB txn wrapper around Director-action ledger writes). Next in the CHANDA detectors sequence. Research Agent's engineering-matrix artefact spec at `_ops/ideas/2026-04-21-chanda-engineering-matrix.md` §6 row #2 + §Recommendation step 3. Target Brisen: b1 or b5 (whichever is proven + idle at your moment).

2. **`BRIEF_KBL_SCHEMA_1`** (M0 row 1 — schema templates + people.yml + entities.yml + VAULT.md rules). Design decisions **LOCKED this session** (Director "default recom is fine" 2026-04-23):
   - Frontmatter = Standard 7 fields: `type`, `slug`, `name`, `updated`, `author`, `tags`, `related`
   - People-slug format = `firstname-lastname` (e.g., `andrey-oskolkov`). Collision rule: append middle-initial or institution.
   - Taxonomy = 3-way: matter / person / entity. Matter = things we DO; person = natural persons; entity = legal/corporate actors.
   - Greenfield: `baker-vault/schema/templates/` EMPTY; `baker-vault/schema/VAULT.md` is 1-line stub; `people.yml` / `entities.yml` do not exist; `slugs.yml` v9 is authoritative for matters.

3. **`BRIEF_MAC_MINI_WRITER_AUDIT_1`** (CHANDA detector #9 — documentation only, no code). After LEDGER_ATOMIC_1. Documents the Render-has-no-vault-push-credentials invariant + monthly audit procedure.

4. **`BRIEF_CHANDA_PLAIN_ENGLISH_REWRITE_1`** (paired with ENFORCEMENT_1 from Research's 2026-04-21 artefact). Rewrites `CHANDA.md` to remove invariants (now in enforcement file) + add §8 pointer.

5. M0 quintet rows 3/4/5: `BRIEF_KBL_INGEST_ENDPOINT`, `BRIEF_PROMPT_CACHE_AUDIT_1`, `BRIEF_CITATIONS_API_SCAN_1`. All not drafted.

### Queued — Director-gated (§4 Cortex Design prerogatives)

- **`BRIEF_CORTEX3T_MVP_HAGENAUER_1`** — M3 window, after M0 closes. Research Agent pre-mortem ratified 2026-04-23 (`_ops/ideas/2026-04-23-cortex3t-premortem.md`). **MUST include TIER_B_BUDGET_1 + S5_RUNTIME_1 as mandatory deliverables (not separate briefs).** 5 post-M3 mitigations named in pre-mortem but DO NOT pre-stage — Director's instruction.
- Cortex-3T reasoning-loop design session — still pending (roadmap open Q#1).
- Matter-routing quality (Step 1 over-routes to `hagenauer-rg7`) — parked; §4 #1/#2/#11. Not a blocker since M3 pilot scope is Hagenauer-only.

### Parked — post-M0 (don't touch without explicit ratification)

- Phase 2 audit-sentinel generalization (decorator across 12+ cron jobs) — gated on 30-day observation of Phase 1.
- `BRIEF_POST_PR44_TEST_REGRESSION_1` — **SUPERSEDED** by PR #46 hotfix. Remove from queue.
- All 5 post-M3 pre-mortem mitigations.

---

## 📁 Key files to read (★ = new or materially updated this session)

| Path | Purpose |
|------|---------|
| `/Users/dimitry/baker-vault/_ops/processes/ai-head-autonomy-charter.md` | Charter (unchanged) |
| `/Users/dimitry/baker-vault/_ops/skills/ai-head/SKILL.md` | ★ §Brief Authoring Standards rules 7-9 added |
| `/Users/dimitry/baker-vault/_ops/agents/ai-head/OPERATING.md` | ★ Rewritten — post-GUARD_1 state, B/A/A design calls locked |
| `/Users/dimitry/baker-vault/_ops/agents/ai-head/ARCHIVE.md` | ★ Session 2 block appended (Team 1 + Team 2 composite) |
| `memory/actions_log.md` | ★ Multiple entries today: PR #45 merge, PR #48 merge + rebase, scratch merge, PR #49 merge + Mac Mini install |
| `_ops/ideas/2026-04-21-chanda-engineering-matrix.md` | Source for CHANDA detectors — next sub-briefs (LEDGER_ATOMIC, MAC_MINI_WRITER_AUDIT) |
| `_ops/ideas/2026-04-23-cortex3t-premortem.md` | ★ Ratified — M3 constraint (TIER_B_BUDGET_1 + S5_RUNTIME_1 inside CORTEX3T_MVP_HAGENAUER_1) |
| `briefs/BRIEF_AUDIT_SENTINEL_1.md` | Shipped template pattern (infra brief + Ship Report format) |
| `briefs/BRIEF_AUTHOR_DIRECTOR_GUARD_1.md` | Shipped template pattern (shell script + pytest + CHANDA amendment) |
| `briefs/BRIEF_CHANDA_ENFORCEMENT_1.md` | Shipped template pattern (pure-insert markdown) |

---

## ⚙️ Workflow (unchanged)

- Dispatch via `briefs/_tasks/CODE_{1,3,5}_PENDING.md` — overwrite, commit, push to baker-master main.
- Trigger: `cd ~/bm-b{N} && git checkout main && git pull -q && cat briefs/_tasks/CODE_{N}_PENDING.md`
- Auto-merge: `gh pr merge N --repo vallen300-bit/baker-master --squash --subject "<title> (#N)"`
- Tier B (rare this session — none active) via 1Password: `TOKEN=$(op item get "API Render" --vault "Baker API Keys" --fields credential --reveal 2>/dev/null)`
- SSH to Mac Mini: `ssh macmini` (alias confirmed working this session).
- **Pre-merge rebase on PR branch only** when GitHub reports `CONFLICTING`: local rebase onto main, resolve, syntax-check, `git push --force-with-lease` to PR branch. Verified clean on PR #48 this session. Never force-push to main.

---

## 🎬 Status ping to Director after refresh

```
[TEAM-1] AI Head #1 refreshed — morning handover read. Charter active.

Queue clean: 0 open PRs. M0 quintet 3 of ~9 sub-briefs shipped
(ENFORCEMENT_1 #45, AUDIT_SENTINEL_1 #48 infra-parallel, GUARD_1 #49).
CHANDA #4 hook LIVE on Mac Mini baker-vault.

Next autonomous: LEDGER_ATOMIC_1 draft + KBL_SCHEMA_1 draft (design
calls B/A/A locked). Standing by otherwise.

Pre-mortem M3 constraint noted (CORTEX3T_MVP_HAGENAUER_1 at M3 window
must include TIER_B_BUDGET_1 + S5_RUNTIME_1 as mandatory deliverables).
```

---

## ⚠️ Things NOT to do (unchanged + session additions)

### Charter-rooted
- Do not ask Director to authorize technical actions (charter §3).
- Do not re-explain ratified rules back to Director in chat (charter §6).
- Do not touch `CHANDA.md` without paired rewrite brief (`CHANDA_PLAIN_ENGLISH_REWRITE_1`).
- Do not touch `hot.md` (Director-authored — and now hook-guarded).
- Do not dispatch matter-routing quality fix without Director (§4 #1/#2/#11).

### Session-captured (add to your mental model)
- **Do not invent b-code lane models.** Route to proven + idle. Don't assume "b5 for detectors, b1 for schema."
- **Do not skip `/write-brief` Step 4 REVIEW rules 1-9.** Rules 7-9 are post-MOVIE-AM scar tissue; don't repeat those bugs.
- **Do not pester Director with tactical questions.** Bank-client frame (charter §2) re-invoked this session. Decide autonomously; flag in brief/ship report if Director needs awareness.
- **Do not ship "by inspection."** Every PR needs literal `pytest` output.
- **Do not force-push to main.** Only to PR branches during rebase cleanup; use `--force-with-lease`.
- **Do not pre-stage post-M3 pre-mortem mitigations.** Director explicit: "premature."

---

## 🗒️ Lessons surfaced this session (captured in ARCHIVE Session 2 + SKILL.md)

1. **Parallel-team shared-file merge conflicts are predictable** on `embedded_scheduler.py` (both teams add jobs in `_register_jobs`). Rebase-before-merge on PR branch is the canonical path. ~5 min overhead. Acceptable.
2. **Bank-client framing dominates tactical asks.** Before asking: (a) would a CEO/bank-client expect this? (b) does it change what vs how? (c) is it reversible? Decide silently if "no / how / yes."
3. **Scratch-merge discipline:** Team 2 scratch files are first-class paper trail. Merge into canonical triplet at checkpoint; retire scratch file after merge.
4. **Post-merge hook install requires Director-local action** for baker-master (AI Head can't reach laptop). Mac Mini baker-vault install is AI Head autonomous via SSH.
5. **SSH+shell-escape mangling** of `\"` characters can cause false-reject in ad-hoc smoke tests. Use COMMIT_EDITMSG file construction for direct marker testing.

---

*Prepared 2026-04-23 MORNING. 3 PRs merged (#45, #48, #49), 1 scratch retired, 1 Mac Mini hook installed, SKILL.md rules 7-9 captured. Queue fully drained. Next: LEDGER_ATOMIC_1 + KBL_SCHEMA_1 drafting autonomously.*
