# B3 Ship Report — ARRIVALS_EMBED_COOKIE_FIX_1

- **Brief:** `briefs/_tasks/ARRIVALS_EMBED_COOKIE_FIX_1.md` (dispatched_by: lead; assigned_to: b3)
- **Dispatch:** wake bus #14418 → ship bus #14427
- **Branch:** `b3/arrivals-embed-cookie-fix-1` off `origin/main`
- **PR:** #616 · **SHA:** `0dc1487c` (was `2cfc6ce4`; +bus-console guard per lead #14431)
- **Date:** 2026-07-21
- **Ship to:** lead (cc b2)

## Done rubric answer

Terminal = Merged + Deployed + post-deploy AC. This report covers through
**pushed + PR open + self-test green**. Remaining: blocking codex gate on
`2cfc6ce4` → lead merge → Render auto-deploy → live embed AC with b2.

## Problem

Director Triaga 2026-07-21 ruled `/arrivals` opens direct-embedded in the Lab
`/v2` shell. b2's Phase-A prototype (bus #14414) proved `/arrivals` renders bare
"Not Found" inside the cross-origin iframe. Root cause: the arrivals access
cookie was `SameSite=Strict`, so the browser withholds it in a cross-origin
iframe (top-level = brisen-lab.onrender.com); the cookie gate fails and the
404-disguise answers (Lesson #122 — the "Not Found" IS the gate).

## Change

- `outputs/dashboard.py` `_set_arrivals_board_cookie` (:2114): `samesite="strict"`
  → `"none"`. Keeps `Secure` + `HttpOnly` (SameSite=None requires Secure, already
  set). Cookie value stays unreadable cross-site.
- `outputs/dashboard.py` `/arrivals` HTML route (:8603): add
  `Content-Security-Policy: frame-ancestors 'self' https://brisen-lab.onrender.com`.
  Compensates for SameSite=None (any site could otherwise frame the board); CSP
  constrains framing to self + the Lab shell. HTML page only — not the JSON API,
  not global middleware.

Gate logic (`_mcp_verify_key`, PIN flow, 404 disguise) byte-identical. The other
cookie (`aih_session`, :588) untouched (stays Strict).

## Tests

`tests/test_arrivals_board.py` + `tests/test_bus_console.py`:
**38 passed, 1 skipped** (live-PG upsert). `outputs/dashboard.py` compiles clean.

New embed tests (`test_arrivals_board.py`):
1. cookie SameSite=None + Secure + HttpOnly
2. `/arrivals` page carries the frame-ancestors CSP
3. valid cookie still passes the gate (+ CSP present)
4. no-cookie request still 404-disguised, no CSP leak
5. JSON API has no CSP header

Updated existing SameSite assertions in `test_arrivals_board.py` (2) and
`test_bus_console.py` (1) — the shared cookie helper genuinely changed.

## Quality checkpoints (brief §)

1. ✅ Set-Cookie shows `SameSite=None; Secure; HttpOnly` on arrivals responses.
2. ✅ CSP frame-ancestors present on arrivals HTML, absent on the JSON API.
3. ✅ 404 disguise for unauthenticated requests unchanged.
4. ⏳ Live embed AC — pending, with b2 + lead post-deploy.

## Flag to lead → RESOLVED in-branch (lead ruling #14431)

`/bus-console` reuses the shared `arrivals_board_access` cookie helper, so it
inherited `SameSite=None`. I flagged it (bus #14427). Lead ruled #14431: a
surface must never lose Strict without gaining the fence, even read-only — guard
it now, same branch. Done at SHA `0dc1487c`: identical frame-ancestors CSP added
to the `/bus-console` HTML route (200 path only; 404 disguise unchanged, no CSP
leak) + a test. Reply with SHA on bus #14438.

## Post-deploy note

Existing Strict cookies in Director's browser get replaced on next pin entry —
Director may need ONE top-level `/arrivals` pin visit before the embed
authenticates.
