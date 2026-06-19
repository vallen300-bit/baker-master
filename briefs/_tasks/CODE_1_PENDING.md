---
status: PENDING
brief_id: STATIC_HTML_NOCACHE_REVALIDATE_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-19
task_class: bug-fix
harness_v2: applies
gate_plan: G1 self-test (pytest) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
---

# BRIEF — STATIC_HTML_NOCACHE_REVALIDATE_1 — stop dashboards serving stale cached HTML

## Context
Director deployed AI_HOTEL_FIELD_NOTES_AND_AUDIO_1 (#381) then opened the AI-Hotel Field Notes dashboard and
**could not see his saved card** — the live HTML + feed were correct (cap 17 = site_visit/confirmed returned by
the API), but his browser served a **pre-deploy cached copy** of the page. Root cause confirmed live:
`StaticFiles` mount sets `etag` + `last-modified` but **no `Cache-Control`**, so browsers/iOS-PWA heuristically
cache the HTML and skip revalidation. Every deploy risks the Director seeing a stale dashboard. This bit a real
Director session — fix it for all static HTML.

**RACI:** accountable=lead, responsible=b1, gate=codex (G3). **Complexity:** Low.

## Current State (verified this session)
- Static mount: `outputs/dashboard.py:1545` → `app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")`.
- Live `GET /static/ai-hotel.html` returns `etag` + `last-modified` but NO `Cache-Control` (curl-confirmed).
- The AI-Hotel pages (`ai-hotel.html`, `ai-hotel-capture.html`) are self-contained, opened via a `?key=`
  bookmark — there is NO referenced sub-asset to `?v=`-bust, so the only lever is a response header on the HTML.

## Engineering Craft Gates
- **Diagnose:** APPLIES. Symptom reproduced (Director's stale page); root cause = missing Cache-Control on
  StaticFiles HTML. Feedback loop: `curl -sI https://baker-master.onrender.com/static/ai-hotel.html | grep -i cache-control`.
  Hypothesis confirmed (no header → heuristic cache). Probe/regression: assert the served HTML carries `Cache-Control: no-cache`.
- **Prototype:** N/A. **TDD:** APPLIES — write the header-assertion test first.

## Fix
Subclass `StaticFiles` so `text/html` responses carry `Cache-Control: no-cache` (revalidate-always), then mount
the subclass instead of the bare `StaticFiles` at line 1545. Use **`no-cache`, NOT `no-store`** — `no-cache`
means "always revalidate", and the existing `etag` then yields a cheap `304 Not Modified` when unchanged
(fresh-on-deploy, near-zero bandwidth otherwise). Apply ONLY to `.html`/`text/html` — leave images/JS/CSS
(if any) on normal caching.

```python
# near the other StaticFiles import / mount
from starlette.staticfiles import StaticFiles as _StarletteStaticFiles

class NoCacheHTMLStaticFiles(_StarletteStaticFiles):
    """Static mount that forces revalidation on HTML so a deploy is never
    masked by a browser/PWA-cached page (Director stale-dashboard incident
    2026-06-19). etag still yields 304 when unchanged — cheap + always fresh."""
    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        try:
            ct = resp.headers.get("content-type", "")
            if ct.startswith("text/html"):
                resp.headers["Cache-Control"] = "no-cache"
        except Exception:
            pass
        return resp
```
Then at line 1545: `app.mount("/static", NoCacheHTMLStaticFiles(directory=str(_static_dir)), name="static")`.
**Verify the `file_response` signature against the installed Starlette version before relying on it** — if the
hook point differs, achieve the same via a tiny middleware that stamps `Cache-Control: no-cache` on `text/html`
responses whose path starts with `/static/`. Pick whichever matches the installed Starlette cleanly.

## Acceptance criteria (prove with pytest — NOT "by inspection")
- AC1: `GET /static/ai-hotel.html` response carries `Cache-Control: no-cache` (TestClient assertion).
- AC2: a non-HTML static asset (e.g. an image/JS if present) does NOT get `no-cache` forced (normal caching preserved).
- AC3: the page still serves 200 with correct body (no regression to the mount); `etag` still present (304 path intact).

## Files Modified
- `outputs/dashboard.py` — `NoCacheHTMLStaticFiles` subclass + swap at the mount (line ~1545).
- `tests/test_static_nocache.py` — NEW (AC1–AC3, via FastAPI TestClient).

## Do NOT Touch
- The static files themselves. Other `FileResponse` routes that already set `Cache-Control: no-cache`.
- Applied migrations / anything orthogonal. No new dependencies.

## Done rubric
DONE = AC1–AC3 pytest green (paste tail) + `py_compile` clean + live `curl -sI .../static/ai-hotel.html` shows
`Cache-Control: no-cache` after deploy + codex G3 PASS + `POST_DEPLOY_AC_VERDICT v1`. Compile-clean ≠ done.

## Kill criteria
- Mount swap breaks static serving (any 404/500 on a previously-served asset) → immediate revert.
- `no-store` used instead of `no-cache` (kills the cheap 304 path) → fix before merge.

## Gate plan
G1 pytest → G2 `/security-review` → G3 codex (bus `lead`→`codex`, topic `gate-request/prNNN`) → lead merge →
b1 `POST_DEPLOY_AC_VERDICT v1` (incl. the live curl header check). Branch `b1/static-html-nocache-revalidate-1`
→ PR to baker-master `main`. Bus-post on ship + gate-request + post-deploy. Reply target: lead.
