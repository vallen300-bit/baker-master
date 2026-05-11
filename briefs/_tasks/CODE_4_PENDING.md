---
status: PENDING
brief: briefs/BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md
trigger_class: TIER_B_AUTH_SURFACE_PLUS_NEW_ENV_VAR
dispatched_at: 2026-05-11
dispatched_by: ai-head-a
claimed_by: null
brief_revisions: V0.1
---

# CODE_4_PENDING — BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1 — 2026-05-11

**Brief:** baker-master `briefs/BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md` (Tier B, ~2-3 hours, 9 ACs)
**Working branch:** `b4/render-config-read-1` (brisen-lab repo)
**Repo:** brisen-lab @ `~/bm-b4-brisen-lab` (NOT baker-master)
**Pre-requisites:** brisen-lab main at `8b0b7fb` or newer (sync first: `git fetch && git checkout main && git pull --ff-only`)
**Acceptance criteria:** per brief §AC table (9 testable items, A1-A9)
**Ship gate:** literal `pytest tests/test_render_config.py -v` GREEN + `pytest tests/ -v` no regressions — no "by inspection" (Lesson #8 + #52)
**Heartbeat:** 12h cadence binding (per SKILL.md §B-code stall chase)

**Read first (MANDATORY):**
1. `briefs/BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md` — full spec + 3 features + 9 ACs
2. `~/baker-vault/_ops/agents/b4/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

**Path forward:**
1. Read brief BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1.md cover-to-cover.
2. Sync brisen-lab: `cd ~/bm-b4-brisen-lab && git fetch origin main && git checkout main && git pull --ff-only`. Confirm HEAD `8b0b7fb` or newer.
3. Branch: `git checkout -b b4/render-config-read-1`.
4. Implement Feature 1: write `render_config.py` per brief §1.1. Edit `app.py` 2 lines per §1.2. Verify `requirements.txt` has `httpx` (add if missing per §1.3).
5. Implement Feature 2: write `tests/test_render_config.py` per brief §2.
6. Live pytest GREEN: `pytest tests/test_render_config.py -v` (must be all-green) + `pytest tests/ -v` (no regressions). Capture literal output for PR description.
7. Open PR to brisen-lab `main`. Title: `feat(render-config): read-only Render API proxy on bus surface (BRISEN_LAB_RENDER_CONFIG_READ_1)`.
8. Ship via PL paste-block per SKILL.md §"PL ship-report contract".

**NOTE:** Feature 3 (live smoke tests) + Render env-var PUT happen POST-MERGE on AH1's side. B4 ships PR + tests; AH1 handles Tier-B env-var PUT + smoke tests + AID confirmation. Do NOT attempt to set `RENDER_API_KEY` env-var yourself — that's AH1's Tier-B action.

**4-gate review chain on PR (post-B4 ship):**
- Gate 1: B4 pytest GREEN (literal output in PR)
- Gate 2: AH2 `/security-review` against diff
- Gate 3: AH1 `architecture-review` via picker-architect
- Gate 4: AH1 `feature-dev:code-reviewer` 2nd-pass (parallel with Gate 3)

**Critical do-NOTs:**
- Do NOT write any Render API key value into a source file, brief, commit message, or PR description. Key lives in 1Password only; `RENDER_API_KEY` env var is set by AH1 post-merge.
- Do NOT widen `RENDER_CONFIG_ALLOWED_SLUGS` beyond `{"aid", "lead", "deputy"}`. Director ratified that whitelist 2026-05-11; widening = new Director ask.
- Do NOT add POST/PUT/PATCH/DELETE routes to `render_config.py`. Read-only is the contract.
- Do NOT touch baker-master — this is a brisen-lab-only brief. (The brief FILE lives in baker-master/briefs/ but the implementation is brisen-lab.)

**PL ship-report:** End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract".

**Anchor:** Director ratification 2026-05-11 ~07:55Z "confirm and go" on whitelist `['aid', 'lead', 'deputy']`. AID request relayed via Director chat (msg #62 thread re: cockpit fix closure). Brief commit `<TBD>` baker-master main.

---

## Prior CODE_4 task (archive reference)

BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1 — COMPLETE 2026-05-05. brisen-lab PR #3 merged `d7c46a0`; baker-master PR #161 merged `87f0535`. Mailbox COMPLETE flip committed `693b619`. Overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
