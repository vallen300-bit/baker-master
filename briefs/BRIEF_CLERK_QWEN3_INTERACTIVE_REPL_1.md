---
brief_id: CLERK_QWEN3_INTERACTIVE_REPL_1
title: Make Clerk Qwen3 open as a plain-English REPL with real telemetry
to: b-code-tbd
from: deputy-codex
dispatched_by: lead
task_class: baker-master implementation plus Mac-local picker activation
harness_v2: applies
base_branch: main
branch: clerk-qwen3-interactive-repl
depends_on:
  - briefs/BRIEF_CLERK_WORKBENCH_1.md
  - briefs/BRIEF_CLERK_WORKBENCH_2.md
  - briefs/BRIEF_CLERK_WORKBENCH_3.md
  - briefs/BRIEF_CLERK_QWEN3_BUS_AGENT.md
---

# BRIEF: CLERK_QWEN3_INTERACTIVE_REPL_1

## Context

The Qwen3 Clerk terminal client exists, but opening the "Clerk Qwen3" picker still
lands the Director in a shell-oriented workflow. The current CLI requires a
subcommand: `build_parser()` sets `required=True` for subparsers
(`clerk_qwen.py:226-237`), and the useful path is still
`clerkqwen run "..." --wait` (`clerk_qwen.py:188-198`).

Director-requested change, 2026-06-07: the picker should behave like an agent
seat. The Director types plain English directly; Clerk already knows its
identity, reach, limits, and Baker API access.

Amendment #2110: the footer must show real telemetry, not a decorative mimic of
the Claude Code footer. Figures must come from the Qwen3/OpenRouter response or
show `n/a` field-by-field.

## Problem

The Director typed plain English into the current "Clerk Qwen3" terminal and zsh
treated the words as shell commands. That is a UX failure: a document clerk
picker should open into a task prompt, not into a raw shell that requires
remembering `run`, quotes, and `--wait`.

The first dispatch asked for a status footer using cost or token data. The
amendment makes this stricter: the footer must expose actual model usage and
context-window fill. No constants, guesses, or fake meters.

## API / Schema Checks

- **Baker endpoints:** existing client targets `POST /api/clerk/run`,
  `GET /api/clerk/session/{id}`, and `GET /api/clerk/sessions`
  (`clerk_qwen.py:83-90`). Reuse these; do not add a new endpoint.
- **OpenRouter / Qwen3 endpoint:** existing runtime uses OpenAI-compatible
  `/chat/completions` (`orchestrator/clerk_runtime.py:291-296`).
- **OpenRouter docs checked 2026-06-07:** usage accounting is now returned in
  the `usage` object automatically. The older request parameter
  `usage: {"include": true}` is deprecated/no-op. Therefore, parse the returned
  `usage` object; do not make the feature depend on that flag.
- **Live DB schema verified 2026-06-07:** `clerk_sessions` currently has only
  `session_id`, `task`, `status`, `result_json`, `draft_content`, `draft_path`,
  `source_meta`, `error`, `created_at`, `updated_at`. Add a new migration; do
  not edit applied migration `migrations/20260606_clerk_sessions.sql`.
- **Bootstrap check:** `rg clerk_sessions` shows the table is created only by
  `migrations/20260606_clerk_sessions.sql`; there is no separate
  `store_back.py` bootstrap to update.

## Context Contract

- **Task class:** small production implementation, Baker repo plus Mac-local
  picker activation after merge.
- **Surface contract:** add an interactive terminal mode to `clerk_qwen.py`; no
  new dashboard page and no brisen-lab server change.
- **Runtime contract:** minimal read-only telemetry addition to
  `orchestrator/clerk_runtime.py` is in scope. Denylist, guardrails,
  tool registry permissions, draft-gating, and escalation policy remain
  unchanged.
- **Data contract:** add nullable telemetry columns to `clerk_sessions` and
  expose them through the existing `GET /api/clerk/session/{id}` response.
- **No-access-widening contract:** do not add Todoist, ClickUp, Calendar,
  WhatsApp, Slack, production, money, or send tools.
- **Fault-tolerance contract:** all HTTP errors in the REPL print a clean error
  and return to the prompt. DB paths retain try/except plus rollback.
- **Telemetry honesty contract:** if any telemetry field is missing, print `n/a`
  for that field only. Never fabricate a cost, token count, context maximum, or
  context percentage.

## Scope

### 1. CLI REPL mode

Modify `clerk_qwen.py`:

- Add subcommand `chat`.
- Make bare `clerkqwen` with no args enter `chat`.
- Keep `run`, `status`, `list`, and `url` backward-compatible.
- On entry print a short identity banner:
  - Clerk is Brisen's document clerk on Qwen3-Coder.
  - Reach: Gmail, Outlook/Graph, Dropbox, Baker Clerk workbench, internal bus.
  - Limits: no money, no external sends, no production changes; risky actions
    return drafts or `pending_approval`.
- Prompt loop:
  - Read one plain-English line.
  - Empty line, Ctrl-D, `exit`, or `quit` exits cleanly.
  - For any other line, call existing `ClerkQwenClient.run(task)`.
  - Poll the returned `session_id` via existing `_wait_for_terminal()`
    (`clerk_qwen.py:174-185`) until the session leaves `running`.
  - Print the same useful result details as `_print_session()`
    (`clerk_qwen.py:139-158`).
  - Print the telemetry footer after the result.
- Do not require quotes or the `run` wrapper inside the loop.
- Catch `ClerkQwenError`, `KeyboardInterrupt`, and malformed payloads per turn;
  the loop must continue unless the user exits.

Implementation note: factor shared run-and-wait logic out of `cmd_run()` so the
REPL and `run --wait` cannot drift.

### 2. Real Qwen3/OpenRouter telemetry

Modify `orchestrator/clerk_runtime.py`:

- Extend `_Usage` / `_ToolResponse` (`orchestrator/clerk_runtime.py:74-90`) to
  carry:
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`
  - `cost`
- In `_QwenMessages.create()` parse `data["usage"]` after `resp.json()`
  (`orchestrator/clerk_runtime.py:298-326`):
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`
  - `cost`
- Do not hardcode model prices.
- If `usage.cost` is absent, compute `session_cost_usd` only when configured
  prices exist in config/env. If prices are absent, leave cost as `None` so the
  CLI renders `n/a`.
- Preserve existing `input_tokens` / `output_tokens` aliases where practical,
  because current tests and cost logging use them (`tests/test_clerk_runtime.py:98`,
  `orchestrator/clerk_runtime.py:731-734`).
- In `ClerkAgent.run()` (`orchestrator/clerk_runtime.py:694-787`), accumulate:
  - total prompt tokens across Qwen3 turns
  - total completion tokens across Qwen3 turns
  - total tokens across Qwen3 turns
  - largest single-request prompt token count as `context_window_used`
  - configured context max as `context_window_max`
  - summed session cost as `session_cost_usd` when known
- Return those values in the result under `usage` without removing the current
  result status/tool-call behavior.

Config addition:

- Add nullable or zero-default config fields to `Qwen3Config`
  (`config/settings.py:73-88`):
  - `context_window_max` from `CLERK_QWEN_CONTEXT_WINDOW_MAX`
  - `prompt_price_per_m` from `CLERK_QWEN_PROMPT_PRICE_PER_M`
  - `completion_price_per_m` from `CLERK_QWEN_COMPLETION_PRICE_PER_M`
- Cost computation is allowed only when both price fields are present and
  positive. Otherwise cost remains unknown.

### 3. Persist and expose session telemetry

Add a new migration, for example `migrations/20260607_clerk_session_usage.sql`:

```sql
ALTER TABLE clerk_sessions
    ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS completion_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS total_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS context_window_used INTEGER,
    ADD COLUMN IF NOT EXISTS context_window_max INTEGER,
    ADD COLUMN IF NOT EXISTS session_cost_usd NUMERIC(12, 8);
```

Modify `outputs/dashboard.py`:

- Include the new columns in `_clerk_fetch_session()`
  (`outputs/dashboard.py:394-425`).
- Allow the new fields in `_clerk_update_session()`
  (`outputs/dashboard.py:427-472`).
- Extract telemetry from `result["usage"]` in `_clerk_run_session_sync()`
  (`outputs/dashboard.py:565-596`) and persist it with the session update.
- Include telemetry in `_clerk_public_session()` (`outputs/dashboard.py:501-517`)
  as top-level fields:
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`
  - `context_window_used`
  - `context_window_max`
  - `session_cost_usd`

Modify `orchestrator/clerk_bus_worker.py` too, because the headless Clerk bus
worker writes the same `clerk_sessions` rows:

- Include the new fields in `DirectClerkSessionStore.get_session()`
  (`orchestrator/clerk_bus_worker.py:154-173`).
- Allow the new fields in `DirectClerkSessionStore.update_session()`
  (`orchestrator/clerk_bus_worker.py:194-225`).

### 4. Footer rendering

In `clerk_qwen.py`, render the footer from the public session payload:

```text
Qwen3-Coder | ctx <used>/<max> (<pct>%) | <total_tokens> tok | $<session_cost_usd>
```

Rules:

- `used` = `context_window_used` from the session payload.
- `max` = `context_window_max` from the session payload.
- percentage = `used / max * 100`, only when both are positive numbers.
- tokens = `total_tokens`.
- cost = `session_cost_usd`.
- Print `n/a` for any missing field or uncomputable percentage.
- The footer must never show a made-up zero unless the API/config genuinely
  returned zero.

### 5. Picker activation

Mac-local activation is a post-merge step for AH1 unless AH1 explicitly folds it
into the implementation PR:

- `~/bm-clerk/clerk_qwen.py` is a copy of the canonical repo file and currently
  matches `bm-aihead1/clerk_qwen.py`. After merge, sync the updated file there.
- `~/.zshrc` currently defines `clerkqwen()` as a wrapper around
  `/Users/dimitry/bm-clerk/clerk_qwen.py` (`~/.zshrc:46-50`) and
  `clerkqwenterm()` as a banner that ends in `exec zsh -i` (`~/.zshrc:169-177`).
  Update `clerkqwenterm()` to land in `clerkqwen chat`, or make the Terminal
  profile command call `clerkqwen chat` directly.
- The persisted Terminal profile key currently visible in
  `com.apple.Terminal.plist` is `Clerk`, command `clerk`; the "Clerk Qwen3"
  string appears as window state, not an extractable profile key. Do not
  PlistBuddy-mutate blindly.
- If creating/updating a `.terminal` profile, use Terminal's import path
  (`open <profile>.terminal`) and verify Shell -> New Window shows the expected
  entry. This follows Lesson #96 on Terminal profile cache behavior.

## Files Modified

Expected repo files:

- `clerk_qwen.py` - add `chat` REPL, no-args default, footer formatting, tests hooks.
- `orchestrator/clerk_runtime.py` - parse and accumulate real usage/cost data.
- `config/settings.py` - Qwen3 context max and optional configured price fields.
- `outputs/dashboard.py` - persist and expose telemetry in Clerk session API.
- `orchestrator/clerk_bus_worker.py` - keep direct session store compatible.
- `migrations/20260607_clerk_session_usage.sql` - add telemetry columns.
- `tests/test_clerk_qwen_cli.py` - REPL line-to-run path and footer tests.
- `tests/test_clerk_runtime.py` - usage/cost parsing and accumulation tests.
- `tests/test_clerk_workbench_endpoints.py` - session API returns telemetry.
- `tests/test_clerk_bus_worker.py` - direct store allows telemetry fields if needed.

Expected local activation files after merge:

- `/Users/dimitry/bm-clerk/clerk_qwen.py`
- `/Users/dimitry/.zshrc`
- Terminal profile import artifact, if used.

## Acceptance Criteria

- **AC1** `clerkqwen chat` opens an identity banner and prompt; entering
  `find emails from Peter in my Outlook` sends that text as one task to
  `POST /api/clerk/run` without requiring quotes or `run`.
- **AC2** Bare `clerkqwen` with no args enters the same chat mode.
- **AC3** `clerkqwen run "..." --wait`, `list`, `status`, and `url` still work
  as before.
- **AC4** The banner states identity, reach, and limits.
- **AC5** Each task polls `GET /api/clerk/session/{id}` until the session is not
  `running`, then prints status, edit URL, draft path/reason when present.
- **AC6** The footer shows real context-window fill, token total, and session
  cost from session telemetry:
  `Qwen3-Coder | ctx <used>/<max> (<pct>%) | <total_tokens> tok | $<session_cost_usd>`.
- **AC7** If telemetry is absent, unavailable, or unconfigured, the footer prints
  `n/a` for that field only. No constants, decorative numbers, or guessed costs.
- **AC8** A test proves footer numbers come from a mocked API/session usage
  payload, not constants.
- **AC9** A runtime test proves OpenRouter-style `usage.cost` is parsed and
  accumulated; a second test proves fallback cost is computed only from configured
  prices.
- **AC10** `GET /api/clerk/session/{id}` returns the telemetry fields and remains
  auth-gated.
- **AC11** Opening the "Clerk Qwen3" Terminal picker lands directly in chat mode
  after AH1 local activation.
- **AC12** Existing denylist/guardrail/draft-gating behavior is unchanged.
- **AC13** Literal pytest green; no "pass by inspection".

## Verification

Run at minimum:

```bash
python3 -m py_compile clerk_qwen.py orchestrator/clerk_runtime.py outputs/dashboard.py orchestrator/clerk_bus_worker.py config/settings.py
/opt/homebrew/bin/python3.12 -m pytest -q tests/test_clerk_qwen_cli.py tests/test_clerk_runtime.py tests/test_clerk_workbench_endpoints.py tests/test_clerk_bus_worker.py
```

Manual smoke after merge/local activation:

```bash
clerkqwen chat
find emails from Peter in my Outlook
exit
```

Expected: the line becomes one Clerk task, the session reaches a terminal status,
and the footer shows real telemetry or `n/a` by field.

## Gate Plan

G0 deputy-codex self-check -> implementation PR -> G1 literal pytest ->
G2 security review for auth/telemetry/no-access-widening -> G3 codex
cross-vendor review -> AH1 merge -> AH1 local picker activation -> live picker
smoke.

## Done Rubric / Done-State Class

Done-state class: merge-ready implementation plus pending AH1 local activation.
The repo work is done when tests prove the REPL and telemetry contracts. The
feature is operationally done only after AH1 updates/imports the Terminal picker
and verifies the picker opens directly into chat mode.

## Do Not

- Do not add new Clerk tools or permissions.
- Do not touch money/send/prod-change guardrails except to preserve them.
- Do not fabricate cost, context, or token numbers.
- Do not edit applied migration `migrations/20260606_clerk_sessions.sql`.
- Do not mutate Terminal profiles by raw plist edits without import/menu
  verification.
- Do not replace the existing `run/status/list/url` commands.
