# CHANDA Enforcement — engineering matrix

## §1. Purpose & audience

> This file is the operational complement to CHANDA.md. It translates the 5 missions into testable invariants with severity tiers and mechanical detectors. Every agent whose actions can trigger an invariant must read this at session start: Code agents (commit-time rules), runtime pipeline (loop-mechanics rules), surface handlers (user-facing safety rules). Research-agents may skip.

## §2. Severity tiers

| Tier | Behavior on breach | Audience |
|---|---|---|
| **critical** | Halt the operation; explicit unblock required | Director + AI Head, immediate |
| **warn** | Operation continues; breach surfaced in end-of-session report | Director end-of-session |
| **policy** | No runtime check; enforced at PR review | Code reviewer / AI Head |

Breach response is per-tier, not per-invariant. Predictable.

## §3. Detection methods

1. **Static check** (pre-commit hook, CI) — fails the PR. Best for file-structure invariants.
2. **Runtime assertion** — fails the operation. Best for pipeline-loop invariants.
3. **Infra-level enforcement** (credentials, permissions) — physically impossible to breach. Best for writer-isolation.
4. **Monitor + alert** (post-hoc) — detects after the fact. Best for rate/quota.
5. **PR review checklist** — human gate, last resort for genuinely architectural rules.

## §4. KBL invariants (11 rows)

| # | Invariant | Tier | Method | Detector |
|---|---|---|---|---|
| 1 | Gold read before Silver compile | critical | runtime assert | `assert gold_loaded == True` before compile |
| 1b | Cold-start (zero Gold) handling | critical | runtime gate | if `gold_count < N` → flag confidence-lowered; continue. N deferred. |
| 2 | Ledger write atomic with Director action | critical | runtime DB txn | wrap ratify + ledger in same transaction |
| 3 | Step 1 reads hot.md AND ledger every run | critical | runtime assert | log both file opens; verify at pipeline end |
| 4 | `author: director` files untouched by agents | critical | pre-commit hook | scan diff for frontmatter `author: director`; reject |
| 5 | Every wiki file has frontmatter | warn | static scan | quarantine un-frontmattered files; warn, don't halt |
| 6 | Pipeline never skips Step 6 (Cross-link) | critical | runtime assert | Step 6 counter check at pipeline end |
| 7 | Automated alerts are suggestions, never overrides | policy | architectural | alerts enter a queue; PR review checks no actuator path |
| 8 | Silver → Gold only by Director frontmatter edit | critical | runtime + git | pipeline refuses to write `voice: gold`; commit signer verified |
| 9 | Mac Mini single writer | critical | infra-level | Render has no push credentials for main vault repo |
| 10 | Pipeline prompts do not self-modify | policy | file permissions | prompt files read-only at runtime |

**Total:** 11 rows. 9 critical, 1 warn, 2 policy.
**Note on #5:** deliberately downgraded from original CHANDA (was critical) to avoid brittle-tripwire failure mode — one stale file with missing frontmatter should not halt the pipeline.

## §5. Surface invariants (5 rows — NEW)

| # | Invariant | Tier | Method |
|---|---|---|---|
| S1 | Baker never auto-sends to external recipients (drafts only) | critical | runtime: external flag on recipient → force draft mode |
| S2 | Every write to external systems logs to `baker_actions` atomically | critical | runtime DB txn |
| S3 | Kill switches respected (`BAKER_*_READONLY` env vars) | critical | runtime assertion at write-path entry |
| S4 | Rate caps enforced (max 10 writes/cycle/integration) | critical | runtime counter |
| S5 | Scan responses cite sources; no hallucinated citations | warn | post-response validator: grep citations against source IDs |

**Total:** 5 rows. 4 critical, 1 warn.

## §6. Detector script pointers

Detectors live under `/15_Baker_Master/01_build/invariant_checks/`.

**First build — top-3 critical (Director-approved 2026-04-21):**

| Invariant | Detector script | Method | Integration point |
|---|---|---|---|
| #2 Ledger atomicity | `invariant_checks/ledger_atomic.py` | runtime DB txn wrapper | all Director-action handlers |
| #4 Author:director files | `invariant_checks/author_director_guard.sh` | pre-commit hook | git hook + CI |
| #9 Mac Mini single writer | *(infra config — no script)* | Render deploy manifest: no push creds | Render dashboard + deploy YAML |

Remaining 13 detectors (KBL 1, 1b, 3, 5, 6, 7, 8, 10 + S1–S5) deferred to subsequent briefs after top-3 ship stably for 30 days.

## §7. Amendment log

Append-only. Every change to this file gets a row. Director signs via commit.

| Date | Section | Change | Director auth |
|---|---|---|---|
| 2026-04-21 | all | Initial creation from CHANDA rewrite session | "yes" (2026-04-21) |
