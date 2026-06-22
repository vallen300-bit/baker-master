---
status: PENDING
brief_id: AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1
to: b2
from: lead
dispatched_by: lead
dispatched_at: 2026-06-22
reply_target: lead (bus)
task_class: auth hardening (baker-master: outputs/dashboard.py auth dep + outputs/ai_hotel_lab.py admin endpoint + tests)
arc: AI Hotel Lab Sprint-0 — partner-live unblocker (Director ruling 2026-06-22: hold partner-live until write-scope split)
gate_plan: G1 pytest -> G2 deputy-codex (privilege-escalation/scope-bypass) -> G3 deputy AC -> G4 lead /security-review -> merge -> deploy -> POST_DEPLOY_AC_VERDICT
harness_v2: applies
tier: B-adjacent (auth boundary) — gate-chain mandatory
---

# AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1 — split admin mutations behind a dedicated write scope

## Problem
Step 5.1 G4 surfaced a sub-threshold defense-in-depth gap (security-review, PR #412): the projection-admin
mutation endpoint `POST /api/admin/{action}` (approve/revoke/refresh) sits behind the SAME
`verify_ai_hotel_read_access` dependency (scope `ai-hotel:read`) as every read endpoint. A read-scoped token
can therefore drive the kill switch. Not a leak (revoke only *hides*), and the caller is already
Brisen-authenticated — but **Director ruled (2026-06-22) that Step 5 stays internal/view-as and does NOT go
partner-live until this is closed.** This brief is the named unblocker.

## Goal
Mutations require a strictly higher `ai-hotel:write` scope; reads keep `ai-hotel:read`. Fail closed.

## Scope (bounded)
1. Add `verify_ai_hotel_write_access` (or scope param) in `outputs/dashboard.py` alongside the existing
   read dep — same signing/PIN machinery, requires scope `ai-hotel:write` (superset-or-distinct of read).
2. Gate `POST /api/admin/{action}` on the write dep specifically (router stays read-gated; the admin route
   adds the write requirement). Reads unchanged.
3. Token/PIN minting: ensure a write-scope credential path exists for Brisen admin; read-only tokens must
   be rejected (403) at the admin endpoint. Fail closed on missing/forged scope.
4. Do NOT weaken the existing policy-layer human-admin check (`policy.projection.admin` AC7/T7) — this is an
   additional outer gate, defense-in-depth, not a replacement.

## Acceptance criteria
- AC1 `POST /api/admin/{action}` returns 403 for a valid `ai-hotel:read`-only token.
- AC2 Same endpoint succeeds for a valid `ai-hotel:write` token (approve/revoke/refresh unchanged behavior).
- AC3 All read endpoints unaffected (still work with read scope).
- AC4 Missing/forged/expired scope = fail closed (403/401), never silent allow.
- AC5 Policy-layer AI/external denial still enforced (unchanged).
- AC6 Tests: read-token-denied-on-admin, write-token-allowed, read-endpoints-unbroken, fail-closed paths.

## Threat focus for gate
Privilege escalation via read token; scope-claim forgery / missing-scope default-allow; admin route silently
inheriting only the read dep; downgrade (write token accepted but check no-op).

## Verify (Lesson #8)
- `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` + ai_hotel_lab.py
- `pytest tests/test_ai_hotel_cockpit.py -v` + auth tests
- Live exercise: read-token admin POST -> 403; write-token admin POST -> 200.

## Done = partner-live gate cleared
On merge+deploy+AC PASS, the residual gap from #3943/#3873 is closed; codex-arch/Director can then declare
Step 5 partner-live. Reply target: lead (bus).
