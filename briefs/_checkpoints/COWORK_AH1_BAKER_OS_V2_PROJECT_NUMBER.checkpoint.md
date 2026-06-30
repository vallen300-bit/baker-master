# CHECKPOINT — cowork-ah1 — Baker OS V2 project-number + 1Password fix

**Type:** Director-facing computer-use + Baker OS V2 build coordination. Rollover at ~103% context, 2026-06-30.
**Bus key:** cached at `scratchpad/.bus_key` (600). `export BRISEN_LAB_TERMINAL_KEY=$(cat <that>)` before any bus call — do NOT call `op` (see #2). Daemon `https://brisen-lab.onrender.com`; `GET/POST /msg/cowork-ah1`, ack `POST /msg/<id>/ack`.
**Repo state:** clone on stale branch `cowork-ah1/rollover-checkpoint-20260607`; live code = `origin/main` (d88abd8). Read live code via `git show origin/main:<path>` / `git grep <pat> origin/main`.

## TWO OPEN THREADS (top priority on respawn)

### 1. 1Password prompt — MID-ACTION, blocked on Director
- **Root cause (confirmed via Director screenshot):** the popup is the 1Password DESKTOP app authorizing the **"Claude" (Cowork) app** for CLI access ("Allow Claude to get CLI access", Brisen Capital SA). NOT a service-token call. It fires when `op` runs from the Claude app without the service token in that process.
- **Fix:** disable **1Password → Settings → Developer → "Integrate with 1Password CLI"**. Then `op` uses the service-account token (`OP_SERVICE_ACCOUNT_TOKEN`, set, reaches "Baker API Keys" + "Passwords") non-interactively → never prompts. Safe; re-enable if any secret fails to read.
- **DONE (2026-06-30):** Director unlocked; I unchecked **1Password → Settings → Developer → "Integrate with 1Password CLI"** via computer-use (confirmed unchecked via zoom). `op` now uses the service token non-interactively → no more "Allow Claude CLI access" prompts. If any agent's `op` later fails to read a secret, re-enable that checkbox. (Note: "Integrate with other apps", "MCP clients" left ON; only the CLI toggle changed.)
- Memory: `project_1password_prompt_open_diagnostic.md`. Lesson logged: verify `op` auth mode before claiming op behavior (I mis-diagnosed twice).

### 2. BRIEF_PROJECT_NUMBER_REGISTRY_1 — written, staged, dispatch requested
- **Brief:** `briefs/BRIEF_PROJECT_NUMBER_REGISTRY_1.md` (this clone) + staged shared at `~/baker-vault/_ops/briefs/BRIEF_PROJECT_NUMBER_REGISTRY_1.md` (322 lines).
- **What:** NEW `kbl/project_registry_store.py` — project-number registry. Format **`DESK-MATTER-###`** (e.g. `BB-AUK-001`), Director-ratified (codex #4679). One table `project_registry` (idempotent `CREATE TABLE IF NOT EXISTS`, mirrors `ensure_airport_ticket_table`) + 3 resolvers: `resolve_project_number` (hard lane) + `resolve_by_participant` + `resolve_by_alias` (soft-lane primitives, codex #4680). Validates matter_slug via `slug_registry.is_canonical`. + `tests/test_project_registry.py` (7 vertical live-PG). Additive, touches NO live code. Low / ~1.5h.
- **Guardrails (codex #4680, in brief):** number-alone never clears; fast-lane needs number AND (participant in manifest OR thread continuity); sender-only forbidden; soft-lane multi-signal logic lives in Box 5 (downstream, NOT this brief). Builder = a B-code (NOT Deputy/Codex).
- **State:** dispatch requested from `lead` = **bus #4681** (`dispatched_by: cowork-ah1`). **Awaiting lead to name the free B-code** (his dispatch lane; mailbox single-threaded). On respawn: poll bus for lead's reply; if he named a B-code, write `briefs/_tasks/CODE_<N>_PENDING.md` after clearing with lead, else let lead dispatch.
- **Confirm before non-pilot seed:** canonical Aukera/Annaberg slug (`slug_registry.canonical_slugs()`) + `DESK_CODES` values.

## DONE THIS SESSION (no action needed)
- PR #438 (ClickUpClient singleton, 3 sites + CI guard + regression test) — MERGED by lead, squash `8759e49` on main. Closed.
- Baker OS V2 live audit filed: `_ops/build/baker-os-v2/05_outputs/baker-os-v2-signal-journey-audit-cowork-ah1-20260630.md` (bus #4670).
- Box 5 second-pair review filed: `_ops/build/baker-os-v2/05_outputs/baker-os-v2-box5-second-pair-review-cowork-ah1-20260630.md` (bus #4676). codex locked 7 decisions (#4677). Fast-lane second-pair (#4678).
- Bus acked through #4680. My posts: #4670 #4676 #4678 #4681.

## REGISTER STYLE
Director-facing = laconic V2 (Bottom line / CAPS headers / numbered ≤12-word items / math / Recommendation if options / 👉 YOU or 🟢 GO? end-cue). Hooks enforce Recommendation + end-cue.
