# BRIEF: FUND_AGENT_SEAT_INSTALL_1 — install "The Fund" (the-fund) as a standing Brisen Lab tmux seat, persona-pack-only cage

## Problem

D-057 (Director-ratified 2026-07-24): the Fund persona — adversarial in-persona reviewer of AO-facing artifacts — graduates from summoned subagent to a permanent Lab seat with full memory. Two pilot runs flown and done-gated; borrow-pass complete (cowork #15716); cage ruling final (cowork #15719). Seat does not exist: no picker, no card, no key, no wiring.

Dispatch authority: Director ratification (charter §Director rulings 1-5) + cowork ready-ping #15716/#15719. Crew pre-ratified: deputy build (you) → deputy-codex review → codex gate → lead merge/Tier-B → ARM stamp.

## Context

- **Identity:** slug `the-fund`, display "The Fund", registry AG-406 committed vault @cf9a938 (status `planned` — flips `active` at done-gate; do NOT flip it yourself).
- **Seat charter (verbatim constraints, Director-ratified — memory + #15719):**
  1. tmux seat, cockpit card (fleet standard, librarian-era pattern).
  2. **Persona-pack-only cage — the load-bearing rule.** The seat loads ONLY `wiki/matters/oskolkov/04_working_brief/fund-agent-persona-pack-v1.md` + the artifact dropped for review + its own `fund-agent-memory.md` (append-only). NO other vault/repo/Dropbox/archive reads. It must never see `fund-agent-charter-v1.md`, CONTEXT.md, decision logs, or any de-facto-layer file — a read-all seat destroys the persona (it discovers it is fictional and its objections stop being honest).
  3. **NO email** — no send, no draft. Structural block, not prose.
  4. **Comms whitelist:** bus agents + Director only. No external channels.
  5. CAN create documents — findings/memos — but only into its allowed write paths.
- **Work loop:** artifact in (file-drop into its inbox dir) → numbered in-character objections (BLOCK/CONDITION/NOTE, clause-tied) → findings out to orchestrator (cowork-ah1 / ao-desk) → seat appends its positions to `fund-agent-memory.md`. Its output is input to Gate 1, never a gate itself.
- Precedent install: librarian arc (baker-master @594d91c4 + brisen-lab @87e369e, PR #181) — mirror its wiring shape; cage precedent: designer cage hook (`.claude` hooks, path-allowlist).

## Estimated time: ~4h
## Complexity: Medium-High (standard 14-row install + custom cage)
## Prerequisites: vault @cf9a938 (registry) + @430aef8 (persona pack/memory canonical) — `git -C ~/baker-vault pull --rebase` first.

## Baker Agent Vault Rails
Relevant: bus-and-lanes, verification-surfaces, standing-contract (seat charter enforcement).
Ignored: loop-runner, memory-and-lessons (no lesson surface; seat memory is matter-side).

## Harness V2

- **Task class:** feature (production fleet seat) — full gate chain.
- **Context Contract:** inputs = this brief + install SOP (`~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md`, 14-row map) + registry @cf9a938 + persona pack/memory @430aef8 + librarian install as wiring precedent. The seat's charter file is orchestrator-side — you MAY read it to build the cage; the SEAT must never load it (enforce in cage allowlist).
- **Done rubric / done-state class:** DONE (your slice) = repo PRs open, literal pytest output, 14-row table with dispositions, cage negative-tests passing. NOT done at compile-clean; live rows are lead's; registry flip + ARM stamp close the arc (three-signature gate; registry stays `planned`/`pending-arm-stamp` until then).
- **Gate plan:** deputy-codex review → codex gate (cite repo+branch+sha, never PR#) → lead merge + Tier-B local rows + E2E → ARM 14-row stamp at `wiki/_fleet/audits/`.

---

## Fix/Feature 1: 14-row wiring (enumerated — never silently omit)

Owner key: [D] = deputy (repo-side, this brief) · [L] = lead Tier-B post-merge.

- **Row 0 pre-flight [D]:** existing-workspace audit — `ls ~/bm-* ~/Vallen\ Dropbox/Dimitry\ vallen/bm-* 2>/dev/null | grep -i fund` + `grep -n "fund" ~/.zshrc`. Expect empty (greenfield per cowork pre-check pattern); any hit → STOP, post lead.
- **Row 1 picker [D]:** `bash scripts/install_picker_dir.sh the-fund` → `~/bm-the-fund/`; register snapshot path in `generate_agent_identity_artifacts.py` `_snapshot_path_for()`; regen artifacts BOTH repos (registry @cf9a938 already carries the entry); commit regenerated files. Treat the generator's stderr WARNING as a completion gate.
- **Row 2 zshrc [D writes block, L applies]:** function `thefund()` — cd `~/bm-the-fund`, `BAKER_ROLE=the-fund FORGE_TERMINAL=the-fund`, git-pull-rebase-autostash line, launch claude. Deliver the block in your ship report; lead pastes (user-file, not repo).
- **Row 3 Terminal profile [L]:** `.terminal` + `open` import, name "The Fund" (= card alias parity).
- **Row 4 picker CLAUDE.md [D]:** Tier-0 = persona pack ONLY + first-message confirmation phrase + review protocol + bus_post path `~/bm-b1/scripts/bus_post.sh`. MUST NOT reference charter/CONTEXT/decision-log. Include the comms whitelist + no-email rules verbatim.
- **Row 4b cage hook [D] — the custom row:** PreToolUse Read/Glob/Grep allowlist hook in `~/bm-the-fund/.claude/` (designer-cage pattern): allowed reads = picker dir + persona pack path + `fund-agent-memory.md` + `~/bm-the-fund/inbox/` (artifact drops). Allowed writes = picker dir + `fund-agent-memory.md` (append-only enforced: hook rejects Write/Edit to it, allows Bash `>>`-only helper or an append script) + `wiki/matters/oskolkov/04_working_brief/fund-findings/` (new dir, findings out). EVERYTHING else blocked — including email/external tools (no Gmail/Outlook/WAHA/MCP-mail tools in permissions), charter file explicitly denied by path. Negative tests required (see Verification).
- **Row 5/6 bus_post.sh whitelists [D]:** recipient + sender cases for `the-fund` (canonical `~/bm-aihead1/scripts/bus_post.sh` — commit on baker-master main).
- **Row 7 drain hook [D fixture, L deploys]:** add `the-fund` to BAKER_ROLE case in `tests/fixtures/session-start-bus-drain.sh`; lead cp-deploys to `~/.claude/hooks/`.
- **Row 8 1P key [L]:** `BRISEN_LAB_TERMINAL_KEY_the-fund`, category "API Credential", field `credential` (Lesson #78).
- **Row 9 Render env [L]:** merge into `BRISEN_LAB_TERMINAL_KEYS` + explicit POST /deploys.
- **Row 10 front-end [D]:** brisen-lab card — index.html article + app.js TERMINALS + LABELS ("The Fund"). Surface contract: card in the desks row, alias `the-fund`, same card grammar as librarian's.
- **Row 11 server FOUR places [D]:** bus.py KNOWN_CARD_SLUGS + `_build_terminals_response()` tuple + app.py TERMINALS + regression tests `tests/test_a3_a8_a9_bus.py`. Pre-flight grep per SOP (expect 3 matches before edit). Plus cockpit manifest row (librarian precedent @594d91c4): `cockpit_launch_manifest.json` + layout + reconciliation note, next free ttyd port.
- **Row 12 snapshot pusher [D]:** `the-fund:~/bm-the-fund` in `forge_snapshot_push.sh` TERMINALS — picker has no `.git`? `install_picker_dir.sh` output decides: if no git repo, use `~/baker-vault` (hard rule, RESEARCHER_ON_BUS_1 @7fb9072). Regression test case. [L] redeploys pusher BOTH hosts.
- **Row 13 wake-handler [D]:** BOTH maps — fnMap `{"the-fund","thefund"}` + cwdForAlias `~/bm-the-fund`. Bare-CR submit pattern (never key code 36). [L] rebuilds via build.sh.
- **Row 14 wake-listener [D]:** ALLOWED_ALIASES + deployed-copy diff noted for lead. [L] deploys + kickstarts.

## Key Constraints
- The cage is the point. If any row conflicts with the cage (e.g. drain hook injecting fleet context), cage wins — surface, don't average.
- tmux session row [L] per librarian pattern (`install_cockpit_ttyd.sh the-fund` + tmux session at lead's step).
- Registry: do not edit; do not flip `planned`.
- No model override anywhere — seat inherits picker default (Opus; judgment seat, Sonnet policy §4b does not apply to standing judgment seats).
- Base: both repos origin/main at pickup; cite repo+branch+sha in ship post.

## Files Modified
- baker-master: `scripts/generate_agent_identity_artifacts.py` (+regen artifacts), `scripts/bus_post.sh`, `scripts/forge_snapshot_push.sh` + test, `tests/fixtures/session-start-bus-drain.sh`.
- brisen-lab: regen `agent_identity_generated.py`, `bus.py`, `app.py`, `static/index.html`, `static/app.js`, `tests/test_a3_a8_a9_bus.py`, `scripts/cockpit_launch_manifest.json` + layout + reconciliation, `tools/wake-handler/wake-handler.applescript`, `tools/wake-listener/wake-listener.py`.
- New (uncommitted, picker-side — describe in ship report): `~/bm-the-fund/CLAUDE.md`, `~/bm-the-fund/.claude/` cage hook + settings, `~/bm-the-fund/inbox/`.
- baker-vault: `wiki/matters/oskolkov/04_working_brief/fund-findings/.gitkeep` (findings-out dir).

## Do NOT Touch
- `fund-agent-persona-pack-v1.md` / `fund-agent-charter-v1.md` / `fund-agent-memory.md` — content is cowork's lane; you wire paths only.
- `_ops/registries/agent_registry.yml` — committed already.
- Any Render env / 1P — lead only.

## Quality Checkpoints
1. All 14 rows in ship report with disposition (done / N/A-reason / lead-owed).
2. Literal pytest output both repos; syntax checks on every touched .py.
3. Cage negative tests: seat-side Read of charter file → BLOCKED; Read CONTEXT.md → BLOCKED; Write outside allowed paths → BLOCKED; append to memory → ALLOWED; Read persona pack → ALLOWED. Literal hook-output transcript in report.
4. Ship post to lead: repo+branch+sha both repos + row table; deputy-codex review next (lane restated on any re-dispatch — known drift).

## Verification SQL
```sql
-- post-install (lead E2E): message to the seat lands
SELECT id, from_terminal, to_terminals, topic, created_at FROM brisen_lab_msg
WHERE 'the-fund' = ANY(to_terminals) ORDER BY id DESC LIMIT 5;
```
