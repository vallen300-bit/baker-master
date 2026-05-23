---
status: pending
brief: briefs/BRIEF_BACKFILL_SCRIPT_ENV_PREFLIGHT_1.md
brief_id: BACKFILL_SCRIPT_ENV_PREFLIGHT_1
target_repo: baker-master
matter_slug: baker-internal
dispatched_at: 2026-05-23T12:55:00Z
dispatched_by: lead
target: b1
working_branch: b1/backfill-script-env-preflight-1
reply_to: lead
deadline: 2026-05-24T18:00:00Z
priority: tier-b
---

# CODE_1_PENDING — BACKFILL_SCRIPT_ENV_PREFLIGHT_1 — 2026-05-23

**Brief:** `briefs/BRIEF_BACKFILL_SCRIPT_ENV_PREFLIGHT_1.md` (committed to baker-master `main` — PR #245 merged 2026-05-22; current HEAD `bf9e739`)
**Working branch:** `b1/backfill-script-env-preflight-1` (cut from baker-master `main`)
**Repo:** baker-master ONLY (`scripts/backfill_meeting_transcripts_matter_slug.py` + `scripts/backfill_matter_slug.py` + tests)
**Pre-requisites:** none — the brief is self-contained.

## Bottom line

Add `_check_required_env()` pre-flight at the top of `main()` in both backfill scripts, listing all required envs in ONE clear error before init touches anything. Director-ratified 2026-05-22 §X batch-ratification Group B item 24. ~1-2h.

Slot freed after RESEARCHER_VERIFY_CITATIONS_1 V0.2 merge (baker-vault PR #107 → `09bb1de`, 2026-05-23 12:31Z).

## Acceptance criteria

Full AC list in `briefs/BRIEF_BACKFILL_SCRIPT_ENV_PREFLIGHT_1.md` AC1-AC6. Summary:

- **AC1** Pre-flight at `main()` entry, before any class instantiation or DB connect.
- **AC2** Required env list: `VOYAGE_API_KEY` + (`DATABASE_URL` OR full `POSTGRES_*` split). Verify `POSTGRES_SSLMODE` requirement against current connect path before listing.
- **AC3** Single error report listing all missing envs (not one error per env).
- **AC4** Non-zero exit on missing envs; standard exit on env-present.
- **AC5** Tests: env-missing case + env-present case.
- **AC6** Same fix applied symmetrically to `scripts/backfill_matter_slug.py` (deadlines variant).

## Ship gate

- Literal `pytest tests/<env-preflight-test>.py -v` output in ship report. No "by inspection."
- `python3 scripts/backfill_meeting_transcripts_matter_slug.py --help` runs without env-related crash on a freshly-deployed environment (validates fast-fail behavior).
- Syntax check both scripts via `python3 -c "import py_compile; py_compile.compile('scripts/<name>.py', doraise=True)"`.

## Reporting

- Ship PR against baker-master `main` from branch `b1/backfill-script-env-preflight-1`.
- **Bus-post `lead` on PR open** with topic `ship/backfill-script-env-preflight-1` (`dispatched_by: lead` ⇒ ship-report to `lead`).

## Out of scope (Do NOT touch)

- Other one-off scripts that don't touch SentinelStoreBack — generalization is future-refactor candidate, NOT this brief.
- `outputs/dashboard.py` + other runtime-server code — different env loading path, different failure mode.
- `kbl/db.py` / `kbl/voyage_client.py` — pre-flight reads env, doesn't modify these helpers.
- Render env vars themselves — this brief only adds a check that runs on Render's existing env set; no env additions.
