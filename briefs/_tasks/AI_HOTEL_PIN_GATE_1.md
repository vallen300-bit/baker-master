# BRIEF: AI_HOTEL_PIN_GATE_1

**Dispatched_by:** lead (AH1) — reply-to: lead
**Owner:** deputy-codex
**Priority:** MEDIUM (Director convenience — memorable access code)
**Task class:** medium-feature (auth surface)
**Harness-V2:** applies (emit POST_DEPLOY_AC_VERDICT)
**Source:** Director ask via deputy bus #3425(2)

## Goal
Let Director open the AI-Hotel dashboard with a short memorable code **6470** instead of pasting the long master key. The master `X-Baker-Key` (bakerbhavanga) MUST NOT be aliased to 6470 and MUST NEVER reach the browser via this path (blast-radius containment — deputy's hard flag).

## Design (engineer's secure shape — honors 6470 + contains risk)
1. **Env-configured PIN, not hardcoded:** `AI_HOTEL_PIN` env var (default value set to `6470` in Render). Server reads it; never commit the literal as the only source.
2. **PIN-auth endpoint:** `POST /api/ai-hotel/pin-auth` body `{pin}`. Constant-time compare against `AI_HOTEL_PIN`. On success, set an **httpOnly + Secure + SameSite=Strict** cookie `aih_session` = signed (HMAC, server secret) short-TTL token (e.g. 12h). On failure, 401 generic ("incorrect code"), no hint.
3. **Scoped acceptance:** the AI-Hotel READ endpoints (`/api/ai-hotel/captures`, `/captures/{id}/images`, `/captures/{id}/media`, `/captures/{id}/audio`, form-drafts read) additionally accept a valid `aih_session` cookie as auth. The cookie grants AI-Hotel read scope ONLY — it must NOT authorize any other Baker endpoint, writes, money, or sends. Existing `X-Baker-Key` auth stays unchanged.
4. **Brute-force mitigation (mandatory — 4 digits = 10k combos on a public URL):**
   - Rate-limit `pin-auth` per IP: e.g. 5 attempts / minute, then exponential backoff.
   - Lockout: after 10 consecutive failures from an IP, block that IP for 15 min (in-memory or DB-backed; fault-tolerant).
   - Log failed attempts (count only, no PIN value) for observability.
5. **Frontend:** on the keyless empty state, add a 4-digit PIN box ("Enter access code") alongside the existing paste-key affordance. On submit → POST pin-auth → on 200, cookie is set automatically → re-run `renderNotes()` (no reload, no key in JS). Wrong code → inline "Code not accepted". Keep the paste-key + remember-key paths intact.

## Security posture (built-in, not asked)
- Master key never exposed to browser; cookie is httpOnly (JS can't read it).
- Cookie scope limited to AI-Hotel read endpoints → brute-force worst case leaks Director's hotel field notes/photos/videos only, not the wider system.
- Rate-limit + lockout make 10k-combo brute-force infeasible (~33h at 5/min, lockout halts it).
- This is the convenience/risk tradeoff Director chose (4-digit memorable code); mitigations make it acceptable for this data class. If he later wants a longer code, only the `AI_HOTEL_PIN` env value changes.

## Acceptance criteria
1. `POST /api/ai-hotel/pin-auth {pin:"6470"}` → 200, sets httpOnly Secure cookie; wrong PIN → 401 generic.
2. After PIN auth, `GET /api/ai-hotel/captures` succeeds via cookie alone (no X-Baker-Key header, no key in JS).
3. The `aih_session` cookie does NOT authorize a non-AI-Hotel endpoint (verify a representative other endpoint returns 401 with only the cookie).
4. Rate-limit trips after the configured attempts/min; lockout blocks a brute-force loop; both fault-tolerant (no 500s).
5. Frontend PIN box loads cards on correct code with no reload; wrong code shows inline message; paste-key + remember-key paths unchanged.
6. Master `X-Baker-Key` is never returned to or stored in the browser by this flow.

## Kill criteria
1. Any path where 6470 maps to / exposes the master key in the browser = BLOCK.
2. Cookie usable on any non-AI-Hotel endpoint = BLOCK (scope breach).
3. No rate-limit / no lockout on the PIN endpoint = BLOCK (open brute-force).
4. PIN value logged in plaintext = block.

## Gates
- G1: pytest (pin-auth success/fail, scope isolation, rate-limit/lockout, cookie flags) + browser exercise.
- G2: /security-review MANDATORY (new auth surface + cookie + rate-limit).
- G3: lead routes to codex (auth surface) before merge.
- Post-deploy: I set `AI_HOTEL_PIN=6470` env on Render; emit POST_DEPLOY_AC_VERDICT exercising AC1–AC3 live.
