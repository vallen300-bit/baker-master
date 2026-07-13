# B3 Ship Report — CASE_ONE_P3_CONTRACT_IDENTITY_1

- **Date:** 2026-07-13
- **Builder:** b3 (fresh successor seat, attempt:2 — claimed via checkpoint attempt-bump commit 196b0179)
- **Brief:** `briefs/BRIEF_CASE_ONE_P3_CONTRACT_IDENTITY_1.md` @39bba3e4 (deputy-authored, lead-PASS w/ 2 riders); dispatch lead #10023
- **PRs (must merge together):**
  - brisen-lab **#124** (server daemon) — branch `b3/case-one-p3-contract-identity-1`, commit `6669136`
  - baker-master **#545** (MCP fleet client) — branch `b3/case-one-p3-contract-identity-1`, commit `d162c77e`
- **Ship bus post:** #10028 → lead. b3 inbox: 0 unread.

## Done rubric (brief §Quality Checkpoints)

1. **Typed envelope validated at POST, garbage rejected with reason (E4)** ✅ — `bus.py` `_post_msg_inner` rejects empty / too-short execute-obligation bodies with a distinct 4xx + reason. Ships **dormant** behind `BRISEN_LAB_ENFORCE_BODY_MIN` (default off) — see transition note.
2. **Dedup keys on `id` ONLY, content-hash dedup removed (E20)** ✅ — dedup was already keyed on the P1 idempotency key `(from_terminal, idempotency_key)`, never on content. Confirmed the daemon **never had** content-hash dedup: `hashlib` was a dead import (removed). Envelope `id` is now the sole basis; identical body + new id → a second row (proven in test). Every post now carries a unique id (synthesized if absent), so genuinely-new posts never false-dedup.
3. **Claim-check + explicit truncation flag, full text first-class (E5)** ✅ — `truncated` flag on every row (preview clip distinguishable from complete); payload over `BRISEN_LAB_INLINE_MAX_BYTES` stashed in new `brisen_lab_artifact` table with an excerpt + `artifact_ref`; `GET /artifact/<ref>` returns full text; `?full=1` still returns inline full body.
4. **Execute-obligation typed + bus single assignment truth (E11/E13)** ⚠️ partial — typed `execute_obligation` field added to the authoritative bus row (derived from kind: dispatch/ratify_required ⇒ act-on-receipt). Physically retiring/read-only-ing the file-mirror is **behavioral (P4 scope)** — flagged, not done here.
5. **Server-derived identity, shared-key `daemon` stamp handled (E12)** ✅ — `source` stamped server-side from the authenticated key; client-supplied `source` hard-refused (400). Shared-key path mapped to `source=daemon` + `unattributed=true`; **staged kill** via `BRISEN_LAB_SHARED_KEY_KILL` (rider b).
6. **Live drill AC + `POST_DEPLOY_AC_VERDICT v1`** ⏳ — deferred to post-merge/post-deploy; deputy is bus-health owner for the live drill per gate plan.

## Two lead riders (both honored) + a 3rd transition gate

All three new hard requirements ship **DEFAULT-OFF** so nothing breaks mid-rollout:

- **(a) TRANSITION MODE (id requirement)** — a post without an id is accepted, id synthesized server-side + `legacy=true`. `BRISEN_LAB_REQUIRE_ENVELOPE_ID=true` flips a missing id to a hard 400 once every fleet client ships the id.
- **(b) STAGED shared-key kill** — shared key (`BRISEN_LAB_SHARED_KEY_SLUGS`, default `{daemon}`) → `daemon` + unattributed. `BRISEN_LAB_SHARED_KEY_KILL=true` flips to a hard 403 once every app-seat has a per-seat key.
- **(+) E4 body-floor** — `BRISEN_LAB_ENFORCE_BODY_MIN=true` to enforce; default off avoids rejecting the 113 existing short-body test posts + in-flight fleet traffic.

## Schema

Six columns (`source`, `execute_obligation`, `unattributed`, `legacy`, `truncated`, `artifact_ref`) + `brisen_lab_artifact` table, added via **catalog-guarded bootstrap ALTER** (mirrors the `idempotency_key` lock-avoidance pattern — steady-state boots take no ACCESS EXCLUSIVE lock; `IF NOT EXISTS` covers concurrent first-boot).

## Verification (literal)

- **15 new tests** (`tests/test_case_one_p3_contract_identity.py`) vs **real local Postgres** (isolated throwaway DB on local pg 5432 — shared Neon test DB avoided per concurrent-TRUNCATE hazard): **15 passed**.
- **Full brisen-lab suite: 27 failed / 526 passed / 1 skipped.** The 27 fail **identically on clean `main`** (checked by stashing my edits: clean main = 27 failed / 511 passed). They are pre-existing environmental failures (autowake / agent-identity vault-drift / wake-topic — cross-region latency, no CI). **0 regressions; +15 new green.**
- baker-master MCP change: compile-clean. The MCP consumer test can't collect locally (`mcp` module not installed — pre-existing env gap, unrelated).

## Gate plan

G1 self-verify (**done**) → G2 deputy cross-lane review + non-author test-run vs real pg → lead independent Claude-side review before merge (codex suspended per Director #9711) → lead merges **both** PRs → deploy → deputy verifies live as bus-health owner + folds metrics into P4 dashboard.

## Deploy notes (for lead at merge)

Both PRs deploy safe with **all gates default-off** (pure additive contract). Post-fleet-ship sequence: (1) confirm every client sends an id → flip `BRISEN_LAB_REQUIRE_ENVELOPE_ID`; (2) confirm every app-seat has a per-seat key → flip `BRISEN_LAB_SHARED_KEY_KILL`; (3) confirm posting patterns clear the floor → flip `BRISEN_LAB_ENFORCE_BODY_MIN`. `BRISEN_LAB_INLINE_MAX_BYTES` (default 256 KiB) tunes the claim-check threshold.
