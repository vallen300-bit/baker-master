# CODE_2_PENDING — PROMPT_CACHE_AUDIT_1 B2 SECOND-PAIR REVIEW — 2026-04-24

**Dispatcher:** AI Head #2 (Team 2) — **cross-team** per Research Agent charter §6C Orchestration-mode
**Nature:** REVIEW (not build) — trigger-rule second-pair review
**Estimated time:** 25–40 min
**Working dir:** `~/bm-b2`
**Target:** PR #61 on branch `origin/prompt-cache-audit-1` (B1's build — B1-builder-reviewing-own-work gap fires, so B2 reviews)

---

## Why cross-team

Per the ratified B1 situational review trigger rule (`memory/feedback_ai_head_b1_review_triggers.md`), PR #61 fires **two** triggers:

- **§2.5 External API** — new `cache_control: {"type": "ephemeral"}` parameter on Anthropic `messages.create` at 3 hot sites (`outputs/dashboard.py` `/api/scan`, `orchestrator/capability_runner.py`, `baker_rag.py`). Changes the request payload shape passed to an external API; stable-prefix purity is a cache-poisoning / cross-call-leak risk surface.
- **§2.7 Cross-capability state writes** — new `kbl/cache_telemetry.py` emits `baker_actions` rows per call with `{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, call_site}`. Writes touch the audit table from 3 different call sites.

B1 built this PR. B1 can't second-pair-review their own work. Director dispatched B2 via AI Head #2 (this cross-team hop is covered by §6C Orchestration-mode — AI Heads self-coordinate the shared pool).

**Flow:** AI Head #2 runs `/security-review` in parallel with your review → merge on BOTH green.

---

## What you're reviewing

**Brief:** `briefs/BRIEF_PROMPT_CACHE_AUDIT_1.md` (what B1 was building — read only if the diff raises a question about intent)
**Ship report:** `briefs/_reports/B1_prompt_cache_audit_1_20260424.md` (what B1 shipped — B1's self-assertion of clean)

**Expected scope (7 files, per brief):**

| # | File | Kind | What to look for |
|---|------|------|------------------|
| 1 | `scripts/audit_prompt_cache.py` | NEW ~240 LOC | Static-analysis AST walker; stdlib-only; no network calls; output is markdown to stdout or `--out` file |
| 2 | `scripts/prompt_cache_hit_rate.py` | NEW ~110 LOC | Reads `baker_actions` JSONB; cost math round-trips; Slack alert only when <60% |
| 3 | `kbl/cache_telemetry.py` | NEW ~70 LOC | Fire-and-forget helper — never raises, never blocks, silent on DB failure |
| 4 | `tests/test_prompt_cache_audit.py` | NEW ~180 LOC, 8 tests | No live API calls (no `anthropic.Anthropic(...)` or `messages.create(...)` invocations) |
| 5 | `outputs/dashboard.py` `/api/scan` | ~15 LOC MODIFIED | `cache_control: {"type": "ephemeral"}` on stable system block + `log_cache_usage` wiring |
| 6 | `orchestrator/capability_runner.py` | ~15 LOC MODIFIED | Same pattern |
| 7 | `baker_rag.py` | ~15 LOC MODIFIED | Same pattern |

---

## Review method

```bash
cd ~/bm-b2
git fetch origin prompt-cache-audit-1
git stash -u -m "pause-for-cache-audit-review" 2>/dev/null  # you're idle, likely no-op

# Diff against main baseline
git diff --stat main...origin/prompt-cache-audit-1
git diff main...origin/prompt-cache-audit-1 | less
```

---

## §2.5 External API trigger — focus checks

**Stable-prefix purity** (cache poisoning / cross-call leak):

```bash
# At each of the 3 hot sites, the cache_control block must NOT include user-controlled data.
# User query, conversation history, retrieval context → MUST be in user message, NOT in system block.
git show origin/prompt-cache-audit-1:outputs/dashboard.py | grep -n -B2 -A30 "cache_control"
git show origin/prompt-cache-audit-1:orchestrator/capability_runner.py | grep -n -B2 -A30 "cache_control"
git show origin/prompt-cache-audit-1:baker_rag.py | grep -n -B2 -A30 "cache_control"
```

Confirm for each:
- `cache_control` block applied to a `system=[{"type":"text","text":"..."}]` element (or similar) — NOT to user message
- The text block it's attached to contains ONLY stable persona / rules / static context. No `{user_query}`, `{conversation_history}`, `{retrieved_context}`, `{current_date}`, `{capability_state}`, or any f-string interpolation of request-scope variables
- Dynamic content moved to user message position (not system)
- Cache-control structure matches Anthropic API spec: `{"type": "ephemeral"}` — no other type smuggled

**Model-ID invariant:**
```bash
# Model strings must be unchanged in these 3 hot sites. This PR is cache-only, NOT a 4.6→4.7 migration.
git diff main...origin/prompt-cache-audit-1 -- outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py | grep -E "claude-opus|claude-sonnet|model\s*="
# EXPECT: 0 lines changed on model= assignments
```

**Reference untouched:**
```bash
git diff --stat main...origin/prompt-cache-audit-1 -- kbl/anthropic_client.py
# EXPECT: empty (kbl/anthropic_client.py is the existing reference, per brief Do-Not-Touch)
```

---

## §2.7 Cross-capability state writes trigger — focus checks

**Fire-and-forget contract on `log_cache_usage`:**

```bash
git show origin/prompt-cache-audit-1:kbl/cache_telemetry.py
```

Confirm:
- Function wraps its entire body in `try: ... except Exception: ...` — no unhandled exception path
- `except` block logs at `WARN` (or lower) and returns None — does NOT re-raise
- No `raise` inside the function
- No blocking network call — `baker_actions` row write is local PG only, with `conn.rollback()` on failure
- Parameterized SQL — `INSERT INTO baker_actions (...) VALUES (%s, %s, ...)` — no f-string interpolation of call data
- `call_site` value comes from the caller as a literal string (e.g., `"dashboard_scan"`), not from request body

**Telemetry-silent-on-failure test exists:**
```bash
grep -n "silent_on_failure\|silent.*fail\|fire.?and.?forget" tests/test_prompt_cache_audit.py
# EXPECT: at least one test asserting log_cache_usage swallows exceptions
```

**No new API endpoint serving telemetry:**
```bash
git diff main...origin/prompt-cache-audit-1 -- outputs/dashboard.py | grep -E "@app\.(get|post|put|delete)"
# EXPECT: 0 lines (this PR is cache-only; it adds no new route)
```

---

## General correctness sanity

```bash
# No accidental baker-vault writes (brief explicitly excludes)
git diff --name-only main...origin/prompt-cache-audit-1 | grep -E "(^baker-vault/|~/baker-vault)"
# EXPECT: empty

# No CHANDA invariant file writes
git diff --name-only main...origin/prompt-cache-audit-1 | grep -E "CHANDA|chanda"
# EXPECT: empty

# Singleton check runs clean on the branch
git show origin/prompt-cache-audit-1:scripts/check_singletons.sh >/dev/null 2>&1 && echo "singleton script exists"

# No live API calls in tests
grep -nE "anthropic\.Anthropic\(|messages\.create\(" tests/test_prompt_cache_audit.py
# EXPECT: 0 matches (brief Non-negotiable)

# Audit script is stdlib-only (no third-party imports sneaking in)
git show origin/prompt-cache-audit-1:scripts/audit_prompt_cache.py | grep -E "^import |^from " | head -20
# EXPECT: only stdlib modules (ast, os, re, sys, json, argparse, pathlib, typing, dataclasses)
```

---

## Out of scope for this review

- Cache-hit-rate math in `prompt_cache_hit_rate.py` (not security-trigger-class; let AI Head's `/security-review` + B1's own tests cover it)
- Style / naming / comment density
- Performance of the audit script (it's a one-shot CLI)
- Coverage of non-top-3 sites (brief explicitly scopes to 3 hot sites — scope-creep out, not in)
- Full re-read of `BRIEF_PROMPT_CACHE_AUDIT_1.md` — only consult on specific intent questions

---

## Deliverable

Paste review verdict **as a PR #61 comment** (Director directive), then return here to AI Head #2 chat.

Format:

```
## B2 second-pair review — PROMPT_CACHE_AUDIT_1

Verdict: GREEN | FINDINGS

### §2.5 External API (cache_control on Anthropic calls)
- Stable-prefix purity at 3 hot sites: <confirmed | leak at file:line>
- cache_control structure {"type": "ephemeral"} only: <confirmed | other type at file:line>
- Dynamic content NOT in system block: <confirmed | interpolation at file:line>
- Model IDs unchanged: <confirmed | changed at file:line>

### §2.7 Cross-capability state writes (baker_actions telemetry)
- log_cache_usage fire-and-forget (try/except wraps body, no re-raise): <confirmed | raise path at file:line>
- Parameterized SQL on baker_actions INSERT: <confirmed | f-string at file:line>
- No new auth-gated route added: <confirmed | route at file:line>
- Telemetry-silent-on-failure test present: <confirmed | missing>

### Other findings
<none | list file:line + severity>

### PR comment link
<paste the PR comment URL once posted>
```

On GREEN → AI Head #2 merges once its `/security-review` also passes.
On FINDINGS → AI Head #2 routes fix-back to **B1** (implementation lane — B1 built it, B1 fixes it). B2 does not implement fixes for PRs B2 reviewed.

---

## After review — resume protocol

B2 mailbox was idle before this dispatch — no pre-review state to restore. After posting the PR #61 review comment, B2 is idle again until next dispatch lands.

Return this mailbox to `COMPLETE` state via §3 hygiene once the review comment is posted:

```bash
cd ~/bm-b2
printf 'COMPLETE — PR #61 PROMPT_CACHE_AUDIT_1 second-pair review posted <date> <time>\n\nB2 idle. Next dispatcher: run §2 busy-check.\n' > briefs/_tasks/CODE_2_PENDING.md
# Do NOT commit from B2 — AI Head #2 handles mailbox commits. Just write locally and ping.
```

Actually — **skip the local §3 rewrite; AI Head #2 owns mailbox-commit authority per charter §4.** Just post the PR comment and ping AI Head #2 in chat.

— AI Head #2
