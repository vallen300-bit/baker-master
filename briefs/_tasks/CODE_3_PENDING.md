---
status: PENDING
brief_id: CLERK_ON_BUS_1
dispatch: CLERK_ON_BUS_1 (repo-work rows; AH1 owns Tier-B + picker)
to: b3
from: lead
dispatched_by: lead
task_class: agent install — 3-repo PRs (repo rows of the 14-row SOP)
harness_v2: applies
slug: clerk
brief_path: baker-vault _ops/briefs/BRIEF_CLERK_ON_BUS_1.md (commit f9e0573, codex G0 v3 PASS #1850)
sop: ~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md
---

# B3 dispatch — CLERK_ON_BUS_1 (repo-work rows)

**Full spec: baker-vault `_ops/briefs/BRIEF_CLERK_ON_BUS_1.md` (f9e0573). codex G0 v3 PASS (#1850). Read it + the SOP. This envelope = the split + gate contract.**

Install the new worker **Clerk** (slug `clerk`, picker `~/bm-clerk`) onto Brisen Lab. Director-authorized via codex #1833. **Bus/terminal presence only** — the Workbench + cheap-model runtime are Phase 2 (`BRIEF_CLERK_WORKBENCH_1`, not in scope).

## Split of ownership
- **AH1 already did (do NOT redo):** Row 1 picker dir `~/bm-clerk/` + `CLAUDE.md` + `.claude/skills/clerk/SKILL.md` (AH1-local, not a repo).
- **AH1 owns Tier-B post-merge (do NOT attempt):** Row 2 zshrc, Row 3 Terminal profile, Row 6 1P key, Row 7 Render env, Row 11 forge redeploy, Row 13/14 wake rebuild+listener reload.
- **YOUR repo-work rows (PRs):**
  - **baker-master PR:** Row 5 `scripts/bus_post.sh` — add `clerk` to recipient case (~line 49) AND `clerk|CLERK) SENDER=clerk` to the BAKER_ROLE case (~line 60); Row 7 drain-hook fixture `tests/fixtures/session-start-bus-drain.sh` add clerk to BAKER_ROLE case; Row 10 `scripts/forge_snapshot_push.sh:61` TERMINALS add `clerk:~/baker-vault` + regression case in `tests/test_forge_snapshot_push.sh`.
  - **brisen-lab PR:** Row 8 `static/index.html` add `<article class="card" data-alias="clerk"></article>` to **`.row-shared`** (NOT `.row-desks` — doesn't exist), `static/app.js` add `clerk` to TERMINALS (~:9) + `clerk:"Clerk"` to TERMINAL_LABELS (~:11) + `clerk:"shared-specialist"` to CARD_TYPE (~:24-37); Row 9 server FOUR places — `bus.py:1177` KNOWN_CARD_SLUGS, `bus.py:1334` _build_terminals_response for-loop tuple, `app.py:40` TERMINALS, `tests/test_a3_a8_a9_bus.py` regression (SSE badge + /api/v2/terminals include clerk); Row 13 wake-handler `tools/wake-handler/wake-handler.applescript` fnMap (~:129) `{"clerk","clerk"}` + cwdForAlias (~:41) `if a is "clerk" then return "/Users/dimitry/bm-clerk"` (Clerk is a Claude picker → use the Claude submit path, NOT codex bare-CR); Row 14 wake-listener `tools/wake-listener/wake-listener.py:23` ALLOWED_ALIASES add `"clerk"`.

## Sequencing (SOP three-repo): baker-master PR → brisen-lab PR. (baker-vault already has the agent brief.)

## Gate contract (Harness V2)
- **Done rubric (literal):** both PRs merged; `pytest tests/test_a3_a8_a9_bus.py -v` (brisen-lab) + `bash tests/test_forge_snapshot_push.sh` (baker-master) literal green in PR; pre-flight `grep -nE '"lead".*"deputy".*"b1"' bus.py app.py` = 3 known sites before edit.
- **Gates per PR:** G1 lead literal pytest → G2 /security-review → G3 codex → AH1 merge.
- After both merge, bus lead: "CLERK repo rows merged, shas X/Y" — AH1 then runs Tier-B + AC12 smoke.
- Ship report answers the done rubric literally; bus to lead. NOT Director-facing register.

## Do NOT
- Touch Row 1-4 picker (AH1 done), Tier-B rows (AH1 owns), or build the Workbench/Flash-Lite runtime (Phase 2).
- Introduce slug variants — one canonical `clerk`.
