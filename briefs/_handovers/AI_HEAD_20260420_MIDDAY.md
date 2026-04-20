# Handover — AI Head (Claude App) — 2026-04-20 MIDDAY

**Date:** 2026-04-20 (midday, post-RSS-bulk-insert + post-bridge-brief-ratification)
**From:** AI Head (outgoing — Director-requested refresh before intensive afternoon)
**To:** Fresh AI Head instance
**Director:** Dimitry Vallen
**Supersedes:** `briefs/_handovers/AI_HEAD_20260420.md` (morning session)

---

## 🚨 READ BEFORE ANYTHING ELSE

**Durable rules added THIS SESSION (cumulative on top of morning-session rules):**

1. **Plain English only to Director** — `feedback_ai_head_plain_english_only.md`. No SHA / line numbers / test counts / SQL / env var names in Director-facing chat. Surface only architectural issues, Cortex T3 purpose threats, Tier B auth asks, true ambiguity. Technical detail goes to mailbox + action log, not chat. Ratified 2026-04-20 after Director surfaced: *"I do not need technical details, only write comments in plain english and only if my involvement is genuinly needed."*

2. **Bridge filter teaching starts Day 1** — `feedback_bridge_day1_teaching.md`. When ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 ships, you MUST start surfacing Silver files for Director review as soon as 5-10 land. Don't wait for passive burn-in. 2-3 day convergence window requires active teaching, not observation. Director ratified: *"start the teaching lessons on filtering from day one as soon as the bridge is installed."*

**Morning-session rules still in force** (read the morning handover if you haven't):

- Bank model — Tier A/B/C execution authority. `feedback_ai_head_communication.md`.
- Fenced-block dispatches for B1/B2/B3 (always prepare 3 when dispatching parallel).
- Narrative only for Director-intervention moments.
- Always include explicit recommendation.
- Delegate execution to Code Brisens when fresh.
- Code agents in `~/bm-b{N}` (baker-master) and `~/bv-b{N}` (baker-vault) — NOT `/tmp/`.
- Quit Terminal tab after each PR cycle (RAM hygiene).
- Never touch Dropbox paths from agent shells.
- CHANDA commits require explicit Director authorization in commit message.

**New terminology disambiguation (Director ratified 2026-04-20 midday):**

- **Architecture tiers = T1 / T2 / T3** — T1 Render (ingestion + Opus), T2 Mac Mini (poller + Step 7 + local LLM), T3 your MacBook (Code Brisens + Cowork).
- **Priority tiers = priority Tier 1 / Tier 2 / Tier 3** — Baker's classifier output (Critical / High / Normal).
- ALWAYS write "T1/T2/T3" for architecture and "priority Tier 1/2/3" for urgency. They're different concepts; conflation confuses.

---

## Who you are

You are **AI Head** — orchestration + brief-authoring + architecture-decision agent for Baker / KBL / Cortex T3. You coordinate **three Code Brisen agents in parallel: B1, B2, B3.** You write implementation briefs, review architecture decisions, relay between Director and Code via mailbox pattern. You also orchestrate AI Dennis (IT shadow agent via Cowork skill).

**You do NOT write production code.** Code Brisens do. You DO execute one-shot mechanical Tier B actions (DB UPDATEs, SQL paper-trail, small memory-file edits) after Director authorization per bank model.

You run in Claude App (desktop). B1/B2/B3 run in Claude Code CLI (three separate Terminal tabs on Director's Mac). AI Dennis runs in Claude App Cowork (cloud-sandboxed — can't see local filesystem; reads via MCP).

---

## 🎯 Major work this session

### Session arc (morning → midday, ~8h)

1. **Morning (post-refresh):** Shipped 3 polish PRs (#21 alias rename, #22 dead-code, #23 conftest Neon fixture) + FEEDLY_WHOOP_KILL (#24).
2. **Midday:** Diagnosed Cortex T3 missing-producer seam. Director provided research agent's RSS source list — AI Head bulk-inserted 25 feeds across 8 clusters with language metadata. Authored 2 major briefs: SOT_OBSIDIAN_UNIFICATION_1 (ratified, Phase A+B shipped) and ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 (ratified, awaiting B1 implementation).
3. **Afternoon (coming):** B1 implements the bridge. B2 reviews helper v2 + SOT Phase B. B3 stands by for Phase C once Phase B merges. Day 1 teaching protocol fires when bridge goes live.

### Merges this session

| # | Repo | Title | Merge SHA |
|---|---|---|---|
| 21 | baker-master | DASHBOARD_COST_ALIAS_RENAME | `3efb275` |
| 22 | baker-master | STORE_BACK_DEAD_CODE_AND_DB_ENV_FALLBACK | `d6eb23b` |
| 23 | baker-master | CONFTEST_NEON_EPHEMERAL_FIXTURE | `4b61453` |
| 24 | baker-master | FEEDLY_WHOOP_KILL | `78e8ea9` |
| 25 | baker-master | baker-review template + lessons-grep-helper + SI amendment (B2's self-improvement) | — (squash merged) |
| 3 | baker-vault | SOT_OBSIDIAN_UNIFICATION_1 Phase A (scaffold _ops/) | — |

### Open PRs (in flight at handover)

| # | Repo | Title | Status |
|---|---|---|---|
| 4 | baker-vault | SOT_OBSIDIAN_UNIFICATION_1 Phase B (AI Dennis migration + sync wiring) | B2 review queued |
| 26 | baker-master | LESSONS_GREP_HELPER_V2 (B3 fix of B2's N1+N2 nits) | B2 review queued — 2 flagged deviations for B2 decision |

### Decisions stored in Baker this session

- `11922` — SOT_OBSIDIAN_UNIFICATION_1 brief ratified
- `11937` — ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 brief ratified

### Tier B action log entries this session

- **2026-04-20 ~11:15 UTC** — FEEDLY_WHOOP_KILL post-merge cleanup (3 actions: Render env scan clean, whoop watermark row delete, CLAUDE.md Dropbox edit)
- **2026-04-20 ~13:10 UTC** — RSS bulk insert (migration file + Luxury Daily retire + 25-feed UPSERT + language backfill)

All Director-authorized. All logged in `actions_log.md`.

---

## Agent roster + current workload (state at handover)

| Agent | Platform | State | Next work |
|---|---|---|---|
| **B1** | Terminal CLI | **Idle, tab closed.** Last ship: SOT Phase B at `0174b3e` (PR #4 baker-vault, awaiting B2). | ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1 implementation (6-8h) — mailbox queued at `CODE_1_PENDING.md` commit `5aad04e`. |
| **B2** | Terminal CLI | **Idle, tab closed.** Last work: approved PR #24 FEEDLY_WHOOP_KILL + shipped own PR #25 (template + helper + SI) + approved baker-vault PR #3. | Two reviews: PR #26 (helper v2) + PR #4 (Phase B). Helper v2 has 2 deviations for B2 decision. Mailbox at `CODE_2_PENDING.md` commit `5aad04e`. |
| **B3** | Terminal CLI | **Idle, tab closed.** Last ship: LESSONS_GREP_HELPER_V2 at `ad62130` (PR #26, awaiting B2). | SOT Phase C — migrate `pm/briefs/` → `_ops/briefs/`. Gated on Phase B merge. Standing down until signal. |
| **AI Dennis** | Cowork | **Invoked once this session** (first real session ever). Produced the "lost-file syndrome" diagnostic that became SOT_OBSIDIAN_UNIFICATION_1. Now idle. | Wait for SOT Phase B merge + Phase D MCP bridge (when that sub-brief ships) to be equipped equally with Code. |

---

## Active Cortex T3 work

### Ratified briefs awaiting implementation

- **ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1** — HIGHEST PRIORITY. Unblocks Gate 1 (≥5-10 clean signals through Steps 1-7). B1 assigned.
  - Brief: `briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md` at commit `d449b6c` in baker-master.
  - 4-axis filter (tier + matter + VIP + promote-type) + stop-list for Director-ratified noise denominator.
  - Day 1 teaching protocol baked in — bridge is NOT "done" on merge; it's done after Director reviews 20-30 Silver files and filter is tuned at least once from real dismissals.

- **SOT_OBSIDIAN_UNIFICATION_1** — 5 phases. Phase A merged. Phase B in flight. Phases C-E still ahead.
  - Brief: `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` at commit `4596383` in baker-master.
  - Phase C gated on Phase B merge (B3 queued).
  - Phase D needs a SEPARATE sub-brief from AI Head first: `SOT_OBSIDIAN_1_PHASE_D_TRANSPORT.md` — resolves MCP-on-Render vs. Mac-Mini-side-car question for Cowork equipping. ~300-500 LOC. Author before Phase D dispatches.
  - Phase E = CHANDA Inv 9 refinement + pipeline frontmatter filter. CHANDA edit is Tier B — requires Director's explicit "yes" in chat, commit with quote.

### Follow-up briefs flagged (not yet written)

- **`BAKER_PRIORITY_CLASSIFIER_TUNE_1`** — upstream fix for Baker's classifier producing the noise/mis-tier patterns Director surfaced. Scope revealed: `deadlines` table already has `assigned_to` + `assigned_by`; classifier just doesn't route on them. Originally estimated weekend; now 4-6h.
  - **Do NOT author until bridge has 2-3 days of real Director dismissal data.** Director wants convergence evidence first.
  - Covers three systematic errors surfaced in chat: (a) under-tiering real-matter content as T3, (b) over-tiering promo as T1/T2, (c) under-tiering matter-important informational as T3.

- **`AUSTRIAN_LEGAL_NEWSLETTER_1`** — parsing Austrian law-firm newsletters (E+H, Schönherr, CMS) into `rss_articles` since Cluster 1 (Austrian construction law) has no suitable RSS feeds. **Do NOT draft without Director go.** Director explicitly parked this as follow-up.

### Watch items from RSS bulk insert (2026-04-20 midday)

- **Skift feed** — research agent flagged Cloudflare 403 during validation. Re-enabled in Cluster 3 as hospitality source. If first 24h polls show 6 consecutive failures and it auto-disables, AI Head to hunt replacement. Not blocking.

---

## Key files

| File | What | Changed this session |
|---|---|---|
| `CHANDA.md` (baker-vault) | Gold architectural intent | Untouched (Phase E to refine Inv 9, Tier B) |
| `briefs/BRIEF_ALERTS_TO_SIGNAL_QUEUE_BRIDGE_1.md` | Bridge implementation spec | **NEW, ratified** |
| `briefs/BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` | SoT canonicalization spec | **NEW, ratified, Phase A merged, Phase B in flight** |
| `briefs/_templates/B2_verdict_template.md` + `lessons-grep-helper.sh` + SI amendment | B2 self-improvement | **NEW, merged** (PR #25) |
| `briefs/_tasks/CODE_{1,2,3}_PENDING.md` | Mailboxes | All 3 updated at commit `5aad04e` |
| `baker-vault/_ops/*` | New subtree (Phase A) | **NEW — skills/, briefs/, agents/, processes/ folders + INDEX files + writer-contract** |
| `baker-vault/_install/sync_skills.sh` | Skill sync script | Phase A skeleton merged; Phase B wires real logic (in PR #4) |
| `migrations/20260420_rss_feeds_language_column.sql` | Language column | **NEW, applied by MIGRATION_RUNNER_1 on deploy** |

### Memory files added/modified this session (`/Users/dimitry/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/`)

- `feedback_ai_head_plain_english_only.md` — **NEW rule**
- `feedback_bridge_day1_teaching.md` — **NEW rule**
- `actions_log.md` — two new entries (FEEDLY_WHOOP_KILL cleanup + RSS bulk insert)
- `MEMORY.md` index — added pointer to plain-english rule

---

## Paper trails for this session

Three layers per Tier B action (per session ratification):

1. **git commit** — codified in baker-master commits
2. **`actions_log.md` entry** — append-only paper trail
3. **`baker_store_decision`** — Baker decision IDs `11922` + `11937`

---

## Architecture context carried forward

### Director's RSS strategy (2026-04-20)

- Feedly retired ("too expensive"). Direct RSS polling only.
- 25 active feeds across 8 clusters (C2 Austrian RE + C3 ultra-lux hospitality + C4 UHNW + C5 AI + C6 longevity + C7 Swiss + C8 macro + C9 German institutional RE). Cluster 1 (Austrian legal) intentionally blank.
- Language column present: 18 EN + 6 DE + 1 FR.
- Per-feed poll frequency DEFERRED — all polling at 60-min interval today. Per-feed scheduling is post-burn-in brief.
- Luxury Daily RETIRED (duplicated Spears on UHNW beat).

### Director's filter taxonomy (2026-04-20)

4-axis filter for alerts → signal_queue:

1. Priority Tier 1 or 2 → bridge
2. `matter_slug IS NOT NULL` → bridge
3. VIP sender (via `vip_contacts` join) → bridge
4. Message type in promote-list (commitment/deadline/appointment/meeting/tax-opinion/financial-report/legal-document/dispute-update/contract-change/investor-communication/vip-message/travel-info) → bridge

Stop-list (Director ratified) overrides permissive axes — catches third-party events/offers/visits mis-tagged as commitments (Forbes ticket, Sotheby's preview, Hotel Express promo, Stan Manoukian NYC, wine auction, Medal Engraving, "complimentary", "% off", "will be available").

### Baker v5 architecture doc

Added to `brisen-docs.onrender.com/architecture/baker-v5.html` this session (2026-04-20). Part of the ARCHITECTURE folder carved out for future v6+ when Cortex T3 is documented. Also lives at `docs-site/architecture/baker-v5.html` in baker-master repo.

### AI Dennis + Cowork equipping

- AI Dennis skill IS correctly installed at `~/.claude/skills/it-manager/SKILL.md` — verified this session.
- **Cowork (AI Dennis's runtime) has NO local skill directory** — its skill registry is cloud-delivered. Local filesystem copy does NOT equip Cowork.
- Fix path: SOT_OBSIDIAN_UNIFICATION_1 Phase D — new MCP tool `baker_vault_read` gives Cowork read-only access to `_ops/` content. Transport sub-brief needed first (Render MCP vs Mac Mini side-car question).

---

## Workflow patterns unchanged from morning handover

### Mailbox (unchanged)

- Tasks: `briefs/_tasks/CODE_{1,2,3}_PENDING.md` + `briefs/_tasks/AI_DENNIS_*.md` — overwrite, commit, push.
- Reports: `briefs/_reports/B{N}_<topic>_<YYYYMMDD>.md` (baker-master) or `_reports/` (baker-vault).
- Chat dispatch: THIN POINTER fenced block. File is sole source. Always 3 blocks when dispatching parallel.

### Git flow (unchanged)

- Fresh `/tmp/bm-draft` on refresh (stateless).
- Pull → work → commit with `GIT_AUTHOR_NAME="AI Head"` + `EMAIL="ai-head@brisengroup.com"` → push.
- On push conflict: `git pull --rebase origin main` + retry.
- Two repos: `baker-master` (code + briefs + handovers) + `baker-vault` (CHANDA + wiki + _ops/).

### Auto-merge protocol (unchanged)

```bash
gh pr merge <N> --repo vallen300-bit/<repo> --squash --subject "<title> (#<N>)"
```

Gate: designated reviewer APPROVE + CLEAN mergeable + no Director blockers. AI Head-as-reviewer is sanctioned when the mailbox's fallback clause applies (B1 offline on B2's PR in this session — I reviewed + merged PR #25 directly).

### Verification discipline (unchanged)

- Before merge: `gh pr view <N> --json state,mergeable` — if `UNKNOWN`, poll with `until` loop.
- Post-deploy verification: poll with `until`, don't single-shot (FastAPI `/health` goes green before async startup hook completes — lesson #41).

---

## Director communication style + updated rules

- **Plain English only in chat** — NEW SESSION RULE, non-negotiable. Technical detail to mailbox + action log.
- Bottom-line first, supporting detail second.
- Terse. "yes", "go", "ok", "follow recommendations" are common ratifications.
- Co-designs architecture in conversation (this session: 4-axis filter taxonomy, promote-type allowlist, stop-list patterns). When Director refines a recommendation, fold it in and update immediately.
- Reads recommendations carefully; wants them as dedicated callout lines, not buried.
- Challenges; steel-man against yourself when pushed.
- Will sometimes correct your framing mid-conversation (this session: "items 8/9/10 are extremely important, not borderline" + "MO Vienna press mentions should be priority Tier 2"). Absorb the correction and revise the model.

---

## If Director asks "what's next?"

1. **Immediate** — check three PR states: PR #4 (Phase B), PR #26 (helper v2), B1's bridge PR (if shipped since handover). Auto-merge any that are approved.
2. **Post-Phase-B-merge** — dispatch B3 Phase C.
3. **Post-bridge-merge** — **Day 1 teaching fires**. Surface Silver files to Director as they land. Batch dismissals every ~12h. Tune stop-list from real patterns.
4. **Post-bridge-stable (~48-72h)** — decide: `BAKER_PRIORITY_CLASSIFIER_TUNE_1` now, or accept residual noise + let feedback ledger work?
5. **Parallel** — SOT Phase D sub-brief (`SOT_OBSIDIAN_1_PHASE_D_TRANSPORT.md`). AI Head authors; do this while B1 is on the bridge.

---

## Trust levels (updated)

- **B1:** VERY high. Shipped 4 substantial PRs this session incl. SOT Phase B (12 files, proper safety on symlink logic). Pragmatic, good at flagging architectural ambiguities pre-impl. Memory-hygiene practiced.
- **B2:** VERY high. Reviewed ~8 PRs this session. Caught stop-list regression on PR #26 (helper v2) and flagged 2 substantive deviations for AI Head/Director decision. Self-improvement track: authored baker-review template + lessons-grep-helper (PR #25 — his own PR, AI Head reviewed).
- **B3:** High. Shipped helper v2 with 4/4 synthetic tests + honest deviation-flagging. Design discipline solid.
- **AI Dennis:** Validated first live session. Produced the SOT diagnostic that became a 5-phase architectural brief. Awaiting MCP bridge (Phase D) for full Cowork equipping.

---

## Session-specific lessons (proactively drafted for `tasks/lessons.md` when bridge + Day 1 teaching cycle closes)

Placeholders — real lesson numbering TBD by Phase E / bridge merge timing:

- **#43** — Skills don't live where you think they do. Claude App: `~/.claude/skills/`. Cowork: cloud-delivered registry, no local folder. Filesystem copy does NOT equip Cowork.
- **#44** — Symlink safely or not at all. Sync script skips non-symlink non-empty dirs rather than overwrite.
- **#45** — Frontmatter filters must fail open. Parse-error → process normally, not skip.
- **#46** — Bridges are their own failure class. Test watermark + mapping shape + idempotency independently.
- **#47** — Stop-lists belong at the filter edge, not the classifier. Pair every stop-list with a root-cause brief.
- **#48** — Day 1 teaching is part of the feature. A filter that ships but never gets tuned from real dismissals isn't done.

---

## You are refreshed. Start by:

1. Read this handover end-to-end (~10 min).
2. `cd /tmp && rm -rf /tmp/bm-draft && git clone https://github.com/vallen300-bit/baker-master.git /tmp/bm-draft && cd /tmp/bm-draft` (fresh clone).
3. Read `CHANDA.md` at repo root — note Inv 9 text (will be refined in Phase E).
4. `git log --oneline -15` — scan for commits since this handover.
5. `ls briefs/_reports/ | sort | tail -10` — any new reports.
6. `gh pr list --repo vallen300-bit/baker-master --state open` — expect at least `lessons-grep-helper-v2` + possibly bridge branch.
7. `gh pr list --repo vallen300-bit/baker-vault --state open` — expect `sot-obsidian-1-phase-b` (PR #4) unless B2 merged meanwhile.
8. `curl -sS https://baker-master.onrender.com/health` — expect 44+ scheduled_jobs (43 + kbl_bridge_tick once bridge lands).
9. Baker MCP: call `mcp__baker__baker_watermarks` to confirm MCP still live.
10. `mcp__baker__baker_raw_query` with: `SELECT status, COUNT(*) FROM signal_queue GROUP BY status` — expect 0 if bridge hasn't merged, >0 if bridge is live.
11. Check `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/` — read the two new feedback files (plain_english_only + bridge_day1_teaching) FIRST.
12. Review the three CODE_{N}_PENDING.md mailboxes at commit `5aad04e` to confirm B-code dispatch state.

**First status ping to Director (template):**

```
AI Head refreshed. State as of git <SHA>:
- Merges since handover: <list or "none">
- B1: <status — on bridge implementation?>
- B2: <status — reviewing PR #26 + PR #4?>
- B3: <status — standing down until Phase B merges?>
- Open PRs: <list>
- Render: healthy, <N> scheduled_jobs
- signal_queue: <count — 0 if bridge not yet merged, >0 if live>
- Bridge brief: ratified, awaiting B1 implementation
- SOT: Phase A merged, Phase B in flight, Phases C-E queued
- Day 1 teaching: fires when bridge merges
Standing by.
```

**Then:**

- If bridge is merged: surface first Silver files for Director review per Day 1 teaching protocol.
- If bridge not merged: continue coordinating B-codes; author SOT Phase D transport sub-brief in parallel if idle.

---

*Prepared 2026-04-20 midday by outgoing AI Head. Bridge brief ratified, SOT mid-migration, intensive afternoon ahead. Day 1 teaching is the load-bearing commitment — don't drop it.*
