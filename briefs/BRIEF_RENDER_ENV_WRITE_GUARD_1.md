# BRIEF: RENDER_ENV_WRITE_GUARD_1 — prevent another catastrophic Render env-var wipe

## Context

2026-05-17: catastrophic Render env-var wipe on `baker-master` (srv-d6dgsbctgctc73f55730). All 32 env vars were wiped because an agent (or script) issued a raw `PUT /env-vars` with an array body that REPLACES the entire env-var set rather than merging into it. Recovery took 3 rounds across two parallel AH1 sessions; 11 vars restored from 1Password. Lower-tier vars (feature flags, `ALLOWED_ORIGINS`, etc.) still missing as of session close.

The Render env-var API has two semantically distinct modes:
- `PUT /v1/services/{id}/env-vars` with array body → **REPLACES** the whole set
- `PUT /v1/services/{id}/env-vars/{KEY}` with single-key body → **upserts** one key (safe; the pattern every agent should use)

The first is a foot-cannon. The second is the canonical safe pattern. Today's incident proved the foot-cannon is reachable via at least one agent path. This brief ships a guard.

## Estimated time: ~2-3 builder-hours
## Complexity: Low-Medium
## Prerequisites
- None. Local-only Python utility + test.
- No deploy required (this is operator-side tooling, not server-side runtime).

## API version / deprecation / fallback
- Render API v1 (stable; no deprecation announced).
- The merge-mode single-key PUT is the canonical pattern documented at `_ops/agents/ai-head/LONGTERM.md` and `.claude/rules/python-backend.md`.
- Fallback: if guard is bypassed somehow, post-incident audit catches via Render API call log (already in place).

---

## Problem statement (one paragraph)

Today's wipe traces to an agent path issuing `PUT /env-vars` with array body — replace-mode — when the intent was merge. The two API modes look nearly identical at the URL level (`/env-vars` vs `/env-vars/{KEY}`), the destructive one is the more "obvious" path-stem, and curl invocations don't fail loudly when used wrong (they happily replace). Hardening must intercept before the wire — a pre-write linter that rejects array-form PUT to `/env-vars` and forces single-key PUT to `/env-vars/{KEY}`.

## Acceptance criteria

1. New module `tools/render_env_guard.py` (or similar — confirm location with existing tool layout) exporting `safe_env_put(service_id, key, value, render_key)` that:
   - Issues `PUT /v1/services/{service_id}/env-vars/{key}` with single-key body `{"value": "<value>"}` (merge mode).
   - Returns the parsed response on success.
   - Raises a clear exception on 4xx/5xx.
2. New CLI wrapper or `__main__` block invokable as `python -m tools.render_env_guard <service_id> <key> <value>` for human use.
3. A defensive guard `forbid_array_put(payload)` that detects any caller attempting array-form PUT and raises `RenderEnvGuardError` with: "Use safe_env_put(service_id, KEY, value) — raw PUT /env-vars with array body REPLACES the entire env set. Today's anchor: 2026-05-17 wipe."
4. README / docstring at top of module pointing to the LONGTERM.md entry + this brief + the 2026-05-17 wipe anchor.
5. Test `tests/test_render_env_guard.py` covers:
   - `safe_env_put` issues correct URL + body (mocked requests).
   - `forbid_array_put` raises on list body.
   - `forbid_array_put` passes on dict body with single value.
6. Update `.claude/rules/python-backend.md` to reference `tools.render_env_guard` as the canonical Python path (today's rule entry "Render env vars: use MCP merge mode, NEVER raw PUT" gets a pointer to the Python utility).
7. Add a note to `_ops/agents/ai-head/LONGTERM.md` Render section pointing to the utility.
8. Literal `pytest tests/test_render_env_guard.py -v` green.

## What this brief does NOT do

- Does NOT touch the Render API itself (vendor surface; out of our control).
- Does NOT block bash/curl invocations directly (those still possible from terminal; this guard catches the Python path that every agent should use).
- Does NOT delete or alter any existing env-var write code paths in `outputs/dashboard.py` or `triggers/` (those are read-only against env vars).
- Does NOT introduce a server-side audit hook (potential follow-up; out of scope here).

## Implementation sketch

```python
# tools/render_env_guard.py
"""Safe Render env-var writes — canonical Python path.

Anchor: 2026-05-17 catastrophic env-var wipe on baker-master. Raw
PUT /v1/services/{id}/env-vars with array body REPLACES the entire env-var set;
this module forces the merge-mode single-key path that NEVER replaces.
"""
from __future__ import annotations
import os
import requests

RENDER_API_BASE = "https://api.render.com/v1"

class RenderEnvGuardError(Exception):
    pass

def forbid_array_put(payload) -> None:
    if isinstance(payload, list):
        raise RenderEnvGuardError(
            "Use safe_env_put(service_id, KEY, value) — raw PUT /env-vars "
            "with array body REPLACES the entire env set. Anchor: 2026-05-17 wipe."
        )

def safe_env_put(service_id: str, key: str, value: str, render_key: str | None = None) -> dict:
    render_key = render_key or os.environ.get("RENDER_API_KEY")
    if not render_key:
        raise RenderEnvGuardError("RENDER_API_KEY missing — set env or pass render_key=")
    url = f"{RENDER_API_BASE}/services/{service_id}/env-vars/{key}"
    body = {"value": value}
    forbid_array_put(body)  # invariant: should never trip on dict body
    resp = requests.put(
        url,
        headers={"Authorization": f"Bearer {render_key}"},
        json=body,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RenderEnvGuardError(f"Render API {resp.status_code}: {resp.text[:200]}")
    return resp.json()
```

## Out of scope

- Server-side guard (would require Render-side hook; not available).
- Audit-trail logging to baker_actions (could add; defer until usage settled).
- Wrapping AH2 / B-code Render write paths (they'll adopt the utility next time they touch env vars; no forced migration).

## Ship gate

- Literal `pytest tests/test_render_env_guard.py -v` output in ship report
- Branch: `b<N>/render-env-write-guard-1` (pick B-code on dispatch)
- PR title: `feat(tools): render_env_guard — prevent catastrophic env-var wipe`

## Anchors

- 2026-05-17 catastrophic env-var wipe (11 vars restored across 3 rounds).
- Lesson recorded: `memory/feedback_render_env_var_wipe_lesson.md` (this session).
- Existing rule: `.claude/rules/python-backend.md` — "Render env vars: use MCP merge mode, NEVER raw PUT".
- Existing canonical pattern: `_ops/agents/ai-head/LONGTERM.md` Render section.
