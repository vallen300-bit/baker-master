# BRIEF: ARRIVALS_EMBED_COOKIE_FIX_1 — let /arrivals render inside the Brisen Lab embed

```yaml
brief_id: ARRIVALS_EMBED_COOKIE_FIX_1
dispatched_by: lead
assigned_to: b3
repo: baker-master (worktree ~/bm-b3; branch b3/arrivals-embed-cookie-fix-1 from origin/main)
status: PENDING
```

## Context

Director's Triaga ruling 2026-07-21: BOTH boards (Baker Dashboard + Arrivals)
open DIRECT-EMBEDDED on sidebar click in the Lab /v2 shell. b2's Phase-A
prototype gate (bus #14414) proved the split: Baker Dashboard embeds fine;
**/arrivals renders bare "Not Found" inside the cross-origin iframe** while
rendering the full flip-board top-level in the same browser.

Root cause verified by lead in code: the arrivals access cookie is set with
`samesite="strict"` (`outputs/dashboard.py:2114-2121`,
`_set_arrivals_board_cookie`). In a cross-origin iframe (top-level =
brisen-lab.onrender.com) the browser withholds SameSite=Strict cookies, the
cookie gate fails, and the 404-disguise gate answers (Lesson #122 pattern —
the "Not Found" IS the gate).

b2 shipped the honest fallback (link pane) per the Phase-A brief; when THIS
fix is live, b2 wires the Arrivals embed (their offer, #14414).

### Surface contract: N/A — backend-only cookie/header change; the UI surface is b2's Phase-A work, already contracted there

## Estimated time: ~1-2h
## Complexity: Low
## Prerequisites: none (independent of Phase A; b2 wires on land)

## Harness V2

- **Context Contract:** this brief (whole); `outputs/dashboard.py` arrivals
  block only — `_ARRIVALS_BOARD_PIN_COOKIE` (:164), `_arrivals_board_pin*` /
  `_arrivals_board_cookie_ok` / `_arrivals_board_access` /
  `_set_arrivals_board_cookie` (:2074-2121), and every call site of
  `_arrivals_board_access` (grep — :8606, :8621, :8783, :8801 region);
  existing arrivals tests in `tests/` if any (grep `arrivals` in tests/).
  Nothing else — do NOT read the whole dashboard.py.
- **Task class:** small-fix-production (baker-master, production).
- **Done rubric:** terminal = Merged + Deployed + post-deploy AC. Post-deploy
  AC (lead + b2): authenticated Director browser, /arrivals inside the
  brisen-lab /v2 iframe renders the flip-board; top-level behavior unchanged;
  cookie still HttpOnly+Secure. Writeback: ship report on bus, cc b2.
- **Gate plan:** b3 self-test → push branch → blocking codex gate on pushed
  SHA → lead merge → Render auto-deploy → live embed AC with b2.

---

## Fix 1: SameSite=None + frame-ancestors allowlist for the arrivals surface

### Problem
`samesite="strict"` makes the arrivals cookie invisible to any cross-origin
iframe, so the ratified Lab embed cannot ever authenticate.

### Current State
`outputs/dashboard.py:2114-2121` — cookie set `httponly=True, secure=True,
samesite="strict"`. No frame-embedding headers anywhere on baker-master
(verified live 2026-07-21: no X-Frame-Options, no CSP).

### Engineering Craft Gates
- Diagnose: DONE — b2's live prototype (bus #14414) + code confirmation; no
  competing hypotheses (Strict-cookie withholding fully explains the split).
- Prototype: N/A — mechanism is a two-line semantic change with a known
  browser contract.
- TDD/verification: applies — test seam = the arrivals page/API endpoints via
  FastAPI TestClient: (1) cookie set with `SameSite=None; Secure; HttpOnly`
  (assert on Set-Cookie header string); (2) arrivals page response carries
  `Content-Security-Policy: frame-ancestors 'self' https://brisen-lab.onrender.com`;
  (3) valid-cookie request still passes the gate; (4) no-cookie request still
  gets the 404 disguise. Write test (1)+(2) first.

### Implementation
1. `_set_arrivals_board_cookie` (:2114): `samesite="strict"` →
   `samesite="none"` (keep `httponly=True, secure=True` — SameSite=None
   REQUIRES Secure, already true). Touch ONLY the arrivals cookie — the other
   `set_cookie` at :582-588 stays strict.
2. Clickjacking guard to compensate (SameSite=None means any site could
   FRAME the board even though it cannot read it): on the arrivals PAGE
   response (the HTML route around :8606 region) add header
   `Content-Security-Policy: frame-ancestors 'self' https://brisen-lab.onrender.com`.
   Header on the HTML page response(s) only — NOT global middleware, NOT the
   JSON APIs (they are not framable documents), so blast radius stays zero.
3. Comment both lines with the why (embed ruling + b2 #14414 + this brief id).

### Key Constraints
- Do NOT touch `_mcp_verify_key`, the PIN flow, token derivation, or the 404
  disguise — gate logic byte-identical; only cookie attributes + one header.
- Do NOT add X-Frame-Options (it can't express an allowlist; CSP wins).
- Do NOT change the other cookie (:582) or any other surface.
- Cookie re-issue: existing Strict cookies in Director's browser will be
  replaced on next pin entry / cookie refresh — note in ship report that
  Director may need ONE top-level /arrivals visit (pin re-entry at most)
  before the embed authenticates.

### Verification
- pytest: the 4 tests above + full existing arrivals tests green.
- Syntax: `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`.
- Live (post-merge, with b2 + lead): /v2 → ARRIVALS click → flip-board renders
  embedded in Director's Chrome; top-level /arrivals unchanged.

---

## Files Modified
- `outputs/dashboard.py` — cookie attr + CSP header on arrivals HTML route(s)
- `tests/` — arrivals cookie/header tests (new or extended)

## Do NOT Touch
- Any non-arrivals cookie or route; global middleware; auth/PIN logic
- `migrations/`, env vars — none needed

## Quality Checkpoints
1. Set-Cookie shows `SameSite=None; Secure; HttpOnly` on arrivals responses.
2. CSP frame-ancestors present on arrivals HTML, absent elsewhere.
3. 404 disguise for unauthenticated requests unchanged.
4. Live embed AC passes with b2; top-level behavior identical.
