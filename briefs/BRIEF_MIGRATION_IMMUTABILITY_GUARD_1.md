# BRIEF: MIGRATION_IMMUTABILITY_GUARD_1 — pre-commit hook + CI guard blocking edits to applied migrations

## Context

Real incident 2026-05-01 09:21Z–09:57Z. PR #127 added a 6-line comment block to `migrations/20260430_cortex_directives.sql` — a file that PR #125 had already applied to prod. Drift didn't fire on PR #127's deploy because of advisory-lock graceful-degrade (the new instance couldn't get the lock held by the old still-running instance, skipped migration check, came up clean). Bit us five days later when commit `f2ecb49` deploy got the lock, ran the check, hit `migration sha256 drift`, aborted. Blocked all subsequent deploys (`b2b6d81`, `9832c4e`) until Director-authorized `DELETE FROM schema_migrations`.

Lesson captured: `~/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/feedback_migration_file_immutability.md`. Hash mechanism: `config/migration_runner.py:92 _sha256()` hashes file bytes (not SQL semantics), compared against `schema_migrations.sha256` at startup; mismatch → `MigrationError` aborts process.

This brief ships **mechanical prevention** — the lesson alone won't catch a future inattentive comment-edit on an applied migration.

## Problem

Editing `migrations/*.sql` after apply silently passes local tests, silently passes review (the diff looks like a comment), then aborts deploys days later when the runner finally gets the advisory lock. Recovery is Director-only and high-friction.

Existing controls:
- `tasks/lessons.md` documents the rule (passive — relies on agent reading + remembering).
- Architect review on migration PRs (passive — relies on reviewer noticing).
- No mechanical block.

## Solution

Two-layer mechanical guard:

1. **`migrations/applied_migrations.lock`** — committed snapshot of prod's `schema_migrations` set: `filename + sha256`, one per line, sorted. Refreshed by a new script on every successful PR merge that introduces a migration. Lives in `migrations/` so its blast radius is migration-shaped.

2. **`scripts/check_applied_migrations.sh`** — re-validates that for every entry in `applied_migrations.lock`, the on-disk file's sha256 matches. Fails with a clear "migration X is applied; edits forbidden" message naming the recovery path. Wired as:
   - **Pre-commit hook** (`.githooks/pre-commit` + `git config core.hooksPath .githooks` documented in `CLAUDE.md`) — blocks the edit before it leaves the local machine.
   - **Render `start.sh` pre-flight** — fails the deploy *before* the migration runner runs, with a clearer error than `sha256 drift` (which hits *after* the bad bytes are already on the box).

Bypass: edit the lock file in the same commit + carry `Migration-edit-authorized: <reason>` trailer in the commit message. The hook checks for both. This documents Director consent in git history without an out-of-band approval channel.

## Files to create / modify

- `migrations/applied_migrations.lock` (new, committed) — initial seed = current prod `schema_migrations` snapshot.
- `scripts/check_applied_migrations.sh` (new, executable) — the validator. Returns 0 / non-zero.
- `scripts/refresh_applied_migrations_lock.py` (new) — pulls prod `schema_migrations` via `DATABASE_URL`, writes the lock file. Run by AI Head A after every migration-PR merge, manually for now.
- `.githooks/pre-commit` (new, executable) — calls `check_applied_migrations.sh`; if it fails AND no `Migration-edit-authorized:` trailer in the staged commit message → block.
- `start.sh` — add `bash scripts/check_applied_migrations.sh || exit 1` line *before* the existing migration-runner invocation.
- `CLAUDE.md` (Repo) — one-line addition under `## Hard rules — project-specific (don't do)`: "Edit applied migrations → blocked by pre-commit hook + start.sh check; bypass requires `Migration-edit-authorized:` trailer."
- `CLAUDE.md` (Repo) — under `## Session start`, add: "If pre-commit hook not installed: `git config core.hooksPath .githooks`."

## Acceptance criteria

1. Editing a single character in any file listed in `applied_migrations.lock` and running `git commit` — fails with the named error, names the recovery path, exits non-zero.
2. Editing the same file with `Migration-edit-authorized: doc-only comment add per Director 2026-05-XX` in the commit message — passes.
3. Adding a new migration file *not* in the lock file — passes (nothing to validate).
4. After merging the new migration to `main`, running `python scripts/refresh_applied_migrations_lock.py` against prod's DB and committing the result — lock file gains exactly one entry.
5. `bash start.sh` on a worktree where someone has hand-edited an applied migration — exits non-zero before the migration runner starts.
6. CI: no GitHub Actions in this repo; verification is manual (run the hook against a known-bad edit; confirm it fails). Document the test in the PR body.

## Out of scope

- GitHub-side branch protection / required-status-check (no Actions in this repo; would require setting one up).
- Auto-refresh of the lock file on deploy (deferred — manual refresh by AI Head A is fine for current cadence; revisit if migration cadence increases).
- Hashing semantic SQL content rather than file bytes (would dodge the comment-only case but adds parser complexity; not worth it for the incident frequency).
- Renaming `migration_runner.py`'s graceful-degrade-on-lock-miss behaviour (the latent failure mode that hid the original drift). That's a separate brief if we want it; this guard makes it irrelevant for the comment-edit case.

## Estimated time / complexity

- ~60 min Code Brisen build (3 small scripts + hook + start.sh edit + lock-file seed + CLAUDE.md notes).
- Low complexity. No DB writes. No deploy risk on its own (the start.sh check passes by definition on first deploy because the lock file is freshly seeded from prod).

## Lane

B1 (default lane, mailbox COMPLETE per handover). No worktree conflict.

## Prereqs

None — lesson is captured, incident is documented, mechanism (sha256 hashing) already exists in `config/migration_runner.py`.
