---
dispatch: CODEX_WAKE_ENTER_SUBMIT_1
to: b4
from: lead
dispatched_by: lead
dispatched_at: 2026-06-01
status: PENDING
repo: brisen-lab (NOT baker-master) — work in a brisen-lab clone, PR to brisen-lab main
canonical_brief: ~/Desktop/baker-code/briefs/BRIEF_CODEX_WAKE_ENTER_SUBMIT_1.md
complexity: Medium (~1.5h)
ship_target: bus topic ship/codex-wake-enter-submit-1 -> lead
---

# DISPATCH — codex card wake must auto-run, not wait for Enter (b4)

Read the canonical brief: `~/Desktop/baker-code/briefs/BRIEF_CODEX_WAKE_ENTER_SUBMIT_1.md`.

**One-line:** clicking the codex dashboard card injects `check bus` into codex's Terminal but the
text sits there until Director hits Enter — only codex (it runs the OpenAI `codex` TUI, not `claude`).

Fix `tools/wake-handler/wake-handler.applescript` (brisen-lab repo): (1) add codex to the alias
maps, (2) detect codex by its `codex` process not `claude`+cwd, (3) send an explicit Return
(`System Events key code 36`) so the codex TUI submits. Rebuild via `build.sh` + `lsregister -f`.

**Acceptance is LIVE** — no "by inspection". Launch a real codex session (`cdx`), click the codex
card, confirm the command auto-runs with no manual Enter; regression-check a Claude picker still works.

**Do NOT touch** `db.py` / `bus.py` (cowork-ah1 active) or the dashboard frontend.

Reply to `lead` via bus topic `ship/codex-wake-enter-submit-1`; note the exact submit mechanism + any new Automation grant. Do NOT commit/push until AH1 authorizes.
