"""Pytest shared fixtures for Baker tests.

Primary purpose: unify ``TEST_DATABASE_URL``-gated live-PG tests behind a
single ``needs_live_pg`` fixture that resolves a live-PG URL from either:

  1. ``TEST_DATABASE_URL`` env — operator override (local dev, manual runs).
  2. An ephemeral Neon branch auto-provisioned per pytest session when
     ``NEON_API_KEY`` + ``NEON_PROJECT_ID`` are both set (typically CI).
  3. ``pytest.skip`` — neither set; preserves today's skip-by-default
     behavior.

Closes lessons #35 + #42: live-PG round-trip tests previously ran only
locally, never in CI. The ephemeral Neon branch (copy-on-write, free
within plan limits) is created at session start, torn down at session end.

Design notes
------------

* Session-scoped fixture — branch creation is ~5-15s overhead; we eat it
  once per session and share across every live-PG test.
* Opaque URL — tests do not care whether the URL came from operator env
  or the fixture. Only this module knows.
* Fail loud on Neon API errors except at teardown. Trust marker from
  lesson #40: silent None return would hide CI breakage; we only yield
  None when BOTH env vars are absent (by-design skip path).
* No external Neon SDK — plain ``urllib.request`` keeps the dependency
  surface at zero. Matches repo convention of direct ``psycopg2`` / HTTP
  calls over ORMs.
"""
from __future__ import annotations

import json
import logging
import os
import random
import string
import time
import typing as t
import urllib.error
import urllib.parse
import urllib.request

import pytest

logger = logging.getLogger(__name__)

_NEON_API_ROOT = "https://console.neon.tech/api/v2"
_BRANCH_READY_TIMEOUT_S = 60.0
_BRANCH_POLL_INTERVAL_S = 2.0
_HTTP_TIMEOUT_S = 30.0
_DEFAULT_DB_NAME = "neondb"
_DEFAULT_ROLE_NAME = "neondb_owner"


def _rand_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _neon_request(
    method: str,
    path: str,
    api_key: str,
    body: t.Optional[dict] = None,
) -> dict:
    """Issue a Neon REST API call; raise with status + body on non-2xx."""
    url = f"{_NEON_API_ROOT}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="replace")
        raise RuntimeError(
            f"Neon API {method} {path} failed: HTTP {e.code} — {body_txt[:400]}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Neon API {method} {path} network error: {e.reason}"
        ) from e


def _wait_for_endpoint_active(
    api_key: str,
    project_id: str,
    endpoint_id: str,
    deadline: float,
) -> dict:
    """Poll the endpoint until ``current_state`` is ``active``; raise on timeout."""
    last_state = None
    while time.monotonic() < deadline:
        resp = _neon_request(
            "GET",
            f"/projects/{project_id}/endpoints/{endpoint_id}",
            api_key,
        )
        endpoint = resp.get("endpoint", {})
        state = endpoint.get("current_state")
        last_state = state
        if state == "active":
            return endpoint
        time.sleep(_BRANCH_POLL_INTERVAL_S)
    raise RuntimeError(
        f"Neon endpoint {endpoint_id} did not reach 'active' within "
        f"{_BRANCH_READY_TIMEOUT_S}s (last_state={last_state!r})"
    )


def _build_connection_uri(
    api_key: str,
    project_id: str,
    branch_id: str,
    endpoint_id: str,
) -> str:
    """Ask Neon for the canonical psycopg2 URI for the branch+endpoint."""
    db_name = os.environ.get("NEON_DATABASE_NAME", _DEFAULT_DB_NAME)
    role_name = os.environ.get("NEON_ROLE_NAME", _DEFAULT_ROLE_NAME)
    qs = urllib.parse.urlencode(
        {
            "branch_id": branch_id,
            "endpoint_id": endpoint_id,
            "database_name": db_name,
            "role_name": role_name,
        }
    )
    resp = _neon_request(
        "GET", f"/projects/{project_id}/connection_uri?{qs}", api_key
    )
    uri = resp.get("uri")
    if not uri:
        raise RuntimeError(
            f"Neon connection_uri response missing 'uri' key: {resp!r}"
        )
    return uri


@pytest.fixture(scope="session")
def ephemeral_neon_db() -> t.Iterator[t.Optional[str]]:
    """Provision an ephemeral Neon branch for the pytest session.

    Yields the psycopg2-compatible connection URL when both ``NEON_API_KEY``
    and ``NEON_PROJECT_ID`` are set, otherwise yields ``None`` (skip path).

    Teardown drops the branch; 404/410 at teardown is logged and swallowed
    (idempotent — branch was already gone).
    """
    api_key = os.environ.get("NEON_API_KEY")
    project_id = os.environ.get("NEON_PROJECT_ID")
    if not api_key or not project_id:
        # By-design skip path — tests fall back to TEST_DATABASE_URL or skip.
        yield None
        return

    branch_name = f"ci-pytest-{_rand_suffix()}"
    logger.info(
        "ephemeral_neon_db: creating branch %s on project %s",
        branch_name,
        project_id,
    )

    create_resp = _neon_request(
        "POST",
        f"/projects/{project_id}/branches",
        api_key,
        body={
            "branch": {"name": branch_name},
            # Ask Neon to provision a read-write endpoint alongside the branch
            # so we do not need a second round-trip to attach one.
            "endpoints": [{"type": "read_write"}],
        },
    )
    branch = create_resp.get("branch") or {}
    branch_id = branch.get("id")
    endpoints = create_resp.get("endpoints") or []
    if not branch_id or not endpoints:
        raise RuntimeError(
            f"Neon create-branch response missing branch.id or endpoints: "
            f"{create_resp!r}"
        )
    endpoint_id = endpoints[0]["id"]

    try:
        deadline = time.monotonic() + _BRANCH_READY_TIMEOUT_S
        _wait_for_endpoint_active(api_key, project_id, endpoint_id, deadline)
        conn_uri = _build_connection_uri(
            api_key, project_id, branch_id, endpoint_id
        )
        logger.info("ephemeral_neon_db: branch %s ready", branch_name)
        yield conn_uri
    finally:
        logger.info("ephemeral_neon_db: dropping branch %s", branch_name)
        try:
            _neon_request(
                "DELETE",
                f"/projects/{project_id}/branches/{branch_id}",
                api_key,
            )
        except RuntimeError as e:
            msg = str(e)
            if "HTTP 404" in msg or "HTTP 410" in msg:
                logger.warning(
                    "ephemeral_neon_db: branch %s already gone at teardown",
                    branch_name,
                )
            else:
                # Don't re-raise in teardown — surfaces as CI log noise, not
                # test correctness failure. Branch cleanup is best-effort; if
                # it genuinely leaks, Neon's max-branches limit will surface
                # it on the next run and the operator will investigate.
                logger.error(
                    "ephemeral_neon_db: teardown error for %s: %s",
                    branch_name,
                    e,
                )


@pytest.fixture
def needs_live_pg(ephemeral_neon_db: t.Optional[str]) -> str:
    """Return a live-PG URL for a test to connect to, or skip.

    Resolution order:
      1. ``TEST_DATABASE_URL`` env (operator override).
      2. ``ephemeral_neon_db`` (session-scoped CI-provisioned branch).
      3. ``pytest.skip`` — neither available.

    Tests that used the old ``TEST_DB_URL = os.environ.get(...)`` +
    ``pytest.mark.skipif(not TEST_DB_URL, ...)`` pattern just add
    ``needs_live_pg`` as a function parameter and use it in place of the
    module-level constant.
    """
    override = os.environ.get("TEST_DATABASE_URL")
    if override:
        return override
    if ephemeral_neon_db:
        return ephemeral_neon_db
    pytest.skip(
        "neither TEST_DATABASE_URL nor NEON_API_KEY+NEON_PROJECT_ID set — "
        "live-PG round-trip test skipped"
    )
