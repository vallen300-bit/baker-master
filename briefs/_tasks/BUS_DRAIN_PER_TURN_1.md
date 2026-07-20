# BUS_DRAIN_PER_TURN_1 — mid-session bus drain on every Director prompt

**Owner:** deputy-codex · **Dispatcher:** lead · **Date:** 2026-07-20
**Class:** hook/infra (forge-canonical) · **Repo:** baker-master

## Context

**Context Contract:** read `tests/fixtures/session-start-bus-drain.sh` (drain
core + V0.3 rendered-ledger contract), `~/.claude/hooks/stop-bus-ack.sh`
(ack-only-rendered), `scripts/install_forge_agent.sh` (BUS_HOOKS wiring +
settings blocks), `tests/test_install_forge_agent.sh`. Nothing else needed.
**Task class:** local-mechanical (hook script + installer wiring; no server,
no DB, no UI). **Done-state class:** deterministic — acceptance script.
**Gate plan:** codex exact-HEAD gate on cumulative diff before merge; live AC
on the lead seat post-deploy (mid-session render proof).

The wake pipeline (WAKE_DISPOSITION_REWAKE_1, live today) wakes idle seats
only — by design it never interrupts an active session. SessionStart drain
covers boot. The remaining hole is mid-session arrival.

## Problem (Director-observed, 2026-07-20 ~09:00Z)

The wake pipeline wakes IDLE seats. A seat mid-conversation with the Director
is never idle, so bus messages that arrive during an active session are
invisible until session restart — Director had to copy-paste 5 bus messages
into the lead terminal by hand this morning. Automation gap, not a wake bug:
`session-start-bus-drain.sh` fires only on SessionStart.

## Fix

New hook `turn-bus-drain.sh` registered on **UserPromptSubmit** (alongside the
SessionStart drain, same canonical-fixture pattern):

1. Reuse the drain core of `tests/fixtures/session-start-bus-drain.sh`
   (slug resolve, key resolve, since-cursor, rendered-ID ledger V0.3,
   curl --max-time 4, RENDER_CAP, never-block exit-0 contract).
2. **Cooldown:** skip silently if last drain < 60s ago (state file
   `~/.brisen-lab-bus-turn-drain-<slug>.txt`). Prevents burst cost when
   Director sends rapid messages.
3. Emit unread messages as additionalContext exactly like the SessionStart
   drain; append rendered ids to the SAME rendered ledger so `stop-bus-ack.sh`
   ack semantics stay single-source.
4. Shared since-cursor with the SessionStart drain (same state file) so
   messages are never rendered twice.
5. Factor the drain core into a shared sourced file if duplication exceeds
   ~30 lines; both hooks stay thin wrappers.

## Files Modified

- `tests/fixtures/turn-bus-drain.sh` — NEW (canonical hook).
- `tests/fixtures/bus-drain-core.sh` — NEW only if factoring (see Fix §5).
- `scripts/install_forge_agent.sh` — BUS_HOOKS array + UserPromptSubmit
  settings wiring.
- `tests/test_install_forge_agent.sh` — extend for the new hook row.
- NO changes to `session-start-bus-drain.sh` semantics beyond optional
  core-factoring; NO changes to `stop-bus-ack.sh`.

## Rollout

- Canonical: `tests/fixtures/turn-bus-drain.sh` (+ shared core if factored).
- Wire into `scripts/install_forge_agent.sh` BUS_HOOKS + UserPromptSubmit
  settings block; extend `tests/test_install_forge_agent.sh`.
- Fleet converge via normal forge install; drift check covers it for free.

## Verification

- `bash -n` on every touched script; `tests/test_install_forge_agent.sh` green.
- Literal-run proof: source the hook with a stubbed daemon URL → renders
  fixture messages; with cooldown state fresh → exits 0 silently, no curl.
- Live AC (post-deploy, lead seat): bus-post to lead mid-conversation → next
  prompt shows the message in additionalContext; verify id lands in rendered
  ledger and stop-bus-ack acks it.

## Quality Checkpoints / Acceptance criteria

1. Mid-session: post a bus message to a seat in active conversation → next
   Director prompt renders it as additionalContext (live proof on lead seat).
2. Cooldown: two prompts < 60s apart → second drain skips, no API call.
3. No double-render across SessionStart + turn drains (shared cursor).
4. Prompt latency added < 1s worst-case network-down (curl --max-time honored).
5. `bash -n` + install-test suite green; exit 0 on every failure path.

## Guardrails

- Never block or delay the prompt on bus failure — degrade silent.
- Ack stays rendered-only (V0.3 ledger) — no blind acks.
- Token budget: RENDER_CAP unchanged; cooldown is the cost control.
