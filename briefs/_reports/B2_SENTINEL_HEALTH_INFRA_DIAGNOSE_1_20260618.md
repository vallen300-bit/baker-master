# B2 — SENTINEL_HEALTH_INFRA_DIAGNOSE_1 (diagnose + propose)

**Dispatch:** bus #3281 from `lead`, 2026-06-18. Diagnose 2 sentinels degrading `/api/health`; NO blind prod/credential change.
**Method:** read live `sentinel_health` + `baker_actions` via Baker MCP (real errors, not guessed) + source trace.

---

## Sentinel 1 — `todoist`: GENUINE failure (credential rot)

**Live state:** `status=down`, `consecutive_failures=7`, `last_success_at=2026-05-17 11:47Z`, `last_error_at=2026-06-18 04:26Z`.
**Real error:** `Client error '401 Unauthorized' for url 'https://api.todoist.com/api/v1/projects'`.

**Root cause — where the credential is read:**
- `config/settings.py:379` → `TodoistConfig.api_token = os.getenv("TODOIST_API_TOKEN", "")`.
- `triggers/todoist_client.py:38,45` → sent as `Authorization: Bearer {token}`.
- 401 on every poll since ~2026-05-17 = the `TODOIST_API_TOKEN` in Render env is **invalid/revoked/rotated**. No fallback source (env-only). Not a code bug.

**Proposed fix (needs a LIVE credential — surfacing per dispatch):**
1. Director regenerates a Todoist API token: Todoist → Settings → Integrations → Developer → "API token" (copy the personal token).
2. Update Render env `TODOIST_API_TOKEN` via merge-mode only (`tools.render_env_guard.safe_env_put`; NEVER raw array PUT — Lesson 2026-05-17 wipe), then trigger a deploy/restart.
3. Self-heals on next poll: `report_success("todoist")` resets the row to healthy.
**Blocker:** cannot proceed without the new token from Director. No code change required.

---

## Sentinel 2 — `roadmap_drift_sentinel`: FALSE POSITIVE (code bug, not a live failure)

**Live state:** `status=down`, `consecutive_failures=3`, `last_error_at=2026-05-20 06:00Z` (frozen ~1 month), `last_error_msg=clickup_post_failed`.

**Lead's brief assumed this is genuine + recent ("real error since ~05-20"). Evidence says otherwise:**
- `baker_actions` shows the daily 06:00 `post_comment` to ClickUp task `86c9k6kau` **succeeding every day** — 06-13, 06-14, 06-15, 06-16, 06-17, **and 06-18 06:00 (success=True)**.
- So ClickUp posting works and has for weeks; the original `clickup_post_failed` on 05-20 is long resolved.

**Root cause — arity-mismatch bug that wedges the health row 'down' forever:**
- `triggers/sentinel_health.py:129` → `def report_success(source: str):` — **1 positional arg**.
- `orchestrator/roadmap_drift_sentinel.py:223` → `report_success("roadmap_drift_sentinel", payload)` — **2 args**.
- → `TypeError: report_success() takes 1 positional argument but 2 were given`, swallowed by the wrapper's bare `except: pass` (lines 220-225).
- Net: roadmap_drift can NEVER write a 'healthy' row. After its one real failure (05-20) it is permanently stuck `down` even though every run since has succeeded. `report_failure(source, error)` has the matching 2-arg signature, so failures DO record — that asymmetry is why the row froze at the last failure.

**Same bug, 3 more callers (latent — these only report success, so they silently never clear):**
- `triggers/embedded_scheduler.py:1515` `report_success("wiki_lint", {...})`
- `triggers/embedded_scheduler.py:1530` `report_success("ao_pm_lint", {})`
- `triggers/embedded_scheduler.py:1550` `report_success("movie_am_lint", {})`

**Proposed fix (pure code, NO credential):**
- Widen the signature, backward-compatible, fixes all 4 callers at once:
  `def report_success(source: str, payload: dict | None = None):` (payload accepted; log at debug or ignore).
- No manual DB write needed: once deployed, the next 06:00 roadmap_drift run calls `report_success` cleanly → row auto-heals to `healthy`. (Optional belt-and-suspenders: `reset_sentinel("roadmap_drift_sentinel")`.)
- Add a regression test asserting `report_success(src, {...})` does not raise and writes status='healthy'.

---

## Summary for dispatch decision

| Sentinel | Genuine? | Root cause | Fix owner | Credential needed |
|---|---|---|---|---|
| todoist | YES | `TODOIST_API_TOKEN` revoked ~05-17 → 401 | Director supplies token → env merge-PUT | YES (Director) |
| roadmap_drift_sentinel | NO (false +) | `report_success` arity bug wedges row 'down' | code fix (1-line sig widen + test) | NO |

Diagnose-only per brief — no code changed, no env touched. Awaiting `lead` on: (a) Director Todoist token, (b) dispatch the `report_success` signature fix (also clears 3 latent lint sentinels).
