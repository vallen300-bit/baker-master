# BRIEF: BRISEN-LAB-AUTHZ-FACTORY-1 — extract `authz(policy, allow_director)` Depends factory + add Director exemption to GET /msg/{terminal}

**Repo:** `vallen300-bit/brisen-lab` (NOT baker-master)
**Branch:** `b2/brisen-lab-authz-factory-1`
**Tier:** **A** (auth-touching surface — same review chain as F1)

## Context

Bundle of two F1 follow-ups, both F2-gating. Director ratified bundle approach 2026-05-06: the Depends factory is the right home for the Director-exemption pattern, F2 brief is the customer.

- **F1-FU-1 (HIGH, ClickUp 86c9nnyvj)** — Add `_is_director` exemption to `GET /msg/{terminal}` + regression test pinning the choice. Matches the existing exemption pattern at `bus.py:386` (event-full), `bus.py:415` (delete), `bus.py:460` (ack).
- **F1-FU-2 (MEDIUM, ClickUp 86c9nnywq)** — Extract a FastAPI `Depends(authz(policy, allow_director=True))` factory consolidating the 6 hand-rolled authz shapes at `bus.py:184/307/362/398/446/510` (architect H2 finding). F2 will add new endpoints; without the factory, F2 adds a 7th hand-rolled shape.

**Why bundled:** the factory is the natural home for the Director-exemption flag; absorbing FU-1 into FU-2 means one PR, one review chain, no orphaned exemption code that the factory would just delete next week.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: PR #4 (F1) merged ✅ (010dbb9 2026-05-06T09:27:19Z); local main fast-forwarded.

---

## The 6 hand-rolled authz shapes (current state)

Verified via `grep -n "Depends\|x_terminal_key\|_require_worker_slug\|_is_director" bus.py`:

| # | Endpoint | Line | Authz shape today |
|---|----------|------|-------------------|
| 1 | `POST /msg/{terminal}` | 184 | auth-only (`_require_worker_slug` → sender_slug; no recipient gate) |
| 2 | `GET /msg/{terminal}` | 307–313 | `reader_slug == terminal` (F1; **no Director exemption** ← FU-1 fixes this) |
| 3 | `GET /event/{msg_id}/full` | 383–388 | `reader == sender OR reader ∈ recipients OR _is_director` |
| 4 | `DELETE /msg/{msg_id}` | 414–420 | `_is_director OR (slug == sender AND age ≤ 300s)` |
| 5 | `POST /msg/{msg_id}/ack` | 460 | `slug ∈ recipients OR _is_director` |
| 6 | `POST /msg/{msg_id}/ratify_decision` | 510 | `_require_worker_slug` then full H7 chain (token verify, jti consume, NH2 worker_slug match) |

Plus auth-only callers at `register-session-pubkey` (634) and `human-confirmation` (715) — covered by `Policy.AUTH_ONLY`.

**Scope decision:** factory absorbs shapes #1, #2, #3, #4, #5 + the 2 auth-only callers. Shape #6 (ratify_decision) keeps its bespoke H7 chain — token verify + jti single-use + parent-row FOR UPDATE is too entangled with the SQL transaction to factor cleanly, and it's not on F2's hot path. The factory provides the slug-resolve front step; the rest of #6 stays as-is.

---

## Implementation

### New file: `authz.py` (repo root, ~85 lines)

```python
"""
F1-FU-2 — FastAPI Depends factory consolidating bus.py authz shapes.

Replaces the hand-rolled `_require_worker_slug` + `_is_director` blocks at
bus.py:184/307/362/398/446/510 with a single Depends factory:

    authz(policy=Policy.RECIPIENT_OF_TERMINAL, allow_director=True)

Policies cover the slug-known-up-front cases. Shapes that need the message
row (event-full, ack, delete) get a CallerContext object whose helper methods
enforce the row-dependent check after the row is loaded.

Design:
- Policy enum names what the dependency enforces BEFORE the handler runs.
- allow_director=True means a Director slug satisfies the policy regardless.
  This matches the pre-existing exemption at bus.py:386/415/460 — extending
  it to GET /msg/{terminal} closes F1-FU-1 (Director moderation read path).
- CallerContext is the post-Depends value handlers receive. It carries the
  resolved slug + is_director flag so handlers don't redo the lookup.
- The factory itself stays sync (no DB hit) — slug resolution is in-memory
  via auth_lab._TERMINAL_KEYS. Endpoints that need DB rows do their existing
  SELECT and call ctx.require_*() against the loaded row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import Header, HTTPException, Request

import auth_lab


class Policy(str, Enum):
    """Authz policies enforced by the Depends factory.

    AUTH_ONLY                — caller must hold a valid terminal-key (no
                               recipient gate). Used by POST /msg/{terminal},
                               POST /auth/register-session-pubkey,
                               POST /auth/human-confirmation.

    RECIPIENT_OF_TERMINAL    — caller's slug must match the URL `{terminal}`
                               path parameter. Used by GET /msg/{terminal}.
                               With allow_director=True, Director can read
                               any inbox (F1-FU-1).

    Row-dependent shapes (event-full, ack, delete) DON'T have a Policy enum —
    they use AUTH_ONLY at the Depends layer, then call ctx.require_party_to(),
    ctx.require_recipient_of(), or ctx.require_sender_within_window() against
    the loaded message row inside the handler.
    """
    AUTH_ONLY = "auth_only"
    RECIPIENT_OF_TERMINAL = "recipient_of_terminal"


@dataclass(frozen=True)
class CallerContext:
    """Post-Depends authz context handed to bus.py handlers."""
    slug: str
    is_director: bool

    # --- row-dependent helpers ------------------------------------------

    def require_party_to_message(self, msg_row: dict) -> None:
        """Caller is sender, recipient, or Director. Used by GET /event/{id}/full.
        Raises HTTPException(403) if not."""
        if self.is_director:
            return
        if self.slug == msg_row.get("from_terminal"):
            return
        if self.slug in (msg_row.get("to_terminals") or []):
            return
        raise HTTPException(status_code=403, detail="not_party_to_message")

    def require_recipient_of_message(self, msg_row: dict) -> None:
        """Caller is recipient or Director. Used by POST /msg/{id}/ack.
        Raises HTTPException(403, 'not_recipient') if not."""
        if self.is_director:
            return
        if self.slug in (msg_row.get("to_terminals") or []):
            return
        raise HTTPException(status_code=403, detail="not_recipient")

    def require_sender_within_window(self, msg_row: dict, window_s: int) -> None:
        """Caller is Director, OR sender within window_s of created_at.
        Used by DELETE /msg/{id}. Raises HTTPException(403, 'forbidden') if not.

        Caller's window comparison reads created_at as a timezone-aware UTC
        datetime — bus.py SELECTs use the schema's TIMESTAMPTZ column."""
        if self.is_director:
            return
        if (self.slug == msg_row.get("from_terminal")
                and (datetime.now(timezone.utc) - msg_row["created_at"]).total_seconds()
                    <= window_s):
            return
        raise HTTPException(status_code=403, detail="forbidden")


def _is_director_slug(slug: str) -> bool:
    """Hard-coded match against the canonical Director slug. Single source
    of truth — bus.py's existing _is_director() helper at line 73 is removed
    by this brief in favor of CallerContext.is_director."""
    return slug == "director"


def authz(policy: Policy, *, allow_director: bool = True):
    """Build a FastAPI Depends callable enforcing `policy`.

    Returns CallerContext(slug, is_director) on success. Raises:
      - 401 bad_terminal_key — auth failed
      - 403 reader_slug_mismatch — RECIPIENT_OF_TERMINAL violated and
        not Director (or allow_director=False)

    Notes:
    - The dependency reads the {terminal} path param via `request.path_params`
      rather than declaring `terminal: Optional[str] = None` in its signature.
      FastAPI's parameter binder treats unbound name-typed params as query
      strings, which would expose `?terminal=director` as a leakable input on
      routes WITHOUT {terminal} in the path (event-full, ack, delete). Reading
      from request.path_params.get() avoids the query-leak entirely.
    - allow_director defaults True (matches every pre-existing exemption).
      F2 may pass allow_director=False for endpoints where Director must
      go through the same gate as workers (e.g., audit-trail integrity).
    """

    async def dep(
        request: Request,
        x_terminal_key: Optional[str] = Header(default=None),
    ) -> CallerContext:
        slug = auth_lab.resolve_terminal_key(x_terminal_key)
        if slug is None:
            raise HTTPException(status_code=401, detail="bad_terminal_key")
        is_director = _is_director_slug(slug)

        if policy is Policy.AUTH_ONLY:
            return CallerContext(slug=slug, is_director=is_director)

        if policy is Policy.RECIPIENT_OF_TERMINAL:
            terminal = request.path_params.get("terminal")
            if terminal is None:
                # Programmer error — route doesn't carry {terminal} in its
                # path. Fail loud rather than silently letting any caller
                # through.
                raise HTTPException(
                    status_code=500,
                    detail="authz_misconfigured:terminal_param_missing",
                )
            if slug == terminal:
                return CallerContext(slug=slug, is_director=is_director)
            if allow_director and is_director:
                return CallerContext(slug=slug, is_director=is_director)
            raise HTTPException(status_code=403, detail="reader_slug_mismatch")

        # Defensive — unreachable unless a new Policy is added without
        # extending this dispatcher.
        raise HTTPException(
            status_code=500,
            detail=f"authz_unknown_policy:{policy}",
        )

    return dep
```

### `bus.py` — refactor 5 endpoints to use the factory

Apply each edit below. After all 5 edits, the helpers `_require_worker_slug` (line 66) and `_is_director` (line 73) are removed; their consumers are gone. Also remove the `Header` import line if no other import depends on it (search before delete).

#### Edit 1 — Imports (top of `bus.py` around line 36–46)

Add the authz import alongside existing module imports:

```python
from authz import authz, CallerContext, Policy
```

Remove `Header` from the `fastapi` import line if all six `x_terminal_key: str = Header(None)` parameters are gone (verify with `grep -n "Header" bus.py` after refactor).

#### Edit 2 — Remove `_require_worker_slug` + `_is_director` (lines 66–74)

After all five endpoint refactors land, both helpers are dead. Delete them.

#### Edit 3 — `POST /msg/{terminal}` (line 168, was line 184)

```python
    @app.post("/msg/{terminal}")
    async def post_msg(terminal: str, req: Request,
                       ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        tracer = otel_setup.get_tracer()
        with tracer.start_as_current_span("brisen_lab.bus.post") as span:
            span.set_attribute("brisen_lab.terminal", terminal)
            if not freeze.is_v2_enabled():
                span.set_attribute("brisen_lab.outcome", "frozen")
                raise HTTPException(status_code=503, detail="lab_frozen")
            span.set_attribute("brisen_lab.from", ctx.slug)
            return await _post_msg_inner(terminal, req, ctx.slug,
                                         broadcast_fn, span)
```

Add `from fastapi import Depends` if not already imported. The `_post_msg_inner` helper is unchanged — it already takes `sender_slug` as a positional arg.

#### Edit 4 — `GET /msg/{terminal}` (line 298) — **closes F1-FU-1**

Replace the full handler. The Depends factory enforces `reader_slug == terminal OR Director`; the inline check on lines 312–313 is removed.

```python
    @app.get("/msg/{terminal}")
    async def get_msg(terminal: str,
                      since: Optional[str] = None,
                      kind: Optional[str] = None,
                      topic: Optional[str] = None,
                      exclude_self: bool = False,
                      include_deleted: bool = False,
                      limit: int = 200,
                      ctx: CallerContext = Depends(
                          authz(Policy.RECIPIENT_OF_TERMINAL,
                                allow_director=True))):
        # F1: peek-hole closed via factory authz. F1-FU-1: Director may read
        # any inbox via allow_director=True (matches event-full / ack / delete).
        if kind is not None and kind not in VALID_KINDS:
            raise HTTPException(status_code=400, detail=f"bad_kind:{kind}")
        if limit > 1000:
            limit = 1000

        clauses = ["(%s = ANY(to_terminals) OR '*' = ANY(to_terminals))"]
        params: list[Any] = [terminal]
        ...
```

**The SQL-clause filter remains keyed on `terminal` (the URL path param), not on `ctx.slug`.** When Director reads `/msg/lead`, the SQL filters on `'lead' = ANY(to_terminals)` — i.e., Director sees `lead`'s inbox, not Director's own inbox. That's the moderation-read intent.

The `if exclude_self:` clause currently references `reader_slug` (line 333). Update to `ctx.slug`:

```python
        if exclude_self:
            clauses.append("from_terminal <> %s")
            params.append(ctx.slug)
```

#### Edit 5 — `GET /event/{msg_id}/full` (line 359)

```python
    @app.get("/event/{msg_id}/full")
    async def get_event_full(msg_id: int,
                             ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        def _read():
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT id, thread_id, parent_id, from_terminal, to_terminals,
                               topic, kind, body, created_at, wake_attempted_at,
                               acknowledged_at, deleted_at, tier_required
                        FROM brisen_lab_msg WHERE id = %s
                        """,
                        (msg_id,),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None

        row = await asyncio.to_thread(_read)
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        ctx.require_party_to_message(row)
        return _row_to_dict(row)
```

#### Edit 6 — `DELETE /msg/{msg_id}` (line 393)

```python
    @app.delete("/msg/{msg_id}")
    async def soft_delete(msg_id: int,
                          ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        if not freeze.is_v2_enabled():
            raise HTTPException(status_code=503, detail="lab_frozen")

        def _delete() -> str:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT from_terminal, created_at, deleted_at "
                        "FROM brisen_lab_msg WHERE id = %s",
                        (msg_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return "not_found"
                    if row["deleted_at"] is not None:
                        return "already_deleted"
                    # require_sender_within_window raises 403 if denied —
                    # but we're inside to_thread(), so the HTTPException
                    # would propagate awkwardly. Compute the boolean here
                    # and let the outer code raise.
                    is_director_or_window = (
                        ctx.is_director
                        or (ctx.slug == row["from_terminal"]
                            and (datetime.now(timezone.utc) - row["created_at"]).total_seconds()
                                <= SENDER_DELETE_WINDOW_S)
                    )
                    if not is_director_or_window:
                        return "forbidden"
                    cur.execute(
                        "UPDATE brisen_lab_msg SET deleted_at = NOW() WHERE id = %s",
                        (msg_id,),
                    )
                    return "ok"

        result = await asyncio.to_thread(_delete)
        if result == "not_found":
            raise HTTPException(status_code=404, detail="not_found")
        if result == "already_deleted":
            return {"ok": True, "already": True}
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="forbidden")
        broadcast_fn({"kind": "bus_delete", "id": msg_id, "by": ctx.slug})
        return {"ok": True}
```

**Why the inline boolean instead of `ctx.require_sender_within_window`:** the policy check happens inside `asyncio.to_thread(_delete)` — we want the 403 to carry through the result-string pattern that `_delete` already uses, not propagate a raw HTTPException out of a thread. The CallerContext helper `require_sender_within_window()` is still in `authz.py` for other callers (and tested in the factory matrix) but `soft_delete` keeps its inline form. **Acceptable tradeoff** — the boolean is short, consistent with the surrounding `_delete()` style, and ratify_decision uses the same pattern (line 535+).

#### Edit 7 — `POST /msg/{msg_id}/ack` (line 439)

```python
    @app.post("/msg/{msg_id}/ack")
    async def ack_msg(msg_id: int,
                      ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        if not freeze.is_v2_enabled():
            raise HTTPException(status_code=503, detail="lab_frozen")

        def _ack() -> str:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        "SELECT to_terminals, acknowledged_at "
                        "FROM brisen_lab_msg WHERE id = %s",
                        (msg_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return "not_found"
                    if (ctx.slug not in (row["to_terminals"] or [])
                            and not ctx.is_director):
                        return "forbidden"
                    if row["acknowledged_at"] is not None:
                        return "already_acked"
                    cur.execute(
                        "UPDATE brisen_lab_msg SET acknowledged_at = NOW() "
                        "WHERE id = %s AND acknowledged_at IS NULL",
                        (msg_id,),
                    )
                    return "ok"

        result = await asyncio.to_thread(_ack)
        if result == "not_found":
            raise HTTPException(status_code=404, detail="not_found")
        if result == "forbidden":
            raise HTTPException(status_code=403, detail="not_recipient")
        if result == "already_acked":
            return {"ok": True, "already": True}
        broadcast_fn({"kind": "bus_ack", "id": msg_id, "by": ctx.slug})
        return {"ok": True}
```

Same inline-boolean rationale as Edit 6 — keep the `_ack()` thread-isolated, raise the HTTPException from the outer coroutine.

The cursor in this edit is upgraded from `conn.cursor()` to `conn.cursor(cursor_factory=RealDictCursor)` so `row["to_terminals"]` works (matches the dict-access pattern). **Verify** the existing pre-edit code at `bus.py:449-460` uses tuple-indexing (`to_terminals, acknowledged_at = row`) — it does, so this IS a real change. Same change applies in Edit 6 (DELETE handler at `bus.py:401`, originally `sender, created_at, deleted_at = row` tuple unpacking).

#### Edit 8 — `POST /msg/{msg_id}/ratify_decision` (lines 484–510)

Refactor the auth front step only. The H7 chain stays put. Replace the wrapper:

```python
    @app.post("/msg/{msg_id}/ratify_decision")
    async def post_ratify_decision(msg_id: int, req: Request,
                                   ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY)),
                                   x_human_confirmation_token: str = Header(None)):
        tracer = otel_setup.get_tracer()
        with tracer.start_as_current_span("brisen_lab.bus.ratify_decision") as span:
            span.set_attribute("brisen_lab.parent_msg_id", msg_id)
            if not freeze.is_v2_enabled():
                span.set_attribute("brisen_lab.outcome", "frozen")
                raise HTTPException(status_code=503, detail="lab_frozen")
            return await _ratify_decision_inner(
                msg_id, req, ctx.slug, x_human_confirmation_token, span,
            )
```

Update `_ratify_decision_inner` (line 508) signature: rename `x_terminal_key` → `sender_slug` and remove the now-redundant `_require_worker_slug` call on line 510. The rest of `_ratify_decision_inner` already uses `sender_slug` from line 511 onward — clean rename.

#### Edit 9 — `POST /auth/register-session-pubkey` (line 626)

```python
    @app.post("/auth/register-session-pubkey")
    async def register_session_pubkey(
            req: Request,
            ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        if not freeze.is_v2_enabled():
            raise HTTPException(status_code=503, detail="lab_frozen")
        worker_slug = ctx.slug
        ...  # rest unchanged
```

#### Edit 10 — `POST /auth/human-confirmation` (line 705)

```python
    @app.post("/auth/human-confirmation")
    async def human_confirmation(
            req: Request,
            ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        if not freeze.is_v2_enabled():
            raise HTTPException(status_code=503, detail="lab_frozen")
        caller_slug = ctx.slug
        ...  # rest unchanged
```

---

### Tests

#### NEW: `tests/test_authz_factory.py` — factory matrix

```python
"""F1-FU-2 — authz(policy, allow_director) Depends factory matrix tests.

Covers Policy × header × director × match grid for the factory itself,
isolated from bus.py endpoint logic. Exercises the factory via a tiny
test FastAPI app so the CallerContext-returning behavior is verified
without DB or freeze gates."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from authz import CallerContext, Policy, authz


@pytest.fixture
def factory_app():
    """Standalone FastAPI app exercising the factory at every Policy.

    Uses the same env-loaded terminal keys as the bus tests (set by
    conftest._set_required_env autouse fixture) so dir-key, lead-key, etc.
    resolve correctly via auth_lab._TERMINAL_KEYS."""
    app = FastAPI()

    @app.get("/auth-only")
    async def auth_only_route(
            ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))):
        return {"slug": ctx.slug, "is_director": ctx.is_director}

    @app.get("/recipient/{terminal}")
    async def recipient_route(
            terminal: str,
            ctx: CallerContext = Depends(
                authz(Policy.RECIPIENT_OF_TERMINAL, allow_director=True))):
        return {"slug": ctx.slug, "is_director": ctx.is_director,
                "terminal": terminal}

    @app.get("/recipient-no-director/{terminal}")
    async def recipient_no_director_route(
            terminal: str,
            ctx: CallerContext = Depends(
                authz(Policy.RECIPIENT_OF_TERMINAL, allow_director=False))):
        return {"slug": ctx.slug, "terminal": terminal}

    return TestClient(app)


# ---- AUTH_ONLY ----

def test_auth_only_valid_key_returns_slug(factory_app):
    r = factory_app.get("/auth-only", headers={"X-Terminal-Key": "lead-key"})
    assert r.status_code == 200
    assert r.json() == {"slug": "lead", "is_director": False}


def test_auth_only_director_flagged(factory_app):
    r = factory_app.get("/auth-only", headers={"X-Terminal-Key": "dir-key"})
    assert r.status_code == 200
    assert r.json() == {"slug": "director", "is_director": True}


def test_auth_only_no_header_401(factory_app):
    r = factory_app.get("/auth-only")
    assert r.status_code == 401
    assert r.json()["detail"] == "bad_terminal_key"


def test_auth_only_bad_key_401(factory_app):
    r = factory_app.get("/auth-only",
                        headers={"X-Terminal-Key": "not-a-real-key"})
    assert r.status_code == 401


# ---- RECIPIENT_OF_TERMINAL with allow_director=True ----

def test_recipient_self_match_succeeds(factory_app):
    r = factory_app.get("/recipient/lead",
                        headers={"X-Terminal-Key": "lead-key"})
    assert r.status_code == 200
    assert r.json()["slug"] == "lead"


def test_recipient_director_exemption_succeeds(factory_app):
    """F1-FU-1 — Director reads any terminal's lane via allow_director=True."""
    r = factory_app.get("/recipient/lead",
                        headers={"X-Terminal-Key": "dir-key"})
    assert r.status_code == 200
    assert r.json() == {"slug": "director", "is_director": True,
                        "terminal": "lead"}


def test_recipient_cross_terminal_403(factory_app):
    r = factory_app.get("/recipient/cowork-ah1",
                        headers={"X-Terminal-Key": "lead-key"})
    assert r.status_code == 403
    assert r.json()["detail"] == "reader_slug_mismatch"


def test_recipient_no_header_401(factory_app):
    r = factory_app.get("/recipient/lead")
    assert r.status_code == 401


# ---- RECIPIENT_OF_TERMINAL with allow_director=False ----

def test_recipient_no_director_self_match_succeeds(factory_app):
    r = factory_app.get("/recipient-no-director/lead",
                        headers={"X-Terminal-Key": "lead-key"})
    assert r.status_code == 200


def test_recipient_no_director_director_403(factory_app):
    """allow_director=False locks Director out — F2 may use this for
    audit-trail integrity endpoints where Director must go through the
    same gate as workers."""
    r = factory_app.get("/recipient-no-director/lead",
                        headers={"X-Terminal-Key": "dir-key"})
    assert r.status_code == 403
    assert r.json()["detail"] == "reader_slug_mismatch"


# ---- Misconfiguration safety ----

def test_recipient_misconfig_500():
    """Route without {terminal} in its path used Policy.RECIPIENT_OF_TERMINAL —
    factory must 500, NOT silently allow. Pins the fail-loud branch in dep."""
    app = FastAPI()

    @app.get("/misconfigured")  # no {terminal} in path
    async def bad_route(
            ctx: CallerContext = Depends(
                authz(Policy.RECIPIENT_OF_TERMINAL))):
        return {"slug": ctx.slug}

    client = TestClient(app)
    r = client.get("/misconfigured", headers={"X-Terminal-Key": "lead-key"})
    assert r.status_code == 500
    assert "authz_misconfigured" in r.json()["detail"]


# ---- CallerContext row-helpers ----

def test_caller_context_require_party_to_message_director_passes():
    ctx = CallerContext(slug="director", is_director=True)
    ctx.require_party_to_message(
        {"from_terminal": "lead", "to_terminals": ["cowork-ah1"]})


def test_caller_context_require_party_to_message_sender_passes():
    ctx = CallerContext(slug="lead", is_director=False)
    ctx.require_party_to_message(
        {"from_terminal": "lead", "to_terminals": ["cowork-ah1"]})


def test_caller_context_require_party_to_message_recipient_passes():
    ctx = CallerContext(slug="cowork-ah1", is_director=False)
    ctx.require_party_to_message(
        {"from_terminal": "lead", "to_terminals": ["cowork-ah1"]})


def test_caller_context_require_party_to_message_outsider_403():
    from fastapi import HTTPException
    ctx = CallerContext(slug="b1", is_director=False)
    with pytest.raises(HTTPException) as exc:
        ctx.require_party_to_message(
            {"from_terminal": "lead", "to_terminals": ["cowork-ah1"]})
    assert exc.value.status_code == 403
    assert exc.value.detail == "not_party_to_message"


def test_caller_context_require_recipient_director_passes():
    ctx = CallerContext(slug="director", is_director=True)
    ctx.require_recipient_of_message({"to_terminals": ["lead"]})


def test_caller_context_require_recipient_match_passes():
    ctx = CallerContext(slug="lead", is_director=False)
    ctx.require_recipient_of_message({"to_terminals": ["lead"]})


def test_caller_context_require_recipient_outsider_403():
    from fastapi import HTTPException
    ctx = CallerContext(slug="lead", is_director=False)
    with pytest.raises(HTTPException) as exc:
        ctx.require_recipient_of_message({"to_terminals": ["cowork-ah1"]})
    assert exc.value.status_code == 403
    assert exc.value.detail == "not_recipient"


def test_caller_context_require_sender_window_director_passes():
    from datetime import datetime, timedelta, timezone
    ctx = CallerContext(slug="director", is_director=True)
    # Even a 1-hour-old message — Director bypasses the window.
    ctx.require_sender_within_window(
        {"from_terminal": "lead",
         "created_at": datetime.now(timezone.utc) - timedelta(hours=1)},
        window_s=300)


def test_caller_context_require_sender_window_within_passes():
    from datetime import datetime, timedelta, timezone
    ctx = CallerContext(slug="lead", is_director=False)
    ctx.require_sender_within_window(
        {"from_terminal": "lead",
         "created_at": datetime.now(timezone.utc) - timedelta(seconds=10)},
        window_s=300)


def test_caller_context_require_sender_window_expired_403():
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    ctx = CallerContext(slug="lead", is_director=False)
    with pytest.raises(HTTPException) as exc:
        ctx.require_sender_within_window(
            {"from_terminal": "lead",
             "created_at": datetime.now(timezone.utc) - timedelta(seconds=400)},
            window_s=300)
    assert exc.value.status_code == 403
    assert exc.value.detail == "forbidden"


def test_caller_context_require_sender_window_wrong_sender_403():
    from datetime import datetime, timezone
    from fastapi import HTTPException
    ctx = CallerContext(slug="b1", is_director=False)
    with pytest.raises(HTTPException) as exc:
        ctx.require_sender_within_window(
            {"from_terminal": "lead",
             "created_at": datetime.now(timezone.utc)},
            window_s=300)
    assert exc.value.status_code == 403
```

#### EXTEND: `tests/test_inbox_read_authz.py` — add test 9 (FU-1 regression)

Append after `test_ack_director_exemption_succeeds`:

```python
def test_get_msg_director_exemption_succeeds(client):
    """9 — F1-FU-1: Director reads `lead`'s inbox via allow_director=True
    on Policy.RECIPIENT_OF_TERMINAL. Pins the choice (Director ratified
    2026-05-06) — silent regression here means we lost the moderation
    read path. Mirrors test 8's ack-side exemption."""
    posted = _post(client, "lead", "dir-key",
                   kind="dispatch", body="director moderation read",
                   to=["lead"], topic="dispatch/lead/test9")
    assert posted.status_code == 200, posted.text
    msg_id = posted.json()["message_id"]

    r = client.get("/msg/lead", headers={"X-Terminal-Key": "dir-key"})
    assert r.status_code == 200, r.text
    assert any(m["id"] == msg_id for m in r.json()["messages"]), (
        f"director read of lead inbox lost msg {msg_id}: {r.json()}")
```

Update the file's docstring (lines 1–20) to document 9 tests instead of 8:

```python
"""F1 + F1-FU-1 — recipient-bound authorization on GET /msg/{terminal}.

Closes the horizontal-privilege peek hole surfaced by the V2 cutover
cross-talk test 2026-05-05 (lead's key successfully read cowork-ah1's
inbox via path-substitution).

9-test list:
  1 — self-read succeeds (200, msg in list)
  2 — cross-terminal peek denied (403, reader_slug_mismatch)
  3 — no X-Terminal-Key header (401, regression of pre-fix behavior)
  4 — self-broadcast read succeeds (200, broadcast msg via OR-branch)
  5 — ack on self-addressed message succeeds (200, ack regression)
  6 — ack denied to non-recipient (403, ack regression)
  7 — cross-slug attack with INLINE-created third-slug key (403)
  8 — director exemption preserved on ack path (200, regression)
  9 — director exemption on GET /msg/{terminal} (200, F1-FU-1 — Director
       ratified 2026-05-06, matches event-full / ack / delete pattern)
"""
```

---

## Acceptance criteria

| AC | Test | Status |
|----|------|--------|
| A1 | `pytest tests/test_authz_factory.py -v` — all 22 tests PASS | ☐ |
| A2 | `pytest tests/test_inbox_read_authz.py -v` — all 9 tests PASS (8 existing + 1 new) | ☐ |
| A3 | Full `pytest` run — all existing tests PASS (no regressions) | ☐ |
| A4 | `grep -n "_require_worker_slug\|_is_director\b" bus.py` returns NOTHING | ☐ |
| A5 | `grep -n "x_terminal_key" bus.py` returns NOTHING (all replaced by `Depends`) | ☐ |
| A6 | `grep -n "Header(None)" bus.py` returns ONLY the `x_human_confirmation_token` line in `post_ratify_decision` | ☐ |
| A7 | `python3 -c "import py_compile; py_compile.compile('bus.py', doraise=True); py_compile.compile('authz.py', doraise=True)"` passes | ☐ |
| A8 | `from authz import authz, CallerContext, Policy` succeeds at module load | ☐ |
| A9 | F1-FU-1 regression test 9 in `test_inbox_read_authz.py` PASSES with `allow_director=True`; manually flip to `allow_director=False` in `bus.py` and verify test 9 FAILS (sanity check that the test pins the choice rather than vacuously passing) — then revert. Document the local-only verification in PR body. | ☐ |

---

## 5-gate review chain — MANDATORY (Tier-A auth-touching)

Per Director's directive 2026-05-06:

1. **AH2 static review** — feature-dev:code-reviewer agent — every file in the diff
2. **AH2 /security-review** — full pass over auth surface; report verdict in PR comment
3. **picker-architect review** — design fit + abstraction sanity (factory shape, Policy enum, CallerContext helpers); confirm the inline-boolean carve-outs in Edits 6+7 are warranted
4. **feature-dev:code-reviewer 2nd-pass** — after any review-driven changes
5. **AH1-T merges** — squash + delete branch + PL ship-report

Run reviews in **parallel** (all 4 reviewer agents in a single message) before requesting AH1-T merge.

---

## Files modified

| File | Change |
|------|--------|
| `authz.py` | NEW — Depends factory + CallerContext + Policy enum |
| `bus.py` | refactor 5 endpoints; remove `_require_worker_slug` + `_is_director` helpers; add `Depends`/`authz`/`CallerContext`/`Policy` imports; possibly drop `Header` from fastapi imports |
| `tests/test_authz_factory.py` | NEW — 22 factory matrix tests (4 AUTH_ONLY, 4 RECIPIENT+dir, 2 RECIPIENT no-dir, 1 misconfig, 11 CallerContext helpers) |
| `tests/test_inbox_read_authz.py` | extend — add test 9 (FU-1 regression); update docstring 8→9 |

## Do NOT touch

| File | Why |
|------|-----|
| `auth_lab.py` | slug-resolution + JWT primitives stay; we just consume them |
| Inner H7 chain in `_ratify_decision_inner` | full token-verify + jti-consume + parent FOR UPDATE is too entangled with the SQL transaction; out of scope |
| `app.py` | no surface-level changes |
| `migrations/` | pure code refactor, no schema change |
| `conftest.py` | env-loaded test keys already match the new factory's `auth_lab.resolve_terminal_key()` calls |
| `lifecycle.py`, `freeze.py`, `tier_classification.py` | unrelated |

## Quality checkpoints

1. After code edits, run `pytest -v` — note any new failures
2. Run `python3 -c "import py_compile; py_compile.compile('bus.py', doraise=True); py_compile.compile('authz.py', doraise=True)"` — must be clean
3. Run greps in A4/A5/A6 — confirm dead helpers and `Header` references are purged from authz code paths
4. Local sanity-check for AC A9: temporarily set `allow_director=False` on `GET /msg/{terminal}`'s `Depends(authz(...))` call, run test 9, confirm it FAILS, then revert. **Document** in PR body that this was done locally; don't commit the `False` flip.
5. Push branch + open PR; in PR body include: AC table marked ☑, the 5-gate review-chain checklist for the 4 reviewers + AH1-T merge gate
6. Tag PR with label `tier-a-auth-touching` and link to ClickUp tasks `86c9nnyvj` (FU-1) + `86c9nnywq` (FU-2)

## Ship-report (required on PR merge)

Standard B-code report at `briefs/_reports/B<N>_brisen_lab_authz_factory_1_<YYYYMMDD>.md` in baker-master after merge: PR number, merge commit, AC table all ☑, files modified, any in-flight observations, any V0.x amendments triggered by review feedback.

## Lessons applied

- **Function-signature verification** (Lesson #BRIEF-WRITER-OWNS-BUG): every code snippet in this brief was written after reading `bus.py` lines 66–959 + `auth_lab.py` lines 39–86 + `tests/conftest.py`; no signatures guessed.
- **Tier-A review chain** (Lesson #52): mandatory `/security-review` on auth-touching merges; bundled here with picker-architect for the abstraction-sanity check.
- **Test-pins-the-choice** (Lesson #PIN-NOT-VACUOUS): AC A9 explicitly verifies test 9 fails when the exemption is removed — defends against vacuous test that passes regardless of behavior under test.
- **In-place brief amendments** (Lesson learned 2026-05-06): if review chain produces fixes, fold V0.2 IN-PLACE at original sections + amendment block at bottom for audit trail. NOT append-only.
- **PEP 563 `from __future__ import annotations`** is already in `bus.py:24` — type hints stay strings; no import-time NameError on `Optional` etc. Keep the same convention in new `authz.py`.

---

**Branch:** `b2/brisen-lab-authz-factory-1`
**Mailbox:** `briefs/_tasks/CODE_2_PENDING.md` (this brief is the dispatch payload)
**Closes:** ClickUp `86c9nnyvj` (F1-FU-1) + `86c9nnywq` (F1-FU-2)
**Customer:** F2 brief (BRISEN_LAB_USER_PROMPT_SUBMIT_HOOK_WIRING_1 V0.7+) — will Depends on this factory for any new authz surfaces.
