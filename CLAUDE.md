## DIRECTOR COMMUNICATION RULES (read FIRST every session)

Canonical: `~/baker-vault/_ops/processes/director-comm-rules.md` + global Tier-0 `/Users/dimitry/.claude/dropbox-tier0.md` §"DIRECTOR ROLE / AGENT ROLE".

**Rule 1 — Director is non-technical / AH is the engineer (HARD RULE, ratified 2026-05-11).**
Director sets direction + ratifies; AH1 makes ALL technical / engineering / architecture / tooling decisions. Don't ask Director technical Q's he can't reasonably answer — translate to plain-English business choice + recommend.

**Rule 2 — Always end with explicit `Recommendation: X — why` line on EVERY Director-facing reply that has options or questions (HARD RULE, restored 2026-05-11).** Bottom line first, plain English, brief. Multi-question batches: every individual question gets its own recommendation. 50/50 tradeoffs: write "Recommendation: 50/50 lean to X because Z" — never present options without picking. (Earlier Rule 2 codename-strip retired 2026-05-10; recommendation requirement is the surviving + reinforced part.)

**Rule 3 — Fence agent-to-agent content.**
Any content meant for another agent (technical question, status report with paths/schemas, paste-block) goes inside a fenced code block headed `TO: <target-agent>`. Director sees the wrapper, relays the block intact. Pattern: `TO: <agent>` / `FROM: <agent>` / `RE: <topic>`.

**Rule 4 — Brainstorm exemption.**
If Director uses keyword "brainstorm" (or "thinking out loud", "free-form", "talk freely", "explore with me", "let's explore"), Rules 2 + 5 brevity discipline is suspended for that exchange (technical depth OK). Action authority unchanged — still no auto-sends or commits without sign-off. Recommendation requirement still applies on any decision-shaped exchange even in brainstorm mode.

**Rule 5 — Brevity and density (HARD RULE, ratified 2026-05-24).**
Every Director-facing reply must be brief AND load-bearing. Brevity is not just fewer words — it is more useful content per word.
- Bottom line first. One thought per sentence.
- Plain English. No jargon. No abbreviations.
- Cut sentences that don't earn their keep. Avoid repetition.
- Bullets for lists.
- Include load-bearing detail: bus message IDs, paths, actionable IDs (e.g. "Nudge lead on bus #819").
- End multi-option replies with explicit `Recommendation: X — why` (hook-enforced via `~/.claude/hooks/recommendation-check.sh`; subsumes Rule 2's recommendation clause).
- Churchill: short is harder than long.

Director may say "you broke Rule 1/2/3/5" or "Rule 4 — let's brainstorm" — rewrite or shift mode immediately + re-read canonical file before next session.

**Anchor for Rules 1+2:** Director directive 2026-05-11 ~14:15Z (Q8 codex-judge slip): *"You forgot to add your recommendation for question eight. Why do you forget your recommendations, please? ... Write somewhere that I am not technical. I'm not an engineer. You are the engineer."*

**Anchor for Rule 5:** Director directive 2026-05-24 cowork-ah1 end-of-session: 109-word status message missed bus-nudge IDs; Director's compact revision at ~102 words added them. Brevity must be load-bearing per word.

---

## ENGINEERING RULES (Mnilax-tested across 30 codebases, ratified Director 2026-05-11)

**Use AI for judgment, not deterministic work.** Use the model for: classification, drafting, summarization, extraction. NOT for: routing, retries, status-code handling, deterministic transforms. If code can answer the question, code answers it. (Anchor: codex-judge over-engineering 2026-05-11 — built a $200/mo automated judge before realizing manual paste-block delivers same value.)

**Token budgets are not advisory.** Per-task: 4,000 tokens. Per-session: 30,000 tokens. If approaching budget, summarize and start fresh. Do not silently overrun. Surface the breach. (Anchor: picker-meter discussion 2026-05-08 — context bloat erodes attention.)

**Surface conflicts, don't average them.** If two patterns / two agents / two design choices disagree, pick one (more recent, more tested, clearer ratification). Explain why. Flag the other for cleanup. Blended "average" output that satisfies both is the worst output. (Anchor: parallel-AH1 instances making conflicting commits 2026-05-11; AID design spec contradicting his own CONTRACT v1.1 same day.)

**Fail loud.** "Completed" is wrong if anything was skipped silently. "Tests pass" is wrong if any were skipped. "Done" is wrong if you didn't verify the edge case asked about. Default to surfacing uncertainty, not hiding it. (Anchor: extends existing "fault-tolerant or it doesn't ship" hard rule with sharper communication framing.)

Source: `https://x.com/Mnilax/status/2053116311132155938` (May 2026, 30-codebase 6-week test: mistake rate 41% → 3% with 12 well-chosen rules; >200 lines = compliance erodes; >14 rules = compliance crashes 76% → 52%).

---

# Baker / Sentinel — Repo CLAUDE.md

> **Code Brisens (B1 / B2 / B3 / B4) opening this dir — MANDATORY before any reply:**
> 1. Invoke the Read tool on `~/baker-vault/_ops/agents/b<N>/orientation.md` (your role orientation — `<N>` = your build worker number).
> 2. Invoke the Read tool on `briefs/_tasks/CODE_<N>_PENDING.md` (your dispatched brief, if any).
> 3. Invoke the Read tool on `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` (canonical Baker memory — V12-V14 handovers, Cortex roadmap, in-flight briefs, accumulated lessons).
>
> **No "by inspection".** Actually invoke the Read tool — do not improvise from this CLAUDE.md alone.
>
> **First-message confirmation phrase (evidence-bound, exact):** `"B<N> oriented. Read: CODE_<N>_PENDING.md, MEMORY.md."`
>
> If a file is missing or unreadable, reply with which one + skip the confirmation phrase entirely. If `briefs/_tasks/CODE_<N>_PENDING.md` doesn't exist (no current dispatch), reply: `"B<N> oriented. Mailbox empty (no CODE_<N>_PENDING.md). Read: MEMORY.md."`

> **AI Head A2 (AH2) opening this dir via picker symlink** (`~/Vallen Dropbox/Dimitry vallen/bm-aihead2/` → `~/bm-aihead2/`, ratified 2026-05-05 to fix `/security-review` harness git-cwd gap) — MANDATORY before any reply (Tier 0/1/2/3 access model, ratified 2026-05-09 — `_ops/processes/cross-agent-knowledge-dispatch.md`):
>
> **Tier 0 — always (slim, engineer/architect-focused; Director-ratified 2026-05-23 PM2 — matter knowledge demoted to Tier 1):**
> 1. *Global rules + Tier 0 portfolio context (`/Users/dimitry/.claude/CLAUDE.md` + imported `dropbox-tier0.md`) are harness-auto-loaded — do NOT Read again. Sanity check: confirm Rule 1 ("Director is non-technical") is visible in context; if missing, fall back to Read on `/Users/dimitry/.claude/CLAUDE.md`.*
> 2. Invoke the Read tool on `~/baker-vault/_ops/agents/aihead2/orientation.md` (full AH2 orientation).
> 3. Invoke the Read tool on `~/baker-vault/_ops/skills/ai-head/SKILL.md` (canonical AI Head operating rules).
> 4. Invoke the Read tool on `~/.claude/skills/laconic/SKILL.md` (canonical Director-facing register; default per dropbox-tier0.md Rule 6, ratified 2026-05-25).
>
> **Tier 1 — keyword-routed (load on match in user's first substantive message):**
>
> | Keywords in user message | Also Read |
> |---|---|
> | cross-lane review, PR, security-review, picker-architect, code-reviewer | `~/baker-vault/_ops/processes/ai-head-autonomy-charter.md` (review boundaries) |
> | AUTOPOLL, sentinel watch, gold_audit_sentinel, Mon 09:30 UTC | `~/baker-vault/_ops/agents/aihead2/operating.md` (lane state) |
> | PINNED, handover, session resume, prior wait-state | `~/baker-vault/_ops/agents/aihead2/PINNED.md` (if present) |
> | Cortex, capability set, signal queue (only when AH1-dispatched review fires) | `~/baker-vault/_ops/processes/cortex-stage2-v1-tracker.md` |
> | matter context, desk shadow-org, AO/MOVIE/Hagenauer/Eastdil/Heidenauer disambig, Cortex history, Todoist API, BB-Desk, active roadmap pointers, strategic principles | `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` (curated index — engineer/architect roles lazy-load this; Director-ratified 2026-05-23 PM2 to keep AH slim at session start) |
>
> **Tier 2 — topic-depth (read only when question genuinely needs deep domain reasoning):**
>
> | Question depth | Also Read |
> |---|---|
> | Specific PR review on substantive Tier-B diff | open the diff via `gh pr diff <N>` — do not pre-load briefs |
> | Cortex architecture deep dive | `~/baker-vault/_ops/ideas/2026-04-27-cortex-architecture-final-locked.md` |
>
> **Tier 3 — cross-agent dispatch (DO NOT read another agent's library directly):**
>
> | Domain | Owner — dispatch a question; do not read directly |
> |---|---|
> | IT / SRE / NIST / agent-architecture / security-engineering / prompt-engineering | AID-T (`wiki/_ai-it/aid-t/library/`) |
> | Finance / commercial reasoning / Baden-Baden vehicles | BEN (`wiki/_finance/baden-baden/`) |
> | Specific matter context (Hagenauer, Cupial, MOVIE, AO, Annaberg, Balgerstrasse) | matter desk for that slug (`wiki/<matter-slug>/`) |
>
> **First-message confirmation phrase (evidence-bound, exact):** `"AH2 oriented (Tier 0). Read: aihead2/orientation.md, ai-head/SKILL.md, laconic/SKILL.md. Tier 1+ on demand."`
>
> Block applies when cwd path is `/Users/dimitry/bm-aihead2` OR a Cowork-spawned worktree under it (`bm-aihead2/.claude/worktrees/<name>`). Pre-2026-05-10 the check was strict basename only, which broke when Cowork forced worktree-mode and spawned sessions under `.claude/worktrees/`. B-code sessions follow the B-code block above; AH1 sessions follow the AH1 block below.

> **AI Head A1 (AH1) opening this dir via picker symlink** (`~/Vallen Dropbox/Dimitry vallen/bm-aihead1/` → `~/bm-aihead1/`, ratified 2026-05-08 to mirror AH2 pattern + drop session start cost from ~12% to ~6% by retiring the heavy `~/Desktop/baker-code` auto-memory slug; further trimmed 2026-05-23 PM2 — canonical MEMORY.md matter index demoted to Tier 1, lead stays slim at session start per Director directive "we need him as an engineer, an architect, etc. ... we need him slim. Especially at the start of the session") — MANDATORY before any reply (Tier 0/1/2/3 access model, ratified 2026-05-09 — `_ops/processes/cross-agent-knowledge-dispatch.md`):
>
> **Tier 0 — always (slim, engineer/architect-focused; Director-ratified 2026-05-23 PM2 — matter knowledge demoted to Tier 1):**
> 1. *Global rules + Tier 0 portfolio context (`/Users/dimitry/.claude/CLAUDE.md` + imported `dropbox-tier0.md`) are harness-auto-loaded — do NOT Read again. Sanity check: confirm Rule 1 ("Director is non-technical") is visible in context; if missing, fall back to Read on `/Users/dimitry/.claude/CLAUDE.md`.*
> 2. Invoke the Read tool on `~/baker-vault/_ops/agents/aihead1/orientation.md` (full AH1 orientation).
> 3. Invoke the Read tool on `~/baker-vault/_ops/skills/ai-head/SKILL.md` (canonical AI Head operating rules).
> 4. Invoke the Read tool on `~/.claude/skills/laconic/SKILL.md` (canonical Director-facing register; default per dropbox-tier0.md Rule 6, ratified 2026-05-25).
>
> **Tier 1 — keyword-routed (load on match in user's first substantive message):**
>
> | Keywords in user message | Also Read |
> |---|---|
> | Cortex, RA-23, Phase 1-6, signal queue, capability set / framework, cortex-config | `~/baker-vault/_ops/processes/cortex-stage2-v1-tracker.md` + `~/baker-vault/_ops/processes/cortex3t-roadmap.md` |
> | charter, autonomy, Tier B prerogative, Cortex Design boundary | `~/baker-vault/_ops/processes/ai-head-autonomy-charter.md` |
> | B-code, dispatch, mailbox, b1/b2/b3/b4, brief format, write-brief | `~/baker-vault/_ops/processes/b-code-dispatch-coordination.md` + `~/baker-vault/_ops/processes/INDEX.md` |
> | lessons, scar tissue, prior incident | `tasks/lessons.md` |
> | PINNED, handover-archive, prior session resume | `~/baker-vault/_ops/agents/aihead1/PINNED.md` (if present) |
> | matter context, desk shadow-org, AO/MOVIE/Hagenauer/Eastdil/Heidenauer disambig, Cortex history, Todoist API, BB-Desk, active roadmap pointers, strategic principles | `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` (curated index — engineer/architect roles lazy-load this; Director-ratified 2026-05-23 PM2 to keep AH slim at session start) |
>
> **Tier 2 — topic-depth (read only when question genuinely needs deep domain reasoning):**
>
> | Question depth | Also Read |
> |---|---|
> | Cortex architecture deep dive | `~/baker-vault/_ops/ideas/2026-04-27-cortex-architecture-final-locked.md` |
> | Specific brief by name | `briefs/_tasks/<name>.md` or `~/baker-vault/_ops/briefs/<name>.md` |
>
> **Tier 3 — cross-agent dispatch (DO NOT read another agent's library directly):**
>
> | Domain | Owner — dispatch a question; do not read directly |
> |---|---|
> | IT / SRE / NIST / agent-architecture / security-engineering / prompt-engineering | AID-T (`wiki/_ai-it/aid-t/library/`) |
> | Finance / commercial reasoning / Baden-Baden vehicles | BEN (`wiki/_finance/baden-baden/`) |
> | Specific matter context (Hagenauer, Cupial, MOVIE, AO, Annaberg, Balgerstrasse) | matter desk for that slug (`wiki/<matter-slug>/`) |
>
> **First-message confirmation phrase (evidence-bound, exact):** `"AH1 oriented (Tier 0). Read: aihead1/orientation.md, ai-head/SKILL.md, laconic/SKILL.md. Tier 1+ on demand."`
>
> AH1 picker has NO auto-memory directory (Director-ratified 2026-05-08 PM, mirror AH2 — drops start cost to ~6%). All historical session handovers + feedback + project memories live in baker-vault `_ops/agents/aihead1/handover-archive/YYYY-MM/` + `_ops/agents/aihead1/auto-memory-archive-20260508/`. Read on demand. Latest in-flight state lives in `_ops/agents/aihead1/operating.md` + `ARCHIVE.md` (canonical, no MEMORY.md). SessionEnd hook at `.claude/hooks/aihead1-session-end.sh` warns on uncommitted/unpushed `_ops/agents/aihead1/` state.
>
> Block applies when cwd path is `/Users/dimitry/bm-aihead1` OR a Cowork-spawned worktree under it (`bm-aihead1/.claude/worktrees/<name>`). Pre-2026-05-10 the check was strict basename only, which broke when Cowork forced worktree-mode on the standalone clone and spawned sessions under `.claude/worktrees/`. Pre-2026-05-08 AH1 sessions opened directly at `~/Desktop/baker-code` and used the heavier auto-memory slug there — that fallback path remains operational but new sessions should use the picker.

@.claude/how-to/INDEX.md

Brisen Group's institutional intelligence — not Director's assistant but the
system that carries Brisen matters end-to-end. Per-matter Cortex cycles sense
signals, analyze via invoked domain specialists (legal / finance / tax /
game-theory), synthesize across raw data + curated knowledge, propose decisions,
and execute on Director approval. Director ratifies; Baker carries.
Self-learning per matter; adversarial-aware.

**Sentinel** = AI system. **Baker** = reasoning + action layer.
**CEO Cockpit** = dashboard at baker-master.onrender.com.
Repo: github.com/vallen300-bit/baker-master.

## Stack
FastAPI (port 8080), Python 3.11+, PostgreSQL (Neon), Qdrant Cloud (Voyage AI
voyage-3, 1024d), Claude Opus via Anthropic API, vanilla JS frontend, Render
auto-deploys from `main`. Auth: `X-Baker-Key` header; CORS via `ALLOWED_ORIGINS`.

## Operating model (current — supersedes BAKER_OPERATING_MODEL_v2 / "two hats")
Per Director directive 2026-04-28T07:00Z + `_ops/processes/ai-head-autonomy-charter.md` (ratified 2026-04-22, promoted 2026-04-28):
- **AI Head A** (`aihead1` terminal, `~/Desktop/baker-code`) — sole orchestrator: dispatches briefs, reviews PRs, executes merges, runs recoveries. Autonomous within Cortex Design (charter §3); consults Director only on §4 prerogatives.
- **AI Head B** (`aihead2` terminal, same dir, separate Code instance) — cross-lane review + AUTOPOLL lane + Mon 09:30 UTC `gold_audit_sentinel` watch.
- **Code Brisen build pool** — `b1` / `b2` / `b3` / `b4` (each its own clone at `~/bm-b{N}`); `b5` dormant. Worktree map: `Desktop/baker-code/00_WORKTREES.md`.
- **Director** — final authority. Ratifies Cortex Design changes; ignores tactical execution.
- **RA retired** 2026-04-28T07:00Z. RA's prior role was ideation / synthesis — that work now happens via direct Director ↔ AI Head conversation. AI Head A was already the orchestrator.
- B-code briefs land at `briefs/_tasks/CODE_<N>_PENDING.md`; coordination protocol: `_ops/processes/b-code-dispatch-coordination.md`.

## Workflow
- Tests first — reproduce the bug with a test, then make it pass.
- Surgical edits — don't touch code orthogonal to the task.
- Autonomous bug fixes OK — diagnose from evidence, just fix it.
- After corrections, append to `tasks/lessons.md`.
- Briefs from AI Head A/B arrive as paste-block (problem → constraints → acceptance criteria).
- Commit + push only when authorized.

## Commands
- Syntax check: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- All tests: `pytest`
- Single test: `pytest tests/test_<name>.py -v`
- Live-PG tests: require `TEST_DATABASE_URL` env (else auto-skip); CI auto-provisions
  ephemeral Neon branch via `NEON_API_KEY` + `NEON_PROJECT_ID`
- Local dev (auto-reload, port 8080): `python outputs/dashboard.py`
- Production start (Render): `bash start.sh`
- Install deps: `pip install -r requirements.txt`
- Singleton-pattern CI guard: `bash scripts/check_singletons.sh`
- Slug-registry validation: `python scripts/validate_eval_labels.py`
- Deploy: push to `main` → Render auto-deploys (no manual step)

No lint/typecheck config in repo. No GitHub Actions; Render is single deploy path.

## Architecture — Cortex 3T migration in progress

**Today (2026-04-29):** Cortex Stage 2 V1 partially shipped — `CORTEX_3T_FORMALIZE_1A` + `1B` + `1C` merged 2026-04-28; `CORTEX_PHASE5_IDEMPOTENCY_1` (PR #75) merged 2026-04-28T17:24Z. DRY_RUN pending. First live AO-matter cycle = next milestone (per `_ops/processes/cortex-stage2-v1-tracker.md`).

**Canonical RA-23 spec:** `_ops/ideas/2026-04-27-cortex-architecture-final-locked.md`
(ratified 2026-04-27; will promote to `_ops/processes/cortex-architecture-final.md` via AI Head A Tier B).
**Stage 1 brief:** `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md` (RA-22).

### Legacy (still running, being migrated)
- **18 active capability sets** out of 24 total (2 client_pm + 14 domain + 2 meta active; 6 domain inactive). DB-verified 2026-04-29 via `SELECT capability_type, active, COUNT(*) FROM capability_sets GROUP BY 1,2`. Accessed via fast/delegate path (`classify_intent()` → capability match → SSE stream).
- Matter-PM absorption into Cortex per-matter configs **ratified 2026-04-27 (RA-23)**; execution lands when Stage 2 V1 first AO-matter cycle clears DRY_RUN. Until then: AO PM + MOVIE AM remain queryable via dashboard "Ask AO PM" / "Ask MOVIE AM" buttons.

### Target (Cortex 3T — RA-23 ratified)
- **Cortex Core:** 6-phase cycle (sense → load → reason → propose → act → archive)
  in `orchestrator/cortex_runner.py`.
- **Per-matter configs** absorb matter-PM brains; live in `baker-vault/wiki/matters/<slug>/cortex-config.md`.
- **Invoked domain capabilities** (legal / finance / tax-CH/AT/DE / game-theory) called from Phase 3b.
  Cap **5/cycle**, **60s** per specialist (2 retries), **5-min** absolute cycle timeout.
- **Curated knowledge** per matter in `wiki/matters/<slug>/curated/<topic>-<date>.md`
  (post-reasoned outputs, NOT raw data). Postgres mirror via `cortex_phase_outputs`.
- **Entity registry** in `wiki/people/<slug>.md` + `wiki/entities/<slug>.md`.
- **Activation:** Cortex auto-trigger (Phase 3a meta-reasoning) OR Director manual (Scan/dashboard).
  No third path. No cron / peer / sentinel-direct triggering.
- **Cortex meta-knowledge:** `wiki/_cortex/{director-gold-global,cross-matter-patterns,brisen-style}.md`.

### Signal flow
WhatsApp + email + meeting transcripts → ingestion classifies → `signal_queue`
(with `matter_slug` + 0-3 `related_matters`) → Cortex Phase 1 (sense).
WhatsApp pipeline: WAHA webhook → classify → route → `_wa_reply()`. 6h backfill.

### Read/write split (Cortex era)
- Sentinels write raw data tables; never wiki.
- Cortex Phase 3 specialists write `cortex_phase_outputs` + curated markdown; read raw.
- Director GOLD writes `proposed-gold.md` per matter via PR #66 workflow.
- AI Head Tier B writes per-matter `cortex-config.md`.
- All Baker writes audited to `baker_actions` table.

## Where stuff lives
- `outputs/dashboard.py` → FastAPI app entry (~11.7k lines — be aware before edits)
- `orchestrator/` → Cortex runner + capability framework (`cortex_runner.py`, `capability_router.py`, etc.)
- `kbl/` → Knowledge Base Layer: slug registry, retrievers, RAG pipeline, Anthropic client
- `models/` → data models (deadlines, contacts, etc.)
- `triggers/` → ingestion triggers (Gmail polling, WAHA webhooks)
- `tools/` → MCP tools (24 tools per `.claude/docs/baker-mcp-api.md`)
- `migrations/` → DB schema migrations
- `tests/` → pytest suite
- `briefs/` → AI Head specs; `_tasks/CODE_<N>_PENDING.md` = active dispatch mailbox; `_reports/` = B-code completion reports
- `tasks/lessons.md` → corrections-turned-rules; append on every mistake
- `_ops/` → skills, processes, agents, ratified-but-not-yet-promoted ideas (vault-side)

## Hard rules — project-specific (don't do)
- **Never write to ClickUp outside BAKER Space (901510186446).** Kill switch: `BAKER_CLICKUP_READONLY=true`. Max 10 writes/cycle.
- **Never auto-send external email.** Internal auto-send OK for routine ops; external always drafts first.
- **Never instantiate `SentinelRetriever()` or `SentinelStoreBack()` directly** — use `_get_global_instance()`. CI guard: `bash scripts/check_singletons.sh`.
- **Never write content directly to `MEMORY.md`** — it's an index. Detail goes in typed files under `memory/`.
- **Never modify `baker-vault/slugs.yml` from this repo** — separate-repo PR only.
- **Never delete or rewrite `tasks/lessons.md` entries** — append-only audit trail.
- **Never edit `outputs/dashboard.py` carelessly** — re-run relevant tests after every change.
- **Editing an applied migration is forbidden** unless (1) prod has been corrected by hand AND (2) you refresh `applied_migrations.lock` from prod. Bypass mechanism (`Migration-edit-authorized:` commit trailer or `BAKER_MIGRATION_EDIT_AUTHORIZED=1` env-var for `-m` flow) is for that flow only — never to "make the build pass."
- **Never bypass `/security-review` skill on Tier-A merges** (Lesson #52).
- **All DB/API calls wrapped in try/except** — fault-tolerant or it doesn't ship.
- **IMPORTANT:** Compile-clean ≠ done. Exercise the actual flow before reporting (Lesson #8 — `tasks/lessons.md`).

## Out of scope (don't touch)
- `baker-vault/slugs.yml` — separate-repo PR only.
- `tasks/lessons.md` existing entries — append-only.
- `briefs/_reports/` — B-code completion artifacts; AI Head writes these.
- `_ops/` (vault-side, when present) — Director + Mac Mini commit per CHANDA Inv 9.
- `migrations/` already-applied files — never rewrite; create new migration to amend.
- `outputs/dashboard.py` line numbers in commit messages — file is volatile, line refs rot fast.

## Memory — two layers, do not conflate
- **Claude Code auto-memory** (this repo, this CLI session): `~/.claude/projects/<slug>/memory/`.
  Hot cache = this CLAUDE.md. Index = `MEMORY.md` (first 200 lines load every session).
  Deep storage = typed files in `memory/` (load on demand).
- **Cortex curated knowledge** (per-matter, persistent across cycles):
  `baker-vault/wiki/matters/<slug>/curated/`. Written by capability invocations + Director GOLD.
  Different system, different layer — see RA-23 spec.

## Compaction directive
When compacting this session, ALWAYS preserve:
1. Director-ratified decisions made this session (paste-block exports, ratifications, locked drafts).
2. Open paste-blocks pending Director response (Cowork Triagas, RA reports, AI Head briefs).
3. Current PR / commit state (branch, last commit hash, in-flight PR numbers).
4. Active matter context if discussed (matter slug, current move, pending deadline).
5. Any in-progress migration / restructure draft state (file paths, locked sections).
Drop: routine code reads, intermediate file dumps, resolved error traces, casual chat.

## Matter slug registry
Canonical slugs in `baker-vault/slugs.yml` (separate repo, edit via PR).
Loader: `kbl/slug_registry.py`. Consumers: `scripts/validate_eval_labels.py`,
`scripts/run_kbl_eval.py`, `scripts/build_eval_seed.py`.
Env: `BAKER_VAULT_PATH` must point at vault checkout. 34 canonical slugs @ version 12 (updated 2026-04-26; verify via `grep -c "^  - slug:" baker-vault/slugs.yml`).

## Session start
1. `git pull && git log --oneline -10`
2. Read this file.
3. Every ~5 sessions: 5-min memory audit — scan `memory/` for stale dates,
   resolved items, prune silently, flag ambiguous.
4. Ask the Director what to work on.
5. If pre-commit hook not installed: `git config core.hooksPath .githooks`.

## End of session
1. Update this file (move completed items, note blockers).
2. Commit + push when authorized.
3. Note blockers for next session in `memory/`.

## Reference pointers
- **AI Head autonomy charter (canonical operating doc):** `_ops/processes/ai-head-autonomy-charter.md` — CEO/dept-head model, autonomous zone (§3), Cortex Design prerogatives requiring Director consult (§4).
- **B-code dispatch coordination:** `_ops/processes/b-code-dispatch-coordination.md`
- **Worktree map (5 active terminals):** `~/Desktop/baker-code/00_WORKTREES.md`
- **Cortex architecture (canonical):** `_ops/ideas/2026-04-27-cortex-architecture-final-locked.md` (RA-23 lock)
- **Cortex Stage 1 brief:** `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md`
- **Cortex roadmap (canonical):** `_ops/processes/cortex3t-roadmap.md` (Director-ratified 2026-04-25; M0 ✅ closed; M1 in flight)
- **Cortex Stage 2 V1 tracker:** `_ops/processes/cortex-stage2-v1-tracker.md`
- **Lessons learned:** `tasks/lessons.md` — append on every correction
- **Baker MCP API patterns:** `.claude/docs/baker-mcp-api.md`
- **Critical IDs** (workspaces, lists, contacts): `.claude/docs/critical-ids.md`
- **Path-scoped rules:** `.claude/rules/`
- **Specialized agents:** `~/.claude/agents/` (user-global — not in repo per HARNESS_SUBAGENT_MIGRATION_1)
- **Full architecture diagrams:** `CLAUDE_REFERENCE.md`
