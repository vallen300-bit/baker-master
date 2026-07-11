---
brief_id: ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1
status: SHIPPED
worker: b2
ship_date: 2026-05-31
baker_master_pr: 275
baker_vault_pr: 120
branch: b2/english-v1-cli-skill-invoke-refactor-1
reply_target: lead
revision: request-changes-resolved-2026-05-31
head_sha: 1e6290ea
---

# CODE_2_RETURN — ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1

## REQUEST_CHANGES resolved (2026-05-31, bus #1436 → reply #1439)

Lead requested changes on PR #275: `generator.py` hardcoded `MODEL_HIGH='claude-opus-4-7'` while main moved to `claude-opus-4-8` (PR #276, merge `f8a06826`).

- Rebased `b2/english-v1-cli-skill-invoke-refactor-1` onto `f8a06826` (opus-4-8 main). One conflict, in `generator.py` (docstring + model constant).
- Resolved: `MODEL_HIGH = os.environ.get("KBL_ANTHROPIC_MODEL", "claude-opus-4-8")` (env-overridable); compact docstring kept. `claimsmax/recharge_report/` clean of `opus-4-7`. No conflict markers.
- Amended the rebase commit, force-pushed-with-lease. **Remote HEAD now `1e6290ea`** (pre-commit WhatsApp guard passed).
- Re-verified: **24/24 pytest PASS** against vault PR #120 slot template, all 5 modules compile, singleton-guard PASS, `generator.py` = 130 lines (AC5 ≤130 ✓).
- PR #275 ready for re-review. Merge order unchanged: **vault PR #120 first, then master PR #275**.

> Test-env note: the default `python3` on this box is 3.9.6 (too old — fails on `int | None` PEP-604 syntax at import). Use **`python3.12`**. Also: local vault `main` carries a stray slot-less copy of the V3 template; tests must run with `BAKER_VAULT_PATH` pointed at the PR #120 vault checkout (worktree `/private/tmp/baker-vault-b2`).

---

ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1 shipped. Two PRs open, paired baker-vault PR ships first per brief Fix 6.

- **baker-master PR #275** — https://github.com/vallen300-bit/baker-master/pull/275
- **baker-vault PR #120** — https://github.com/vallen300-bit/baker-vault/pull/120
- **Branch** — `b2/english-v1-cli-skill-invoke-refactor-1` (same name on both repos)
- **Ship report** — `briefs/_reports/B2_ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1_SHIP_20260531.md`

## ACs verified locally (literal evidence in ship report + PR body)
- AC1 live Lohberger probe — 62.6s wall, first-pass validator clean, 16382 bytes
- AC2 structural parity vs V2 hand-rebuild — H2 set + visual primitive classes match
- AC3 V2 Lohberger validates clean
- AC4 spine.md edit propagates to system prompt (runtime read confirmed)
- AC5 generator.py = 129 lines (≤130), no hardcoded H2 names
- AC6 pytest 24/24 PASS in 0.22s
- AC7 all 4 modules compile clean
- AC8 singleton-guard CI PASS
- AC9 no requirements.txt change

## Two judgement calls surfaced for AH1 review
1. Total word lower bound 1200 → 1000 to honor AC3 (V2 has ~1145 body words; parser is accurate).
2. Strict tool-use mode dropped (Anthropic rejects `array minItems > 1`); Pydantic `extra=forbid` + `min/max_length` still block drift at `model_validate()`.

Full rationale in PR body + ship report.

## Recommended merge order
1. baker-vault PR #120 first (V3 template with slots — AC1 cannot pass without it).
2. baker-master PR #275 second.

Bus-posted lead.
