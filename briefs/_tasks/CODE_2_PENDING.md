# CODE_2_PENDING — CAPABILITY_THREADS_1 fix-back — 2026-04-24

**Dispatcher:** AI Head #2 (Team 2)
**Working dir:** `~/bm-b2`
**Target branch:** `capability-threads-1` (continue, DO NOT reset)
**Parent PR:** https://github.com/vallen300-bit/baker-master/pull/57 (HOLD — security-review finding below)
**Complexity:** Trivial (~5 min — 3-line patch)

**Context:** PR #57 passed ship gate + regression but failed `/security-review`. Three new `@app.*` decorators were registered bare. Fix on same branch, same PR, single atomic commit. No new brief — this mailbox IS the brief.

---

## Finding (HIGH × 3, same root cause)

The three new `/api/pm/threads/*` endpoints you added in `outputs/dashboard.py` omit `dependencies=[Depends(verify_api_key)]`. Every other `/api/*` route in the file enforces it (line 62 `verify_api_key` helper; siblings at 646, 1017, 1058, 1118, 1154, 1209 …). The endpoints are reachable unauthenticated on `baker-master.onrender.com`.

Impact:
- `GET /api/pm/threads/{pm_slug}` — leaks `topic_summary` (verbatim Q+A preview) for any PM in `PM_REGISTRY`.
- `GET /api/pm/threads/{pm_slug}/{thread_id}/turns` — leaks full `question`/`answer` text, 50 turns per request.
- `POST /api/pm/threads/re-thread` — unauthenticated WRITE; mutates `capability_turns.thread_id` + `stitch_decision` JSONB; can create new `capability_threads` rows via `force_new=True` path. Corrupts the H4 audit-attribution lineage.

---

## Patch

**File:** `outputs/dashboard.py`
**Lines to change:** 11161, 11198, 11232 (the three new decorators).

Current (verified on `origin/capability-threads-1`):

```python
# line 11161
@app.get("/api/pm/threads/{pm_slug}")
async def get_pm_threads(pm_slug: str, limit: int = 20):

# line 11198
@app.get("/api/pm/threads/{pm_slug}/{thread_id}/turns")
async def get_pm_thread_turns(pm_slug: str, thread_id: str, limit: int = 50):

# line 11232
@app.post("/api/pm/threads/re-thread")
async def re_thread(req: Request):
```

After patch (match sibling convention — keep `tags=` if you prefer consistency with e.g. `tags=["capabilities"]` at 1209; not required):

```python
@app.get("/api/pm/threads/{pm_slug}", dependencies=[Depends(verify_api_key)])
async def get_pm_threads(pm_slug: str, limit: int = 20):

@app.get("/api/pm/threads/{pm_slug}/{thread_id}/turns", dependencies=[Depends(verify_api_key)])
async def get_pm_thread_turns(pm_slug: str, thread_id: str, limit: int = 50):

@app.post("/api/pm/threads/re-thread", dependencies=[Depends(verify_api_key)])
async def re_thread(req: Request):
```

`Depends` + `verify_api_key` are already imported at module top (used by every other route — verify: `grep -n "from fastapi import" outputs/dashboard.py` and `grep -n "^async def verify_api_key" outputs/dashboard.py`). No new imports needed.

---

## Ship gate (condensed)

```bash
# 1. Syntax
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); print('OK')"

# 2. Confirm exactly 3 sites patched (before commit)
grep -n '@app\.\(get\|post\)("/api/pm/threads' outputs/dashboard.py
# Expect each line to end with: dependencies=[Depends(verify_api_key)])

# 3. Count all /api/* routes with dependency — must be +3 vs pre-patch
grep -c 'dependencies=\[Depends(verify_api_key)\]' outputs/dashboard.py
```

Skip full-suite regression — 3-line scope, no logic change. Just syntax + grep.

---

## Frontend note

`outputs/static/app.js` `loadPMThreads()` currently fetches these endpoints without any header. That's fine pre-merge because the UI is feature-flagged off by default (`localStorage['baker.threads.ui_enabled'] === '1'`). Browser-side auth is a separate follow-up (out of scope for this fix-back — Director will decide wiring when enabling the UI). **Do NOT modify `app.js` in this patch.**

---

## Commit

```bash
git add outputs/dashboard.py
git commit -m "CAPABILITY_THREADS_1 fix-back: enforce X-Baker-Key on 3 new endpoints

Security-review (AI Head #2, 2026-04-24) flagged 3 HIGH findings — same
root cause: new /api/pm/threads/* decorators omitted
dependencies=[Depends(verify_api_key)]. Every other /api/* route in this
file enforces it (line 62 helper + sibling pattern). Adds the dependency
to the three decorators at lines 11161 / 11198 / 11232.

PR #57 kept open; merges only after /security-review re-run green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin capability-threads-1
```

---

## Ship report

Append a short `## 9. Fix-back (2026-04-24)` section to `briefs/_reports/CODE_2_RETURN.md` with:
- literal grep output showing the 3 decorators now carry the dependency,
- syntax-check OK line,
- confirmation that `app.js` / endpoint bodies / SQL unchanged.

Push the report commit with the patch (single commit OK; two sequential commits OK — either way).

---

## Standing by

AI Head #2 re-runs `/security-review` on your push. On PASS → Tier A merge → Render deploy → Quality Checkpoints 1–13 + verification SQL (per brief §Post-merge sequence).

— AI Head #2
