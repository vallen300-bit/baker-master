PENDING — BRISEN_LAB_1 dispatch 2026-05-01 by AI Head A. Reactivates dormant b5.

## Brief

`briefs/BRIEF_BRISEN_LAB_1.md` (1384 lines, Director-ratified 2026-04-30, two architect-review passes, READY).

Brisen Lab = separate Render service (`brisen-lab.onrender.com`) — observe-only dashboard for the 6 Claude Code terminals (Lead, Deputy, B1–B4). Hub-and-spoke layout, JSONL-tailing daemon on MacBook, structured event SSE stream. NOT a Cortex matter — engineering observability, parallel to Cortex, not part of it.

## Build target

New repo `vallen300-bit/brisen-lab` (NOT this repo). All Brisen Lab code lives there. The only edits to this repo (`baker-master`) are 4 `.claude/settings.json` files getting a `SessionStart` hook entry (Part 3 of the brief).

## Prerequisites — Director-side, blocking deploy

These must be in place before B5 can complete Part 1 (Render service deploy):

1. **GitHub repo** `vallen300-bit/brisen-lab` created (empty / one-commit init).
2. **Render Web Service** created — Starter $7/mo, name `brisen-lab`, auto-deploy from `main`, connected to the new GitHub repo.
3. **Render env vars** set: `DATABASE_URL` (same Neon DSN baker-master uses) + `FORGE_KEY` (Director-generated, e.g. `openssl rand -hex 32`).

If any prerequisite is missing when B5 starts: B5 should still build Parts 1, 2, 4 *locally* (in `~/bm-b5` clone of `baker-master` for hooks edits, and a fresh clone of `brisen-lab` repo as soon as it exists) and pause Part 1 deploy verification until provisioning lands. Director will signal when ready.

## Build sequence (per brief §Deployment order — DO NOT parallelize)

1. **Part 1** — `brisen-lab` repo: FastAPI app + Postgres `forge_*` schema. Verify `/healthz` + `\dt forge_*`.
2. **Part 2** — MacBook daemon `~/forge-agent/`: launchd plist + JSONL tailer + worktree poller. Verify snapshots in `forge_snapshots`.
3. **Part 4** — Frontend (`static/index.html` + `app.js` + `styles.css`): hub-and-spoke layout, vanilla DOM construction, NO `innerHTML`. Verify cards render with snapshot data.
4. **Part 3 LAST** — `~/.zshrc` updates + SessionStart hook + `.claude/settings.json` edits across 5 worktrees (`~/Desktop/baker-code` + `~/bm-b1..b4`). Verify events flow from real Claude sessions.

Each part has a verifiable checkpoint and clean rollback. Stop and report blockers if any verification step fails — do NOT carry forward.

## Hard constraints (from brief §Hard rules + lessons.md)

- **`baker-master` repo is mostly OFF-LIMITS.** B5 only edits the 4 `.claude/settings.json` files in `~/Desktop/baker-code`, `~/bm-b1`, `~/bm-b2`, `~/bm-b3`, `~/bm-b4` to add the SessionStart hook entry. PRESERVE existing PostToolUse + PreToolUse hooks in those files.
- **`outputs/dashboard.py` — DO NOT TOUCH.** Brisen Lab is a separate service; baker-master's dashboard is unaffected.
- **No `innerHTML` writes anywhere in `app.js`.** Use `createElement` + `textContent` per brief Part 4 sample. QC #15 will grep-verify.
- **Two-layer secret scrubber MUST be in both `db.py` and `agent.py`** with all 11 patterns. QC #17 verifies via test prompt.
- **Connection pool with `maxconn=10` AND `asyncio.to_thread` wrapping every DB block** in `app.py`. QC #16 stress-tests.
- **Hook always exits 0** — never block `claude` from starting. Brief Part 3 sample is the contract; do not add `set -e` or remove the `|| true` guards.
- **Back up `~/.zshrc` before editing** (`cp ~/.zshrc ~/.zshrc.bak.$(date +%Y%m%d)`). Verify `grep -c "^function aihead1" ~/.zshrc` returns exactly 1 BEFORE replacing.
- **Never put `FORGE_KEY` in any committed file.** Render env, launchd plist (local only, not committed), and `~/.zshrc` (local only) are the only allowed locations.

## Acceptance criteria — all 20 QC items in brief §Quality Checkpoints must pass

Brief lines starting with "✅" — 20 items. Each one verifies a specific behaviour. Treat as a contract.

## Reporting

After Part 4 verifies (Parts 1+2+4 deployable without Part 3), open PR(s) in `vallen300-bit/brisen-lab` for the brisen-lab code; for the baker-master `.claude/settings.json` edits, open ONE PR titled `feat(claude-code): SessionStart hook for Brisen Lab observation`. Tag AI Head A in PR body for review.

After ALL 20 QC items pass, post a completion report at `briefs/_reports/B5_brisen_lab_1_20260501.md` (mirror the format of existing `_reports/` files), then overwrite this file with `COMPLETE` plus a short summary referencing the report and the PR(s).

If genuinely blocked (Director provisioning incomplete after a reasonable wait, or an architectural concern not addressed in the brief): write a `BLOCKED` status here with the specific question for Director, then idle.

## Lessons.md surface

After deploy, append any new patterns to `~/Desktop/baker-code/tasks/lessons.md` (append-only). Especially: launchd quirks, JSONL parsing edge cases, `~/.zshrc` editing patterns. Do NOT rewrite or reorder existing lessons.
