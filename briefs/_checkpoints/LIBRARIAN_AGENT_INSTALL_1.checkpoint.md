---
brief_id: LIBRARIAN_AGENT_INSTALL_1
attempt: 1
updated: 2026-07-08
owner: b1
dispatched_by: lead
thread: 69558182-7a17-4227-b76b-1f9b08813a8b
---

# Checkpoint — LIBRARIAN_AGENT_INSTALL_1

## DONE (shipped + gated)
- **Wiring leg MERGED** (3 PRs, SOP order, SHA parity `9166ecb`; codex G3 PASS #7464, deputy G2 items 1-4):
  vault #144 (`a8cf99c`), master #492 (`440dba8b`), lab #107 (`253fb2d`). Registry AG-209 +
  generator KNOWN_FALLBACK_SLUGS + regenerated artifacts (3 repos) + index.html card +
  wake-handler both maps + all bus/forge/identity tests.
- **Cage leg SHIPPED** — baker-vault **PR #145** (`b9d8153`, branch `b1/librarian-cage`; follow-up
  since #144 merged). Deputy re-gate signaled #7467. Contents:
  - Hooks (`_ops/hooks/`): `librarian_write_cage.sh` (writes→wiki/_library/**), `librarian_bash_cage.sh`
    (Bash→librarian wrappers + read-only). cp of hardened researcher cages.
  - Scripts (`_ops/agents/librarian/scripts/`): `librarian_sql.sh` + `librarian_sql_guard.sh` (SELECT-only),
    `librarian_bus_reply.sh` (reply-only), `librarian_drain.sh` (kill switch + ack-after-receipt-check),
    `librarian_commit.sh` (wiki/_library delivery), `librarian_receipt_check.sh`.
  - `picker-settings.reference.json` (deny writes + 3 hooks), `CLAUDE.md.reference`, `seeded-violation-tests.sh`.
  - **Seeded suite: 13 passed, 0 failed** (literal output in PR #145 body).
  - Docs corrected for the baker_vault_write deviation (orientation §cage + data-surface-map #8).
- **Seat deployed** to `~/bm-librarian` (settings + CLAUDE.md + hook/script symlinks to vault canon).
  Row 2 `~/.zshrc librarian()` launcher added (Sonnet-pinned; `~/bm-librarian` has no .git → no pull line).
- Row 7 user-global drain hook deployed (`~/.claude/hooks/session-start-bus-drain.sh`).
- **Lead rulings:** #7448 (placement + runtime), #7454 (Row-1 snapshot deviation), #7457 (cage
  baker_vault_write-DENY + Write/Edit + librarian_commit + SELECT defense-in-depth). All APPROVED.

## Key design deviations (all lead-ratified — enumerate in ship report + spec v1.1 by cowork-ah1)
1. Install is registry-driven (eleventh-pass SOP) — Rows 5/6/7/10-server/11/12/14 = regenerate, not hand-edit.
2. Snapshot path = `~/baker-vault` (KNOWN_FALLBACK_SLUGS), NOT `~/bm-librarian` (no-.git grey-card foot-gun).
3. `baker_vault_write` DENIED (schema targets matters/, not _library); findings via Write/Edit + librarian_commit.sh.
4. Card placement = research-advisors (researcher's sibling).

## GATES — BOTH LEGS CLEAN
- Wiring: codex G3 PASS #7464 (merged). Cage: deputy G2 PASS #7469 + **codex cage G3 PASS #7476**
  (PR #145 @ `3fba108`). Codex FAIL #7473 fixed: F1 env-prefix hole (deny relocated before trusted
  continue + DAEMON/VAULT/ORIGIN hardcoded) + F2 WITH-CTE DML (SELECT-only + DML blacklist). Seeded suite 20/0.
- Handed to lead #7477 for merge + Tier-B.

## LEFT
- **Lead action (blocking Part C):** merge cage PR #145 + Tier-B — Rows 3 (Terminal profile) / 8 (1P key)
  / 9 (Render env + POST /deploys) / 13 (wake-handler build.sh) / 14 (wake-listener kickstart) + pusher
  redeploy both hosts + AC12 smoke + **latch lift Rows 8/9** (seat gets its key). Respond to any further
  fix rounds on the bus (main thread 69558182…).
- **Part C rung-1 acceptance** (LAST deliverable; run AFTER cage merges + lead Tier-B keys the seat, Row 8):
  8-10 seeded hunts across ≥5 surfaces (email/KBL/ClaimsMax/transcripts/vault/WhatsApp/SQL). Hunt #1 =
  live BREC2 securitization-notes issuance/subscription date + face + coupon (candidate AO_MASTER
  "…securitization notes (3).pdf", matter=ao), verbatim quotes; compare vs Opus €12M Gesamtgrundschuld
  reg. 2020-09-28 — HARD-FLAG conflicts, do NOT decide (G0 F3). Findings under `wiki/_library/findings/`,
  receipt-check PASS each. Deliver as rung-1 evidence.
- **Ship report(s)** → `briefs/_reports/` with the full 14-row audit (satisfied-by-registry vs hand-edit) +
  all 4 deviations + test output. Then lead posts POST_DEPLOY_AC_VERDICT.

## ROLLOVER (2026-07-08, ~86% context) — successor pickup
BOTH gate legs are CLEAN (wiring merged + codex G3 PASS #7464; cage deputy G2 PASS #7469 + codex cage
G3 PASS #7476). Cage PR #145 @ `3fba108` handed to lead #7477 for merge + Tier-B. Ship report written
(`briefs/_reports/B1_LIBRARIAN_AGENT_INSTALL_1_20260708.md`). Seeded suite 20/0.

**Successor FIRST action:** `check bus` for lead's merge/Tier-B signal on thread `69558182-…`.
- If lead reports #145 MERGED + Tier-B done (seat keyed, Rows 8/9 latch lifted): run **Part C rung-1
  acceptance** — the ONLY remaining builder deliverable. 8-10 hunts across ≥5 surfaces; hunt #1 = live
  BREC2 (AO_MASTER "…securitization notes (3).pdf", matter=ao): issuance/subscription date + face + coupon,
  verbatim quotes; compare vs Opus €12M Gesamtgrundschuld reg. 2020-09-28 — HARD-FLAG conflicts, do NOT
  decide (G0 F3). Write findings under `wiki/_library/findings/`, run `librarian_receipt_check.sh` on each
  (PASS required), reply to lead. Then lead posts POST_DEPLOY_AC_VERDICT.
- If a gate fix-round arrives instead: address on the bus, re-push #145, re-request the gate.
- Do NOT rebuild the wiring/cage — it is merged/gated. Do NOT re-run the gates.

**Claim discipline:** bump `attempt:` in this checkpoint's frontmatter to claim; if already bumped, stand down.
At `attempt >= 3` escalate to lead with this path + last state.

## Key paths
- Cage canon: `~/baker-vault/_ops/hooks/librarian_*.sh` + `~/baker-vault/_ops/agents/librarian/{scripts/,seeded-violation-tests.sh,picker-settings.reference.json,CLAUDE.md.reference}`.
- Seat: `~/bm-librarian/` (symlinks to canon). Registry: `~/baker-vault/_ops/registries/agent_registry.yml` (AG-209).
- Spec: `~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/SPEC_LIBRARIAN_AGENT_v1.md`.
- SOP: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (registry-driven since eleventh-pass).
