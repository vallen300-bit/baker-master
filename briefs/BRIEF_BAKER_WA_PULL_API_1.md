# BRIEF: BAKER_WA_PULL_API_1 — `GET /api/whatsapp/messages` read endpoint for desk consumption

## Drafted by
AH2 → AH1 (dispatch decision: which B-code, when). Director-ratified 2026-05-18.

## Context

Today desks (AO / MOVIE / Hagenauer / Cupial / BB / Origination / Brisen) that need to pull WhatsApp threads for matter work hit one of two friction paths:

1. **Baker MCP route** — `mcp__baker__baker_whatsapp_*` requires `/mcp` OAuth flow per picker session. Every desk pays this cost every session. Anchor: AO Desk session 2026-05-18, blocked pulling Constantinos + Masha threads for Vladislav KYC banker pack.
2. **Director paste-block fallback** — Director copy-pastes WA threads into chat. Doesn't scale across 7+ matter desks.

The data lives in Postgres `whatsapp_messages`. Baker already has X-Baker-Key auth + several WA write endpoints (`/api/whatsapp/backfill` `outputs/dashboard.py:959`, `/api/networking/sync-whatsapp-contacts` `outputs/dashboard.py:5442`). A read endpoint with the same auth pattern is the missing piece — every desk already has the X-Baker-Key in 1Password and already curls Baker for other ops.

## Estimated time: 2-3h
## Complexity: Low (one endpoint, established auth + SQL patterns, single file)
## Prerequisites: None

---

## Fix: Add `GET /api/whatsapp/messages` with X-Baker-Key auth

### Endpoint shape

```
GET /api/whatsapp/messages
  ?contact=<str>           # required — matches sender_name ILIKE or chat_id substring
  &from=<YYYY-MM-DD>       # required — inclusive lower bound on timestamp
  &to=<YYYY-MM-DD>         # required — inclusive upper bound on timestamp
  &limit=<int>             # optional, default 200, max 1000
  &format=<json|md>        # optional, default json

Headers: X-Baker-Key: <key>
```

### Response — `format=json` (default)

```json
{
  "status": "ok",
  "contact": "Constantinos",
  "from": "2026-05-11",
  "to": "2026-05-17",
  "count": 23,
  "messages": [
    {
      "id": "...",
      "timestamp": "2026-05-14T08:32:14+00:00",
      "sender": "<jid or phone>",
      "sender_name": "Constantinos",
      "chat_id": "<chat_id>",
      "full_text": "...",
      "has_media": false
    }
  ]
}
```

### Response — `format=md`

Markdown thread, oldest first, one block per message:

```
**[2026-05-14 08:32 UTC] Constantinos**
<full_text>

**[2026-05-14 08:35 UTC] Dimitry**
<full_text>
```

### Implementation

**File:** `outputs/dashboard.py` — add new endpoint co-located with other `tags=["whatsapp"]` routes (near line 959 for diff readability).

**Pattern to match exactly:** `dependencies=[Depends(verify_api_key)]` — same as `/api/whatsapp/backfill`. Do NOT roll a new auth mechanism.

**SQL (parameterised, LIMIT enforced per `.claude/rules/python-backend.md`):**

```sql
SELECT id, timestamp, sender, sender_name, chat_id, full_text,
       (media_path IS NOT NULL) AS has_media
FROM whatsapp_messages
WHERE (sender_name ILIKE %s OR chat_id ILIKE %s)
  AND timestamp >= %s
  AND timestamp < %s::date + INTERVAL '1 day'
ORDER BY timestamp ASC
LIMIT %s
```

Bind params: `(f"%{contact}%", f"%{contact}%", from_date, to_date, limit)`.

Verify the `media_path` column actually exists on whatsapp_messages before shipping — if the column is named differently (`media_url`, `has_attachment`, etc.) adjust accordingly. If no media column exists, return `has_media: false` unconditionally and note in PR description.

**Mandatory per `.claude/rules/python-backend.md`:**
- Wrap DB call in try/except; `conn.rollback()` in except block before any further query
- LIMIT clause is non-optional (already in spec above)
- Fault-tolerant: endpoint returns `{"status": "error", "message": "..."}` with 200 on DB failure, not 500 (consistent with `/api/whatsapp/backfill` line 994)

**Markdown formatter** — small helper inside the endpoint module, no new file:

```python
def _format_wa_md(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        ts = m["timestamp"].strftime("%Y-%m-%d %H:%M UTC")
        name = m.get("sender_name") or m.get("sender") or "Unknown"
        lines.append(f"**[{ts}] {name}**\n{m['full_text']}\n")
    return "\n".join(lines)
```

### Out of scope (do NOT do in this brief)

- Updating desk picker CLAUDE.md files with curl examples — AH1 dispatches a follow-up brief after this endpoint lands + smoke-tests green on Render
- Auth model changes (X-Baker-Key reuse is mandatory)
- Schema migrations (read-only endpoint)
- Caching layer (n/a for v1)
- Media file streaming (`has_media: true` is the flag; agents request the media separately via existing flow if needed)

---

## Acceptance criteria

1. `GET /api/whatsapp/messages` registered on FastAPI app with `tags=["whatsapp"]` + `Depends(verify_api_key)`
2. Required query params (`contact`, `from`, `to`) enforced — missing returns 422 (FastAPI default)
3. `limit` clamped to `[1, 1000]` via `Query(200, ge=1, le=1000)`
4. `format` validated to `{"json","md"}` — anything else returns 422
5. SQL uses LIMIT, parameterised binds (no f-string SQL), `conn.rollback()` on exception
6. JSON response shape exactly matches spec above (keys + types)
7. MD response is `text/plain` content-type, oldest-first ordering
8. Test file `tests/test_whatsapp_pull_api.py` with at least:
   - 200 + correct shape on valid request (mocked DB)
   - 422 on missing `contact`
   - 422 on `format=xml`
   - 401 (or whatever `verify_api_key` returns) on missing X-Baker-Key
   - Empty result returns `{"status":"ok", "count":0, "messages":[]}` not 404
9. `pytest tests/test_whatsapp_pull_api.py -v` green
10. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean
11. Smoke test from any desk after Render auto-deploy:
    ```
    curl -H "X-Baker-Key: $BAKER_KEY" \
      "https://baker-master.onrender.com/api/whatsapp/messages?contact=Constantinos&from=2026-05-11&to=2026-05-17&format=md"
    ```
    returns non-empty markdown thread

---

## Files touched

- `outputs/dashboard.py` — new endpoint + helper (~80 lines added, no existing lines modified)
- `tests/test_whatsapp_pull_api.py` — new file

No migrations. No new dependencies. No frontend changes.

---

## Risk + rollback

- **Risk: low.** Read-only endpoint, X-Baker-Key auth gates everything, established auth pattern reused, LIMIT clause caps payload, no schema changes.
- **Rollback:** revert the PR; endpoint disappears, no state to clean up, no callers yet (desks update only after AH1 dispatches follow-up).
- **Dependency on next step:** desks can't actually use this until AH1 dispatches the follow-up CLAUDE.md curl-line PR. That's a feature — endpoint can soak on Render first, get observed via Render logs, then opened to desks.

---

## Why this routing (AH2 → AH1, not AH2 → B1)

AH1 is sole orchestrator (charter §3). AH2 drafts cross-lane scope; AH1 owns dispatch decision (which B-code, when to slot, gate path). Director ratified Option A this session 2026-05-18; AH2 prepared brief; AH1 dispatches.
