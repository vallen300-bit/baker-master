# REPORT — SESSION_START_BLOAT_DIAGNOSIS_2_CONNECTOR_REGRESSION

**Author:** b2 · **Date:** 2026-07-04 · **Brief:** `briefs/_tasks/SESSION_START_BLOAT_DIAGNOSIS_2_CONNECTOR_REGRESSION.md`
**Task class:** diagnostic / instrumentation (Diagnose gate, read-only, no prod code)
**Seam:** parsed `~/.claude/projects/-Users-dimitry-bm-aihead1/*.jsonl` (82 sessions), assistant `message.usage` records.
**dispatched_by:** lead · reply-target: bus → lead

---

## BOTTOM LINE (overturns the brief's hypothesis)

The 6%→29% cold-open regression is **NOT token/connector bloat.** The cold-open token load is
**unchanged June→July (~57–65k tokens both).** The regression is a **context-window shrink from
1,000,000 → 200,000**, caused by the AH1 session running model **`claude-fable-5` (Fast mode)**
instead of **`claude-opus-4-8` with the 1M window**. Same ~57k of context, 5× smaller denominator
→ the meter jumps from ~6% to ~29%.

The connector fleet (~380 deferred-tool names, duplicated baker/chrome stacks, claude.ai connectors)
is real but it is **inside** that flat ~57–65k total and did **not** move the percentage. Cutting
connectors recovers only single-digit pp — and **only** while the window stays at 200k. Restoring the
1M window recovers the full ~23pp on its own.

**Window math (both exact):**
- 57,223 / 200,000 = **28.6% ≈ 29%** (July fable-5 cold open)
- 60,537 / 1,000,000 = **6.05% ≈ 6%** (June opus-4-8 cold open)
- Window ratio 1M : 200k = **5×**; observed 29 : 6 = **4.8×** ✓ consistent.

---

## ITEM 5 (answered first — it is the crux): 200k or 1M window?

**The 29% reads against a 200,000 window; the 6% baseline read against a 1,000,000 window.**
JSONL carries no explicit window/beta field, so the window is established from context-ceiling
behaviour (peak reached + auto-compaction), which is decisive:

| Model (as logged) | Sessions | Peak context reached | Ceiling behaviour | ⇒ Window |
|---|---|---|---|---|
| `claude-opus-4-8` | 59 | up to **503,794** (median peak 337k) | routinely blows past 200k | **1,000,000** |
| `claude-fable-5` | 19 | pure-fable 07-03/04 sessions cluster **≤185k** | auto-compacts at ~185k, never exceeds 200k | **200,000** |

Evidence quotes (raw `usage`):
- **July opus** `250d8ae5` first turn: `input 25083 + cache_creation 24972 + cache_read 15468 = 65,523`; model `claude-opus-4-8`; session **peak 417,296** (>200k ⇒ 1M active) ⇒ 65,523/1M = **6.6%**.
- **July fable** `f836c05d` first turn: `input 16271 + cache_creation 25489 + cache_read 15463 = 57,223`; model `claude-fable-5`; peak 84,644 ⇒ 57,223/200k = **28.6%**.
- **July fable** `0fe1b4ce` (233 turns): climbed to **184,868** then **compacted to 74,809 at turn 206**; never exceeded 200k — the 200k-ceiling sawtooth signature.
- **June baseline** `7f601a9e` first turn: `= 60,537`; model `claude-opus-4-8`; peak **421,824** (>200k ⇒ 1M active) ⇒ 60,537/1M = **6.1%**.

`claude-fable-5` is (strong inference, not JSONL-proven) the **Fast-mode model ID**. Fast mode is
toggled with `/fast`; the harness note states it "uses Claude Opus" but the logged model ID is
`claude-fable-5` and — critically — it runs the **standard 200k window, without the `[1m]` context
beta**. That is the entire regression: Fast mode was on for the observed AH1 cold open.

---

## ITEM 1: Token table by source — MEASURED TOTAL + SEAM LIMITATION

**Measured (JSONL, cold-open total context = input + cache_creation + cache_read, first assistant turn):**

| Window | Session | Model | Cold-open tokens | Meter % |
|---|---|---|---|---|
| June baseline | `7f601a9e` (06-22) | opus-4-8 (1M) | **60,537** | 6.1% |
| June baseline | `aca88f99` (06-20) | opus-4-8 (1M) | 60,471 | 6.0% |
| July | `250d8ae5` (07-04 08:57) | opus-4-8 (1M) | 65,523 | 6.6% |
| July | `f836c05d` (07-04 15:24) | **fable-5 (200k)** | 57,223 | **28.6%** |
| July | `0fe1b4ce` (07-04 12:31) | **fable-5 (200k)** | 56,915 | **28.5%** |

**The absolute cold-open load did not grow.** June opus ≈ 57–66k; July opus ≈ 65k; July fable ≈ 50–58k.

**Per-source split (files / skills-list / agent-types / deferred-tool names / MCP instructions /
hooks / bus-drain): NOT recoverable from JSONL — seam partial-failure (reported per brief, not
improvised around).** Claude Code does **not** persist the system prompt or the injected context
blocks (tool list, skills list, claudeMd, MCP instructions) in the transcript; only `usage` totals
and message bodies survive. The first user-message body in these sessions is 6–245 chars — the big
blocks live in the un-persisted system prompt. So the exact by-source breakdown the brief asked for
in items 1/2/3 cannot be quoted from JSONL evidence. The **total** (above) can, and it is the number
that determines the regression — and it is flat.

---

## ITEM 2: Connector-fleet share — ESTIMATE ONLY (labelled), and immaterial to the regression

Because JSONL does not persist the tool list, an exact token cost cannot be measured from it. From the
current deferred-tool inventory (the ~380 names visible in-session — an **estimate**, not a JSONL
measurement): the tool **names** are cheap (schemas are deferred/not loaded), on the order of a few k
tokens; the heavier cost is the per-connector **MCP server instructions** blocks. Duplicated sets are
real: `mcp__baker__*` (60) is exactly mirrored by `mcp__claude_ai_baker__*` (60); `mcp__chrome__*`
(~30) is mirrored by `mcp__claude-in-chrome__*` (~30); plus claude.ai connectors (ClickUp ~55, Fireflies
20, Slack 19, Gmail 12, Calendar 8, Drive 8, + Box/Linear/Notion/Todoist auth stubs) and a `wassenger`
server. **Whatever this sums to, it is inside the flat ~57–65k total and did not change June→July** —
so it is not the cause of the pp regression. It only matters as an absolute-load cut **if the window
stays at 200k** (see cuts 2–3).

---

## ITEM 3: Skills-list growth — real, but immaterial to the regression

The skills list did grow since June (many new plugin skills with long descriptions). Same seam
limitation: the rendered token cost is in the un-persisted system prompt, so an exact then-vs-now token
count is not JSONL-quotable. It is part of the flat ~57–65k absolute load and, like the connectors,
did **not** drive the percentage regression (the total didn't move; the denominator did).

---

## ITEM 4: Ranked cut list (mechanism + owner + yield on the observed window)

1. **Restore the 1M window on AH1 — turn Fast mode OFF for AH1 (or run `claude-opus-4-8[1m]`).**
   Mechanism: AH1 session drops `claude-fable-5`/200k, returns to opus-4-8/1M. Owner: **(b) Director-action**
   (`/fast` off) — or **(c) harness-level** if Fast mode should carry the `[1m]` beta.
   Yield: **29% → ~6%, ≈ 23pp recovered.** This is the whole regression. Not a "cut" — a denominator restore.
   Tradeoff: loses Fast-mode output speed. This is the real decision — speed vs 1M window.

2. *(Only if Fast/200k must stay)* **Drop the duplicate connector stacks.** Disconnect the claude.ai
   `baker` connector (60 dup tools of local `mcp__baker__*`) and one browser stack (`mcp__claude-in-chrome__*`
   ~30, dup of local `mcp__chrome__*`). Owner: **(b) Director-action** (disconnect in claude.ai / Cowork
   app settings). Yield: single-digit pp of a 200k window (estimate); **~0pp under 1M.**

3. *(Only if Fast/200k must stay)* **Disconnect unused claude.ai connectors** (ClickUp, Fireflies, Slack,
   Gmail, Calendar, Drive, Box, Linear, Notion, Todoist, wassenger). Owner: **(b) Director-action**.
   Yield: a few pp of a 200k window (estimate); **~0pp under 1M.**

**Cuts 2–3 are rounding error unless the 1M window is unavailable. The only high-yield lever is #1.**

---

## CONSTRAINTS HONOURED

Read-only diagnosis. No edits to skills, CLAUDE.md, hooks, or connector config. Did not touch
`~/.claude/skills`. No fresh-session spawn (history was conclusive). Per-source split seam-failure
reported rather than improvised.
