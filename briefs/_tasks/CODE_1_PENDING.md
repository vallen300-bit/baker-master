---
status: COMPLETE
brief: briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1.md
brief_id: CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1
target_repo: baker-master
working_dir: ~/bm-b1
working_branch: b1/cortex-director-card-v1-1-hotfix-gemini-json-1
matter_slug: baker-internal
cross_matter_usage: [all-matters — every Cortex cycle calls Phase 4.5]
dispatched_at: 2026-05-20T12:45:00Z
dispatched_by: lead
director_auth: 2026-05-20 chat — "Tier-A, I act" (AH1 dispatched without per-action ask per autonomy charter §3)
estimated_effort: ~30-45 builder-minutes
complexity: Low
priority: medium-high (100% Sonnet fallback rate = ~4-5x cost regression vs Haiku baseline; quality lift from Gemini swap deferred until shipped)
reply_target: lead (bus topic `ship/cortex-director-card-v1-1-hotfix-gemini-json-1`)
merge_closeout: |
  CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1 merged 2026-05-20 13:25:13Z — baker-master squash 9328e16 (PR #231).
  Gates cleared: AH1 static + 18/18 pytest + diff inspection (backward-compat default None confirmed; Sonnet path unchanged).
  No 2nd-pass / no /security-review — small hot-fix on already-cleared surface, no new attack vectors.
  Render auto-deploy fires; AH1 post-merge smoke on oskolkov pending to confirm Gemini-primary path active (assert _meta.model=gemini-2.5-pro + fallback_used=false; ZERO [phase4_5] warnings).
  Acked bus #601 same turn as mailbox flip.
---

# CODE_1_PENDING — CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1 — 2026-05-20

## What

Hot-fix the Gemini 2.5 Pro primary path in Phase 4.5 (PR #229, merged earlier today). Live smoke 30 minutes after deploy showed 100% Sonnet fallback rate because Gemini returns HTTP 200 with non-JSON body (no `response_mime_type` set in `gemini_client.generate()` + `_MAX_TOKENS=600` too tight for Gemini 2.5 Pro thinking-mode + parser doesn't strip trailing prose).

## Why you (B1)

You own the Phase 4.5 module (PR #229 + #226). You also pre-flighted the brief defect on the prior dispatch (signal_text column missing → proposal_text ILIKE substitution — exactly the kind of careful read this hot-fix needs).

## Brief

Full spec: `briefs/BRIEF_CORTEX_DIRECTOR_CARD_V1_1_HOTFIX_GEMINI_JSON_1.md` (read end-to-end before starting).

## Three-part fix (summary — full detail in the brief)

1. **`orchestrator/gemini_client.py`** — add optional `response_format: str = None` param to `generate()`. When set to `"json"`, build `GenerateContentConfig(response_mime_type="application/json", ...)`. Backward compatible — other callers (capability_runner, auto-insight) unaffected.
2. **`orchestrator/cortex_phase4_5_director_card.py`** — add `_MAX_TOKENS_GEMINI = 2000` constant (keep `_MAX_TOKENS = 600` for Sonnet); Gemini call passes the new max + `response_format="json"`. Rewrite `_parse_json_response` to brace-balance the JSON object (strips trailing prose in addition to existing leading-prose + fence handling).
3. **`tests/test_cortex_phase4_5_director_card.py`** — 3 new tests (trailing-prose, fenced+trailing-prose, parser unit test with `{` inside string value). Existing 15+ tests must still pass.

## Ship gate (literal)

- `pytest tests/test_cortex_phase4_5_director_card.py -v` — full output in PR description; no "by inspection".
- `python3.12 -c "import py_compile; py_compile.compile('orchestrator/gemini_client.py', doraise=True); py_compile.compile('orchestrator/cortex_phase4_5_director_card.py', doraise=True); print('compile OK')"` — must print `compile OK`.
- `bash scripts/check_singletons.sh` — OK.
- Pre-commit hook Parts 1-4 pass (Part 4 just shipped this morning — no `/env-vars` PUT in your diff, so no relevance).
- Diff inspection: `response_format` param has default `None` (backward compat); Sonnet fallback path's `max_tokens=_MAX_TOKENS` (600) unchanged.

## Post-merge AH1 smoke (not your responsibility — for your awareness)

After merge + deploy, AH1 fires another self_wake_smoke on oskolkov and confirms `payload->'_meta'->>'model' = 'gemini-2.5-pro'` + `fallback_used = false` on the resulting card. Render logs show ZERO `[phase4_5]` warnings in the cycle window.

## Reporting

On PR open, bus-post `lead` (per `dispatched_by: lead` above):

```bash
BAKER_ROLE=b1 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "ship/cortex-director-card-v1-1-hotfix-gemini-json-1 — PR #<N> open; pytest <X/X> green; gemini_client.generate gains response_format param + _MAX_TOKENS_GEMINI=2000 + brace-balanced parser. Backward compat preserved." \
  ship/cortex-director-card-v1-1-hotfix-gemini-json-1
```

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Heartbeat = (a) UPDATE entry in this mailbox file with ISO timestamp, OR (b) commit on working branch with `mailbox(b1): heartbeat <ISO> — <where>` pattern, OR (c) ship-report file write.

## Anchors

- PR #229 merge — `d9065ae`, 2026-05-20 12:26:38Z (your prior ship).
- Live smoke that exposed the bug — cycle `dceaf71b-ca6f-4496-9d74-e30e4a3f9656`, oskolkov self_wake_smoke, 12:37:23Z.
- Render log evidence: `[phase4_5] cycle dceaf71b...: gemini returned non-JSON; trying Sonnet fallback` at 12:37:15.820Z.
- Director ratification: 2026-05-20 chat "Tier-A, I act" — no per-action authorization needed.
