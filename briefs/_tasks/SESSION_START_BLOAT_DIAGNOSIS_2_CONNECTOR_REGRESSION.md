# BRIEF — SESSION_START_BLOAT_DIAGNOSIS_2_CONNECTOR_REGRESSION

**Author:** AH1 (lead)  ·  **Date:** 2026-07-04  ·  **Status:** DISPATCHED
**Task class:** diagnostic / instrumentation (NOT a fix brief)
**Harness-V2:** applies — Diagnose gate only (report artifact, no prod code)
**dispatched_by:** lead  ·  **reply-target:** bus → lead
**Recommended effort:** medium (history-derived measurement, no build)

---

## PROBLEM

AH1 session cold-open regressed to **~29% context consumed** (Director-observed 2026-07-04).
Post-SESSION_SLIM_IMPL baseline was ~6%. Delta ≈ 23pp of avoidable load.

Predecessor `BRIEF_SESSION_BLOAT_DIAGNOSIS_1` (2026-06-17) diagnosed the file-stack + skills-list
share and led to SESSION_SLIM_IMPL (shipped). The deterministic file stack is UNCHANGED (~14k tok).
The NEW variable since then: this AH1 session now runs connected to the claude.ai account, which
injects the full connector fleet into the deferred-tool list.

## CONFIRMED FINDINGS (AH1, 2026-07-04 — do not re-derive)

- Local MCP config is minimal and correct: `.mcp.json` → `baker` (http); global `~/.claude.json` → `chrome`. Nothing removable locally.
- Session deferred-tool list shows **~380 tool names**, including full duplication:
  - `mcp__baker__*` (60 tools) AND `mcp__claude_ai_baker__*` (60 tools) — exact duplicate set.
  - `mcp__chrome__*` (~30) AND `mcp__claude-in-chrome__*` (~30) — two browser stacks.
  - claude.ai connectors: ClickUp (~55), Gmail (12), Slack (19), Fireflies (20), Calendar (8), Drive (8), + auth stubs (Box, Linear, Notion, Todoist).
- Also new since June: skills list grew (many new plugin skills with long descriptions), agent-types list, and `wassenger` MCP server connecting.

## DIAGNOSE GATE — what to produce

Use the Phase-0 seam proven in brief _1: parse `~/.claude/projects/-Users-dimitry-bm-aihead1/*.jsonl`
session-start records (attachments, system-prompt lengths, hook outputs). NO fresh-session spawn unless
history is inconclusive — say so if it is.

1. **Token table by source** for a 2026-07-04 cold open: files / skills-list / agent-types / deferred-tool names / MCP instructions / SessionStart hooks / bus-drain. Compare against the June post-slim baseline session.
2. **Quantify the connector share specifically:** how many tokens do the ~380 deferred tool names + MCP server instructions cost? Split duplicated-baker / duplicated-chrome / claude.ai connector fleet / wassenger.
3. **Quantify skills-list growth:** June count vs today count, rendered tokens then vs now.
4. **Ranked cut list with yields:** for each cut, state the mechanism and the owner —
   (a) AH1-unilateral (local config/file edit), (b) Director-action (disconnect connector in claude.ai/Cowork app settings), (c) harness-level (not controllable). Estimate pp recovered per cut on the observed window.
5. **Window sanity check:** confirm whether the 29% reads against a 200k or 1M window (JSONL model/usage fields) — the pp math depends on it.

## DONE RUBRIC

- Report at `briefs/_reports/SESSION_START_BLOAT_DIAGNOSIS_2_REPORT.md` with the 5 items above.
- Every number sourced from JSONL evidence (quote the record), no estimates presented as measurements.
- Bus-post verdict + top-3 cuts to lead.

## CONSTRAINTS

- Read-only diagnosis. Do NOT edit skills, CLAUDE.md, hooks, or connector config.
- Do NOT touch `~/.claude/skills` (vault-symlinked, fleet-wide blast radius — brief _1 foot-gun).
- Budget: this is a medium-effort task; if JSONL seam fails, stop and report the seam failure rather than improvising instrumentation.
