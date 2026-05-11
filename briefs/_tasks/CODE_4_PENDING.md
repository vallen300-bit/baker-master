---
status: STAGED
brief: ~/baker-vault/_ops/briefs/CODEX_JUDGE_INTEGRATION_IMPL_1.md
brief_commit: 4dcd484 (baker-vault main)
design_spec: ~/baker-vault/_ops/briefs/CODEX_JUDGE_INTEGRATION.md (v0.5, AID)
trigger_class: TIER_B_NEW_GH_ACTION_PLUS_EXTERNAL_API_PLUS_AUTH_SURFACE
dispatched_at: 2026-05-11
dispatched_by: ai-head-a
target: b4
director_ratification: Director ratified brief commit + push 2026-05-11 (paste-block); B4 dispatch (status flip STAGED → PENDING) gated on 5 hard blockers below.
priority: P1
phase: 1 of 1 (single PR scope, ~16-20h B4)
unblocks:
  - Cross-provider judge gate on every AH1-authored PR (advisory, AH1 discretion)
  - AID CONTRACT v1.1 §9 verification stack
expected_pr_count: 1 (baker-master — first .github/workflows/ entry)
expected_branch_name: b4/codex-judge-integration-impl-1
expected_complexity: medium-high (~16-20h)
mandatory_2nd_pass: TRUE  # Trigger #1 (auth/authz — bot allowlist) + #4 (external surface — OpenAI API key + GH Action) + #7 (judgment: high-stakes greenfield .github/)
hard_ship_gate: literal pytest output for schema validation + GC sweeper + decommission filter; A16 self-test PR produces a real Codex verdict (not stub)
ship_target: 2026-05-22 B4 finish → 2026-05-24 smoke → 2026-05-25 shadow week
last_heartbeat: null
gate_to_merge: AH2 /security-review + picker-architect + feature-dev:code-reviewer 2nd-pass + Director ratification of A16 self-test verdict
xlane_aid_msg: 87 (original — over-scoped per pre-CONTRACT-v1.1 design spec; superseded)
xlane_aid_q5_q8_msg: 97 (thread ae569f76)
xlane_aid_rescope_msg: 99 (thread 94a79c67 — corrected ownership matrix per CONTRACT v1.1)
director_q5_q8_answers:
  q5_judge_scope: baker-master only
  q6_data_residency: US default + no-training toggle (no ZDR, no EU)
  q7_outcome_loop: advisory only, no feedback loop
  q8_bot_identity: keep distinct (ah1-bot, b1-bot..b4-bot) — AH1 recommendation followed
  ratified_at: 2026-05-11T~14:20Z (Director chat)
hb4_status: CLEARED 2026-05-11 (Q5-Q8 answered)
ownership_rescope_2026_05_11: per Director directive 2026-05-11 ~14:45Z — AID is design-time only post CONTRACT v1.1. Procurement → Director, accounts → Director, infra build → AH1. AID retains only HB5 (prompt-file).
---

# CODE_4_PENDING — BRIEF_CODEX_JUDGE_INTEGRATION_IMPL_1 — STAGED 2026-05-11

**STATUS = STAGED — DO NOT START YET.** AH1 will flip to PENDING + post wake message on bus when all 5 hard blockers below clear.

## What this brief is

Implementation of AID's CODEX_JUDGE design spec v0.5 — cross-provider (OpenAI Codex / GPT-5) advisory judge running as a GitHub Action on every AH1-authored PR. Verdict is permanently advisory (AH1 discretion). Driven by AID CONTRACT v1.1 §9 (ratified Director 2026-05-11) to escape Claude-family review bias.

Brief location: `~/baker-vault/_ops/briefs/CODEX_JUDGE_INTEGRATION_IMPL_1.md` (745 lines, ratified V0.2 with 4 HIGH + 8 MED + 4 LOW folded — review chain cleared by feature-dev:code-architect + feature-dev:code-reviewer V0.1 + V0.2 fold-quality re-review).

Repo touched: `baker-master` only. AID's picker repo + bus-host config out of scope (AID's lane).

## Hard blockers — all 5 must clear before STAGED → PENDING flip

**Ownership matrix CORRECTED 2026-05-11 ~14:45Z** per Director directive — pre-CONTRACT-v1.1 design spec assigned procurement / accounts / infra-build to AID; that's wrong post-CONTRACT v1.1 (AID is design-time only). Re-cut below.

| # | Blocker | Owner (corrected) | Target date | Status |
|---|---|---|---|---|
| HB1 | `CODEX_API_KEY` procurement (OpenAI account / billing setup / $200/mo cap / "no training" toggle / API key generation); then 1Password "AI Infrastructure" storage + baker-master repo secret + OpenAI Python SDK floor version confirmation (`openai>=1.40.0,<2.0.0` provisional) | **Director** (account/billing/key gen) + **AH1** (1Password + repo secret storage once key in hand) | 2026-05-13 | open — Director action item surfaced in chat |
| HB2 | Bot accounts `ah1-bot`, `b1-bot`, `b2-bot`, `b3-bot`, `b4-bot` provisioned (5 GitHub accounts in vallen300-bit org); allowlist file `.github/codex-judge-allowlist.yml` populated | **Director** (org-admin account creation only he can do) + **AH1** (allowlist YAML once accounts exist) | 2026-05-14 | open — Director action item surfaced in chat |
| HB3 | Caveat 4 design + build (bus-host monitoring + secondary log-pull path) | **AH1** (engineering). Optional: AID may hand AH1 a 1-page design sketch if Director asks; not required | 2026-05-14 | open — AH1 will draft + dispatch to a B-code per standard pattern |
| HB4 | Director Q5-Q8 answers (judge repo scope; OpenAI data-residency / ZDR; outcome→tuning loop; matter-confidentiality on bot-PR AI-author identity) | Director | 2026-05-11 | **CLEARED** — Q5: baker-master only; Q6: US + no-training (no ZDR); Q7: advisory only, no loop; Q8: keep distinct bot accounts |
| HB5 | AID delivers `_ops/scripts/codex_judge_prompt.md` v1.0 (system-instruction template; without it B4's A16 self-test produces stub verdicts) | **AID** — sole remaining ask on AID's lane (prompt engineering = AID's library scope per Tier-0 routing) | 2026-05-14 | open — corrected xlane bus msg #99 thread `94a79c67` |

**Caveat 5** (Codex API key 90d rotation) stays with AID long-term as program/operational ownership (Dennis Egorenkov coordination if needed) — that's not engineering, that's program management which IS in AID's lane.

## Wake-paste sequence (when all 5 clear)

1. AH1 verifies HB1-HB5 cleared (1Password key + bot accounts + AID caveat 4 reply + Director Q5-Q8 + prompt-file v1.0).
2. AH1 flips frontmatter `status: STAGED` → `status: PENDING`.
3. AH1 commits + pushes mailbox flip to baker-master main.
4. AH1 posts bus wake-paste to b4 (topic `dispatch/codex-judge-impl-1-pending`) with brief anchors.
5. B4 picks up via SessionStart bus drain on next session.

## Path forward (B4 — DO NOT execute until STAGED → PENDING flip)

**First-message confirmation phrase (evidence-bound, exact):**
`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

When fired:

1. Read `~/baker-vault/_ops/briefs/CODEX_JUDGE_INTEGRATION_IMPL_1.md` cover-to-cover (745 lines — single most-important read).
2. Read upstream design spec `~/baker-vault/_ops/briefs/CODEX_JUDGE_INTEGRATION.md` v0.5 for context.
3. Sync baker-master: `cd ~/bm-b4 && git fetch origin main && git checkout main && git pull --ff-only`.
4. Branch: `git checkout -b b4/codex-judge-integration-impl-1`.
5. Implement per brief Step 1A (Action workflow + config files), Step 1B (`codex_judge_call.py` + bus relay), Step 1C (decommission scripts), Step 2 (state-key GC sweeper Action), Step 3 (tests).
6. Live `pytest tests/ -v` GREEN (capture literal output).
7. A16 self-test: open a tiny PR on baker-master to fire the new Action against a real Codex verdict (NOT stub). Confirm verdict shape matches `schema/judge-verdict-v1.0.json`.
8. Open PR. Title: `feat(judge): cross-provider Codex GH Action (CODEX_JUDGE_INTEGRATION_IMPL_1)`.
9. Ship via PL paste-block per SKILL.md §"PL ship-report contract".

## Critical do-NOTs

- Do NOT write any OpenAI / Codex API key value into a source file, brief, commit message, or PR description. Key lives in 1Password + repo secret only.
- Do NOT widen `.github/codex-judge-allowlist.yml` beyond AH1-authored bot actors. Director ratification needed for any addition.
- Do NOT make the verdict blocking. Permanently advisory per Director ratification + AID CONTRACT v1.1.
- Do NOT skip HB5 (`_ops/scripts/codex_judge_prompt.md`). Without it the A16 self-test verdict is meaningless.
- Do NOT touch AID's picker repo or bus-host config — caveats 4 + 5 are AID's lane (out of scope).
- Do NOT exceed brief scope on first PR — Step 1B's `codex_judge_call.py` is the heaviest module; resist gold-plating.

## 4-gate review chain on PR (post-B4 ship)

- Gate 1: B4 pytest GREEN (literal output in PR description)
- Gate 2: AH2 `/security-review` against diff
- Gate 3: AH1 picker-architect (greenfield `.github/` workflows + first cross-provider API surface — high-stakes architecture review)
- Gate 4: AH1 `feature-dev:code-reviewer` 2nd-pass (parallel with Gate 3 — MANDATORY per SKILL.md §Code-reviewer 2nd-pass Protocol triggers #1 + #4 + #7)

## PL ship-report

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract".

## Heartbeat

12h cadence binding once STAGED → PENDING (per SKILL.md §"B-code stall chase"). Brief is medium-high (~16-20h) so expect 2-4 heartbeats during build.

## Anchors

- Director ratification (brief commit + push): 2026-05-11 (paste-block, captured in actions_log.md)
- AID design spec: `_ops/briefs/CODEX_JUDGE_INTEGRATION.md` v0.5 (2026-05-11, AID)
- AID CONTRACT v1.1 §9: bus msg #68 (broadcast, fleet-wide)
- Cross-lane to AID: bus msg #87 thread `62ddee32-cc15-4278-967b-83514854fbf6`
- Brief commit: `4dcd484` (baker-vault main)
- This mailbox stage commit: `<TBD>` (baker-master main)

— AH1 (lead, AH1-Terminal)

---

## Prior CODE_4 task (archive reference)

BRIEF_BRISEN_LAB_RENDER_CONFIG_READ_1 — COMPLETE 2026-05-11 ~11:08Z. brisen-lab PR #9 merged `96ed2702`; baker-master mailbox COMPLETE flip `8354b8b`. Render env-var PUT (`RENDER_API_KEY` on `srv-d7q7kvlckfvc739l2e8g`) + 6/6 live smoke tests GREEN. AID close-out via bus msg #84. Detail: was prior content of this file before STAGED-overwrite for codex-judge brief; full archive recoverable via `git log briefs/_tasks/CODE_4_PENDING.md` from baker-master main.
