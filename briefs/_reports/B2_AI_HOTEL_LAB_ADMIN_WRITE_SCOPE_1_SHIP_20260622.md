# B2 Ship Report — AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1

- **Brief:** AI_HOTEL_LAB_ADMIN_WRITE_SCOPE_1 (Sprint-0 partner-live unblocker)
- **PR:** https://github.com/vallen300-bit/baker-master/pull/413
- **Branch:** `b2/ai-hotel-admin-write-scope` · **Dispatched by:** lead · **reply target:** lead (bus)
- **Tier:** B-adjacent (auth boundary) — gate-chain mandatory, no merge until G4

## Done rubric
The projection-admin mutation endpoint now requires a strictly higher `ai-hotel:write` scope; reads keep `ai-hotel:read`; a read-only credential can no longer drive the kill switch. Closes the Step-5.1 G4 sub-threshold gap that held Step 5 back from partner-live.

## Delta
| File | Change |
|---|---|
| `outputs/dashboard.py` | New `verify_ai_hotel_write_access` (`ai-hotel:write`). Master `X-Baker-Key` = admin/write credential. Read-only cookie → 403 (insufficient), no credential → 401, forged/expired → fail closed. Refactored session auth into `_ai_hotel_session_scope` (HMAC-signed scope extraction); read access accepts read-or-write (write superset). `_ai_hotel_sign_session(scope=...)` parameterized. |
| `outputs/ai_hotel_lab.py` | Admin route gets placeholder `_write_auth` dep; bound to the real verifier via `app.dependency_overrides` at include time (avoids the dashboard↔module circular import). Router stays read-gated; admin adds write. |
| `tests/test_ai_hotel_cockpit.py` | 8 TestClient auth-scope tests (AC1-AC4). |

The inner policy-layer human-admin check (`policy.projection.admin`, AC7/T7) is **unchanged** — this is an outer gate, defense in depth.

## AC mapping
- AC1 read-token → 403 on admin → `test_aws_ac1_read_only_token_denied_on_admin`
- AC2 master-key → 200 + write-cookie → 200 → `test_aws_ac2_master_key_allowed_on_admin`, `test_aws_ac2_write_scope_cookie_allowed_on_admin`
- AC3 reads unbroken (read cookie + master key) → `test_aws_ac3_reads_unaffected_by_read_token_and_master_key`
- AC4 missing → 401, forged-scope → fail closed, expired → fail closed → `test_aws_ac4_*`
- AC5 policy-layer AI/external denial unchanged → Step-5.1 `test_s51_ai_and_external_principals_cannot_admin` still green

## G1 — pytest (literal)
```
tests/test_ai_hotel_cockpit.py ......................................... 70 passed
ai-hotel + test_partner_projection + test_policy_core: 457 passed, 2 skipped
```

## Fail-loud: pre-existing unrelated failure (NOT this brief)
`tests/test_ai_hotel_pin_gate.py::test_pin_success_sets_secure_cookie_and_reads_only_ai_hotel` fails on the assertion `assert "Path=/api/ai-hotel" in set_cookie` — the AI-Hotel session cookie path was widened to `"/"` in AI_HOTEL_LAB_COCKPIT_UI_1 (dashboard.py `path="/"`), so the assertion is stale. **Confirmed pre-existing** — fails identically with this branch stashed. Left untouched for scope discipline; flagging for a dedicated one-line test fix (assert `Path=/`). Lead's call whether to fold here or a separate ticket.

## Gate plan / next
G1 ✅ → G2 deputy-codex (privilege-escalation / scope-bypass) → G3 deputy AC → G4 lead `/security-review` → merge → deploy → b2 `POST_DEPLOY_AC_VERDICT v1` (live: read-token admin POST → 403, write/master admin POST → 200). On AC PASS the residual #3943/#3873 gap closes and Step 5 can go partner-live.
