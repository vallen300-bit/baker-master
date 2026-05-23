---
status: pending
brief: briefs/BRIEF_SUBSTACK_NATE_INGEST_1.md
brief_id: SUBSTACK_NATE_INGEST_1
target_repo: baker-master
matter_slug: baker-internal
dispatched_at: 2026-05-23T13:20:00Z
dispatched_by: lead
target: b1
working_branch: b1/substack-nate-ingest-1
reply_to: lead
deadline: 2026-05-25T18:00:00Z
priority: tier-b
---

# CODE_1_PENDING — SUBSTACK_NATE_INGEST_1 — 2026-05-23

**Brief:** `briefs/BRIEF_SUBSTACK_NATE_INGEST_1.md` (committed to baker-master `main` @ `bf9e739`; pull before reading)
**Working branch:** `b1/substack-nate-ingest-1` (cut from baker-master `main`)
**Repo:** baker-master + `~/.claude/skills/aidennis-edge-scout/SKILL.md` (host-side skill edit, not committed)
**Pre-requisites:** none — brief is self-contained.

## Bottom line

Auto-ingest Nate's Substack posts from brisengroup Gmail into AID-T library, feed into existing aidennis-edge-scout Sunday digest. Director-ratified 2026-05-23: Q1 = Nate-only first, Q2 = markdown-only v1. ~3-4h. External-surface PR (Gmail trigger touch) — gate-4 code-reviewer 2nd-pass FIRES.

Previous mailbox BACKFILL_SCRIPT_ENV_PREFLIGHT_1 shipped — baker-master PR #247 squash-merged `440bac7` 2026-05-23 13:17Z.

## Acceptance criteria (full list — brief Quality Checkpoints 1-13)

See `briefs/BRIEF_SUBSTACK_NATE_INGEST_1.md` Quality Checkpoints section. Summary:

- New file `triggers/substack_ingest.py` with `is_substack_nate`, `ingest`, helpers
- `triggers/email_trigger.py` insert detector ABOVE existing `_should_skip_pipeline()` at line 978; add import at top
- `requirements.txt` add `html2text>=2024.2.26`
- New file `scripts/backfill_nate_substack.py` (30-day idempotent backfill — AH1 runs post-merge, NOT B-code)
- New file `tests/test_substack_ingest.py` (10 pytest tests minimum)
- Edit `~/.claude/skills/aidennis-edge-scout/SKILL.md` — 5th source row + 1 invocation-prompt sentence
- Substack ingest failures must NOT propagate (caller continues processing other emails)
- Idempotency: filename-derived (date + slug); re-running backfill is no-op
- sentinel_health integration (report_success + report_failure on source="substack_ingest")
- BAKER_VAULT_DISABLE_PUSH=false unchanged
- store.store_email_message() still called for Substack (Postgres searchability preserved)
- No external auto-sends; no DB migrations

## Ship gate

- Literal `pytest tests/test_substack_ingest.py -v` output in ship report. Paste in PR description. No "by inspection."
- Syntax check all 3 modified Python files: `python3 -c "import py_compile; py_compile.compile('triggers/substack_ingest.py', doraise=True); py_compile.compile('scripts/backfill_nate_substack.py', doraise=True); py_compile.compile('triggers/email_trigger.py', doraise=True)"`
- `bash scripts/check_singletons.sh` clear.

## Reporting

- Ship PR against baker-master `main` from branch `b1/substack-nate-ingest-1`.
- **Bus-post `lead` on PR open** with topic `ship/substack-nate-ingest-1` (`dispatched_by: lead` ⇒ ship-report to `lead`).
- Gate chain on PR open: AH1 static + `/security-review` (FIRES per §Security Review Protocol — touches Gmail external-surface) + feature-dev:code-reviewer 2nd-pass (FIRES per §Code-reviewer 2nd-pass Protocol trigger 4 — external-surface endpoints).

## Out of scope (Do NOT touch)

- `_SKIP_PIPELINE_SENDERS` blocklist — additive routing only, no removal
- `memory/store_back.py` — signature unchanged
- Other Substacks (Faster Please, Lenny, Product Growth) — out of scope per Q1 lock
- Qdrant / embedding pipeline — out of scope per Q2 lock
- `tasks/lessons.md` — append-only, separate brief
- `baker-vault/slugs.yml` — separate-repo PR only
- `outputs/dashboard.py` — no dashboard surface for v1
- Cortex pipeline / cortex_runner.py — Substack content not a matter, no matter_slug

## Important verification points

- Pre-commit grep-verify `thread` dict field names at `email_trigger.py:978` insertion site (brief Step 2 flagged: `headers` / `payload_headers` / `payload` / `message_id` / `received_date` are best-guesses).
- Pre-commit grep-verify `_build_gmail_service` helper exists in `scripts/extract_gmail.py` (brief Step 4 flagged: may have different name; use whatever exists, do NOT invent).
