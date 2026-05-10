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


# ============================================================================
# CORTEX_TIER_B_RUNTIME_V1 — Tier B test scaffolding
# ============================================================================
#
# Pattern: each Tier-B test function takes ``tier_b_test_store`` (which sets
# up the schema + monkeypatches SentinelStoreBack._get_global_instance and
# TierBRuntime._instance) plus the seed/registry helpers it needs. All
# helpers gate on ``needs_live_pg`` so the suite skips cleanly when no DB
# is available.


def _bootstrap_tier_b_schema(dsn: str) -> None:
    """Bootstrap the minimal Tier-B schema directly against the live-PG DSN.

    The repo's full ``run_pending_migrations`` chain assumes Python bootstrap
    methods (``SentinelStoreBack._ensure_*``) have already created base tables
    like ``signal_queue``. For Tier-B tests we only need ``baker_actions`` +
    the three ``tier_b_*`` tables + the seed registry, so we inline the same
    DDL the bootstrap (and the matching migration) would emit.

    Idempotent — safe to call against a partially-populated DB.
    """
    import psycopg2

    ddl_blocks = [
        # baker_actions — full bootstrap shape (mirrors store_back.py
        # _ensure_clickup_tables + the additive ALTER from
        # migrations/20260510_baker_actions_tier_b_runtime.sql).
        """
        CREATE TABLE IF NOT EXISTS baker_actions (
            id SERIAL PRIMARY KEY,
            action_type TEXT NOT NULL,
            target_task_id TEXT,
            target_space_id TEXT,
            payload JSONB,
            trigger_source TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            success BOOLEAN DEFAULT TRUE,
            error_message TEXT,
            tier TEXT,
            cost_eur NUMERIC(12, 2),
            committed_at TIMESTAMPTZ,
            committer_agent TEXT,
            action_class TEXT,
            self_cost_eur NUMERIC(12, 2),
            reserved_at TIMESTAMPTZ
        )
        """,
        """
        ALTER TABLE baker_actions
            ADD COLUMN IF NOT EXISTS tier TEXT,
            ADD COLUMN IF NOT EXISTS cost_eur NUMERIC(12, 2),
            ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS committer_agent TEXT,
            ADD COLUMN IF NOT EXISTS action_class TEXT,
            ADD COLUMN IF NOT EXISTS self_cost_eur NUMERIC(12, 2),
            ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_committed
            ON baker_actions (committed_at)
            WHERE tier = 'B' AND cost_eur IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_reserved
            ON baker_actions (reserved_at)
            WHERE tier = 'B' AND cost_eur IS NOT NULL AND committed_at IS NULL
        """,
        """
        CREATE TABLE IF NOT EXISTS tier_b_action_classes (
            id SERIAL PRIMARY KEY,
            class_name TEXT NOT NULL UNIQUE,
            eur_cost NUMERIC(12, 2) NOT NULL,
            description TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            deprecated_at TIMESTAMPTZ
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tier_b_pending (
            id SERIAL PRIMARY KEY,
            action_payload JSONB NOT NULL,
            cost_eur NUMERIC(12, 2) NOT NULL,
            action_class TEXT NOT NULL,
            committer_agent TEXT NOT NULL,
            reason_paused TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ratified_at TIMESTAMPTZ,
            ratified_by TEXT,
            decision_payload JSONB,
            expired_at TIMESTAMPTZ,
            CONSTRAINT tier_b_pending_status_check
                CHECK (status IN ('pending', 'ratified', 'rejected', 'expired'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tier_b_pending_status
            ON tier_b_pending (status, created_at)
        """,
        """
        CREATE TABLE IF NOT EXISTS tier_b_counter_resets (
            id SERIAL PRIMARY KEY,
            reset_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            period_label TEXT NOT NULL,
            final_day_total NUMERIC(12, 2),
            final_month_total NUMERIC(12, 2),
            actions_count INTEGER
        )
        """,
        # Seed the registry (mirrors migration step 5).
        """
        INSERT INTO tier_b_action_classes (class_name, eur_cost, description)
        VALUES
            ('render.deploy.web_service.starter',  7.00,  'test-seed'),
            ('render.deploy.web_service.standard', 25.00, 'test-seed'),
            ('render.env.flip',                    0.00,  'test-seed'),
            ('vendor.subscription.monthly',        50.00, 'test-seed'),
            ('test.synthetic',                     1.00,  'test-seed')
        ON CONFLICT (class_name) DO NOTHING
        """,
    ]

    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor()
        for ddl in ddl_blocks:
            cur.execute(ddl)
        conn.commit()
        cur.close()
    finally:
        conn.close()


class _TestStore:
    """Minimal SentinelStoreBack shim for Tier-B tests.

    Exposes ``_get_conn`` / ``_put_conn`` against the test DSN. Each call
    returns a fresh psycopg2 connection so the SERIALIZABLE-isolation set
    by ``TierBRuntime.enforce()`` doesn't leak into helper queries.
    """

    def __init__(self, dsn: str):
        import psycopg2  # local import keeps test-only dep out of module load

        self._dsn = dsn
        self._psycopg2 = psycopg2

    def _get_conn(self):
        return self._psycopg2.connect(self._dsn)

    def _put_conn(self, conn) -> None:
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


# Capture the REAL ``memory.store_back`` module + its ``SentinelStoreBack``
# class at conftest-collection time. Some other test (e.g.
# ``test_ai_head_weekly_audit``) replaces ``sys.modules['memory.store_back']``
# with a MagicMock and never restores it; without these hard handles, a fresh
# ``import memory.store_back`` inside a later fixture would resolve to the
# mock. Binding here while sys.modules is still clean gives us stable
# references regardless of test order.
import memory.store_back as _REAL_STORE_BACK_MOD  # noqa: E402

_REAL_SENTINEL_STORE_BACK = _REAL_STORE_BACK_MOD.SentinelStoreBack


@pytest.fixture
def tier_b_test_store(needs_live_pg, monkeypatch):
    """Bootstrap Tier-B schema + redirect Tier-B runtime singleton to the test DB.

    Yields a ``_TestStore`` instance. After the fixture exits, the
    ``TierBRuntime._instance`` cache, the ``SentinelStoreBack`` monkeypatch,
    and the ``sys.modules`` restoration all unwind via pytest.
    """
    _bootstrap_tier_b_schema(needs_live_pg)

    # Force ``sys.modules['memory.store_back']`` to the real module for this
    # test, in case an earlier test left a MagicMock in its place. Endpoints
    # and other call-sites that re-import inside their function bodies will
    # then resolve to the real class.
    import sys

    monkeypatch.setitem(sys.modules, "memory.store_back", _REAL_STORE_BACK_MOD)

    store = _TestStore(needs_live_pg)

    from orchestrator import tier_b_runtime as tbr

    monkeypatch.setattr(
        _REAL_SENTINEL_STORE_BACK,
        "_get_global_instance",
        classmethod(lambda cls: store),
    )
    # Force a fresh TierBRuntime that reads the patched singleton.
    monkeypatch.setattr(tbr.TierBRuntime, "_instance", None)
    yield store
    # Reset singleton after the test so suite ordering doesn't leak state.
    tbr.TierBRuntime._instance = None


@pytest.fixture
def clean_baker_actions(tier_b_test_store):
    """Truncate ``baker_actions`` + ``tier_b_pending`` + ``tier_b_counter_resets``.

    Action-class registry is preserved (5 seed rows from the migration);
    individual tests can ``register_class`` more.
    """
    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE baker_actions RESTART IDENTITY CASCADE")
        cur.execute("TRUNCATE TABLE tier_b_pending RESTART IDENTITY CASCADE")
        cur.execute("TRUNCATE TABLE tier_b_counter_resets RESTART IDENTITY CASCADE")
        conn.commit()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    return tier_b_test_store


@pytest.fixture
def register_class(tier_b_test_store):
    """Insert (or upsert) an action class into ``tier_b_action_classes``."""

    def _register(class_name: str, eur_cost: float, description: str = "test"):
        conn = tier_b_test_store._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO tier_b_action_classes (class_name, eur_cost, description)
                VALUES (%s, %s, %s)
                ON CONFLICT (class_name) DO UPDATE
                    SET eur_cost = EXCLUDED.eur_cost,
                        description = EXCLUDED.description,
                        deprecated_at = NULL
                """,
                (class_name, eur_cost, description),
            )
            conn.commit()
            cur.close()
        finally:
            tier_b_test_store._put_conn(conn)

    return _register


def _seed_committed(
    store,
    *,
    class_name: str,
    eur_cost: float,
    count: int,
    agent: str,
    when_sql: str,
):
    """Insert ``count`` Tier-B baker_actions rows with a fixed cost + agent.

    ``when_sql`` is a SQL fragment that resolves to a timestamptz used for
    ``committed_at``. Caller is responsible for any range/offset.
    """
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.executemany(
            f"""
            INSERT INTO baker_actions
                (action_type, payload, tier, cost_eur, committed_at,
                 committer_agent, action_class)
            VALUES ('tier_b_test', '{{}}'::jsonb, 'B', %s, {when_sql}, %s, %s)
            """,
            [(eur_cost, agent, class_name) for _ in range(count)],
        )
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)


@pytest.fixture
def seed_committed_today(tier_b_test_store):
    """Seed N committed Tier-B rows with ``committed_at = NOW() AT TIME ZONE 'UTC'``."""

    def _seed(class_name: str, count: int, agent: str, eur_cost: float):
        _seed_committed(
            tier_b_test_store,
            class_name=class_name,
            eur_cost=eur_cost,
            count=count,
            agent=agent,
            when_sql="NOW() AT TIME ZONE 'UTC'",
        )

    return _seed


@pytest.fixture
def seed_committed_this_month(tier_b_test_store):
    """Seed N committed Tier-B rows with ``committed_at`` early in current month."""

    def _seed(class_name: str, count: int, agent: str, eur_cost: float):
        _seed_committed(
            tier_b_test_store,
            class_name=class_name,
            eur_cost=eur_cost,
            count=count,
            agent=agent,
            when_sql="DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC') + INTERVAL '1 hour'",
        )

    return _seed


@pytest.fixture
def seed_committed_last_month(tier_b_test_store):
    """Seed one committed Tier-B row of given total in the prior calendar month."""

    def _seed(class_name: str, total_eur: float, agent: str = "ah1"):
        _seed_committed(
            tier_b_test_store,
            class_name=class_name,
            eur_cost=total_eur,
            count=1,
            agent=agent,
            when_sql="DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC') - INTERVAL '5 days'",
        )

    return _seed
