# CODE_3_PENDING — BRIEF_AI_HEAD_WEEKLY_AUDIT_1 — 2026-04-22

**Dispatcher:** AI Head
**Working dir:** ~/bm-b3
**Brief:** briefs/BRIEF_AI_HEAD_WEEKLY_AUDIT_1.md (commit 1c276d7)
**Working branch:** feature/ai-head-weekly-audit-1
**Pre-requisites:** none (clean dispatch; no dependencies on in-flight work)

## Scope (5 files)

- `memory/store_back.py` — add `_ensure_ai_head_audits_table` + wire init call
- `outputs/slack_notifier.py` — add module-level `post_to_channel(channel_id, text)`
- `triggers/embedded_scheduler.py` — add `_ai_head_weekly_audit_job` + scheduler registration (Mon 9am UTC, env gate `AI_HEAD_AUDIT_ENABLED`)
- NEW `triggers/ai_head_audit.py` — audit logic module
- NEW `tests/test_ai_head_weekly_audit.py` — 6-test ship gate

## Ship gate (literal output required in CODE_3_RETURN.md)

```
pytest tests/test_ai_head_weekly_audit.py -v  # expect 6 passed
python3 -c "import py_compile; py_compile.compile('triggers/ai_head_audit.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/slack_notifier.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
```

**No "pass by inspection."** Paste the literal `pytest -v` output.

## Handoff

**Open PR when green.** B2 reviews. On APPROVE + green CI, AI Head merges (Tier A).

## Post-merge sequence (AI Head side)

1. After Render deploys, read logs for `Registered: ai_head_weekly_audit (Mon 09:00 UTC)` → capture APScheduler job ID (APScheduler job IDs are string-based; the registration uses `id="ai_head_weekly_audit"`) + compute next-fire timestamp (next Monday 09:00 UTC).
2. Record both in `_ops/agents/ai-head/OPERATING.md` "Verification" section.
3. Re-dispatch Step 10 to B4 with real trigger ID in sentence 2 of the DM body.
4. On B4 confirmation, append ARCHIVE 2026-04-22 session block, commit vault, close deploy.

## Timeline

Estimated: ~2-3h B3 implementation → B2 review 15-30 min → merge → Render deploy ~5 min → AI Head side 15 min → B4 DM ~5 min. Total ~3-4h window from dispatch.

---

**Dispatch timestamp:** 2026-04-22 (post-PR #43 merge)
