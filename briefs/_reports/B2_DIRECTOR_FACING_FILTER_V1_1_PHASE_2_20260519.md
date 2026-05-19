---
brief_id: DIRECTOR_FACING_FILTER_V1_1_PHASE_2
b_code: b2
brief: ~/baker-vault/_ops/briefs/director-facing-filter-v1_1.md
working_branch: b2/director-facing-filter-v1-1
status: SHIPPED
dispatched_at: 2026-05-19T17:48:00Z
dispatched_by: cowork-ah1
shipped_at: 2026-05-19T17:55:00Z
reply_target: cowork-ah1
ship_topic: ship/director-facing-filter-v1-1
---

# B2 ship report — DIRECTOR_FACING_FILTER_V1_1_PHASE_2

## Scope shipped

All 7 brief components:

1. `tests/fixtures/director-facing-filter/lib/call_validator.py` — Anthropic
   Haiku 4.5 validator wrapper. 1Password-fetched API key (cached per-process),
   3 s hard timeout, fail-safe degradation on every error path (op fail,
   ImportError, APITimeoutError, APIConnectionError, RateLimitError,
   APIStatusError 4xx/5xx, malformed JSON, invalid decision value) — all return
   PASS + diagnostic reason. Module-level skill prompt cache. `--self-test`
   mode for ship-gate smoke (verified live: 1P fetch OK, anthropic SDK OK,
   degrade-on-missing-skill OK).

2. `tests/fixtures/director-facing-filter/hooks/stakeholder-authority-trigger.sh`
   — Filter #1 Stop hook. Detects VIP (from
   `authority-profiles.yml`) + authority-asserting verb in same sentence;
   strips code fences (Phase 1 `\x60` pattern); caps 1 VIP/turn for cost
   bound; reentrancy-guarded; mode-aware (deliberate → block; light → append
   to `~/.claude/state/pending-annotations.json`).

3. `tests/fixtures/director-facing-filter/hooks/contract-gate-trigger.sh`
   — Filter #3 Stop hook. Detects ≥4 enumerated items + options-vocab
   nearby; inline-tag bypass (`tag_count >= len(items)`); evidence-file
   bypass with 5-minute freshness check + per-option allowed-tag validation
   on `~/.claude/state/feasibility-tags.json`; mode-aware (deliberate →
   block; light → annotate).

4. `tests/fixtures/director-facing-filter/skills/director-facing-filter-stakeholder-validator/SKILL.md`
   — system prompt + user template + 3 in-prompt examples
   (Rolf BLOCK, Rolf PASS, unknown VIP PASS).

5. `tests/fixtures/director-facing-filter/skills/director-facing-filter-contract-validator/SKILL.md`
   + `EVIDENCE_FILE_FORMAT.md` (Director-readable evidence-file schema doc).

6. `tests/fixtures/director-facing-filter/hooks/annotate-pending-checker.sh`
   — UserPromptSubmit hook. Reads pending file, emits
   `additionalContext` injection with up to 5 entries, clears file to `[]`.

7. **17 new fixtures** + extended pytest harness with mocked Anthropic SDK
   (via PYTHONPATH-prepended `lib_mock/anthropic.py` + a 2nd `lib_mock_no_sdk/`
   for ImportError path) + mocked `op` CLI shim. All 32 fixtures green
   (Phase 1's 15 unchanged + Phase 2's 17 new). Tests never reach the live
   Anthropic API.

Plus:
- `plugin.json` v1.1.0 — lists all 8 hooks, declares `python_env`
  + `secrets` deps.
- `scripts/update_user_settings.py` — adds 3 new hooks (1 UserPromptSubmit,
  2 Stop) to the same `matcher: "*"` entries for deterministic ordering;
  idempotent via path-normalized comparison (Phase 1 pattern).
- `scripts/deploy_to_user_global.sh` — stages `lib/` to `~/.claude/hooks/lib/`,
  validator `SKILL.md` files to `~/.claude/skills/`, runs `pip3 install --user
  --quiet anthropic pyyaml` (degrade-with-warn on failure).
- `.claude-plugin/README.md` — Phase 1+2 hook table, cost section, fail-safe
  contract, known limitations.

## Ship-gate evidence

### Ship-gate #1 — `pytest tests/test_director_facing_filter_v1.py -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b2
collected 32 items

tests/test_director_facing_filter_v1.py::test_fixture[fixture_path0] PASSED [  3%]
... (30 more, all PASSED) ...
tests/test_director_facing_filter_v1.py::test_fixture[fixture_path31] PASSED [100%]

============================== 32 passed in 6.97s ==============================
```

### Ship-gate #2 — `bash -n` on every hook

```
$ bash -n tests/fixtures/director-facing-filter/hooks/*.sh && echo OK
OK
```
All 8 hooks syntax-clean (5 Phase 1 untouched + 3 Phase 2 new).

### Ship-gate #3 — `python3 lib/call_validator.py --self-test`

```
call_validator self-test
  model: claude-haiku-4-5-20251001
  timeout: 3.0s
  1Password fetch: OK (key starts with sk-ant-api03-S...)
  anthropic SDK import: OK
  degrade-on-missing-skill: OK
```

### Ship-gate #4 — plugin.json v1.1.0 parseable + 8 hooks listed

```
version: 1.1.0
hooks count: 8
  UserPromptSubmit hooks/strategic-mode-router.sh
  UserPromptSubmit hooks/authority-profile-preload.sh
  UserPromptSubmit hooks/pre-send-checklist.sh
  UserPromptSubmit hooks/annotate-pending-checker.sh
  Stop hooks/synthesis-vs-taxonomy.sh
  Stop hooks/standing-rules-scan.sh
  Stop hooks/stakeholder-authority-trigger.sh
  Stop hooks/contract-gate-trigger.sh
```

### Ship-gate #5 — T1 (Rolf authority) BLOCK in deliberate

Fixture `filter1_t1_rolf_co_owns_deliberate.json` exercises the canonical
MOVIE Desk T1 scenario (Rolf=standing-consult-monthly + assistant asserts
"Rolf operationally co-owns the F&B problem"). Mock validator returns
`{"decision":"block","reason":"..."}`. Harness asserts stdout contains
`"decision": "block"`. PASSED.

### Ship-gate #6 — multi-block path on T2

T2 (M1–M5 menu, untagged) was already blocked by Filter #2 (Phase 1's
`filter2_clean_menu_blocked.json` covers synthesis-vs-taxonomy) and Filter
#4 (`filter4_r1_m1_block.json` covers standing-rules-scan abbreviation).
Phase 2 adds `filter3_t2_m1m5_block_deliberate.json` for Filter #3
(contract-gate). All three independently fire; the existing T2 fixture
remains unchanged.

### Ship-gate #7 — mode degradation

`filter1_light_mode_t1.json` and `filter3_light_mode_t2.json` cover the
light-mode path: validator returns BLOCK, mode=light → no stdout block;
harness asserts `pending-annotations.json` contains the expected `filter`
entry.

### Ship-gate #8 — validator degradation

`lib_validate_timeout.json` (APITimeoutError), `lib_validate_malformed_json.json`
(non-JSON model response), `lib_validate_op_fail.json` (mocked op CLI fails)
— all three assert no block emitted (PASS-with-reason path).

### Ship-gate #9 — `/security-review`

Gate-4 in the dispatch chain. Awaiting AH1 + AH2 review per gate_chain in
mailbox.

### Ship-gate #10 — live smoke

Requires deploy to `~/.claude/hooks/` (deferred to gate chain). Will run
post-merge on Director's Mac per brief §Reporting.

## Files

**New (baker-master, 25 files):**
- `tests/fixtures/director-facing-filter/lib/call_validator.py`
- `tests/fixtures/director-facing-filter/lib/__init__.py`
- `tests/fixtures/director-facing-filter/lib_mock/anthropic.py`
- `tests/fixtures/director-facing-filter/lib_mock_no_sdk/anthropic.py`
- `tests/fixtures/director-facing-filter/hooks/stakeholder-authority-trigger.sh`
- `tests/fixtures/director-facing-filter/hooks/contract-gate-trigger.sh`
- `tests/fixtures/director-facing-filter/hooks/annotate-pending-checker.sh`
- `tests/fixtures/director-facing-filter/skills/director-facing-filter-stakeholder-validator/SKILL.md`
- `tests/fixtures/director-facing-filter/skills/director-facing-filter-contract-validator/SKILL.md`
- `tests/fixtures/director-facing-filter/skills/director-facing-filter-contract-validator/EVIDENCE_FILE_FORMAT.md`
- 12 new fixtures: `filter1_*.json` (7), `filter3_*.json` (5), `lib_validate_*.json` (3),
  `annotate_pending_*.json` (2) — 17 total

**Modified (baker-master, 4 files):**
- `tests/fixtures/director-facing-filter/.claude-plugin/plugin.json` (1.0.0 → 1.1.0)
- `tests/fixtures/director-facing-filter/.claude-plugin/README.md` (Phase 1 → 1+2)
- `tests/fixtures/director-facing-filter/scripts/update_user_settings.py`
- `tests/fixtures/director-facing-filter/scripts/deploy_to_user_global.sh`
- `tests/test_director_facing_filter_v1.py` (mock staging, Phase 2 fixture support)

**Vault PR:** none. Phase 2 is a pure consumer of Phase 1's
`_ops/people/authority-profiles.yml`.

## Lessons applied (from Phase 1)

1. **Backticks inside heredoc** — used `\x60` for code-fence stripping (the
   `synthesis-vs-taxonomy.sh` workaround for `$(...)` bash-parser confusion).
2. **Reentrancy guard** on every new Stop hook (Filter #1 + #3 triggers).
3. **`_find_or_create_matcher_entry()`** pattern used to bundle Phase 2 hooks
   into the same `matcher: "*"` entries so execution order is deterministic.
4. **Stress-fixture-first** — all 17 fixtures written + harness wired before
   the hook logic was tightened; first pytest run was 32/32 green.
5. **No "by inspection"** — literal pytest output above.

## Awaiting

Per `gate_chain` in mailbox:
- Gate 1 (static, deputy/AH2)
- Gate 2 (/security-review, AH1 — API-key handling especially)
- Gate 3 (cross-lane architecture, AH1 — cross-turn state file +
  first runtime Anthropic API call from hook layer + new SKILL.md runtime pattern)
- Gate 4 (2nd-pass code-reviewer, AH1)

Bus-post sent to `cowork-ah1` on PR open per `dispatched_by`.
