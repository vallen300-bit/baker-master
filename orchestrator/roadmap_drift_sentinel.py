"""ROADMAP_DRIFT_CLICKUP_SENTINEL_1 — daily 06:00 UTC drift detector.

Compares the most-recent commit timestamp on
``_ops/processes/cortex-roadmap-current.yml`` (baker-vault main) against PR
merge cadence on baker-vault + baker-master. If at least
``DRIFT_THRESHOLD`` PRs have merged since the YAML was last touched, posts
a comment on recurring ClickUp task ``86c9k6kau`` (Cortex Backlog list
``901523104264`` in BAKER space ``901510186446``).

Director rule 2026-04-30: NO Slack — ClickUp only. Silent on no-drift to
keep the noise floor low.

Auth surface (already provisioned for sibling sentinels):
  * ``GITHUB_TOKEN`` — same PAT used by ``vault_mirror`` for private repo
    cloning. Needed for both ``baker-vault`` and ``baker-master`` API reads.
  * ``CLICKUP_API_KEY`` — already used by ``clickup_client.ClickUpClient``.

Lock key registry: ``900900`` per ``BRIEF_LOCK_KEY_900300_COLLISION_1`` /
post B3 PR #108 conventions (renumbered ``initiative_engine`` to ``900800``).
Verified free at brief-author time; re-grep ``pg_try_advisory`` if
authoring a new sentinel after this one.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx

logger = logging.getLogger("sentinel.roadmap_drift")

# --- Tunables --------------------------------------------------------------

DRIFT_THRESHOLD: int = 5
ROADMAP_PATH: str = "_ops/processes/cortex-roadmap-current.yml"
VAULT_REPO: str = "vallen300-bit/baker-vault"
MASTER_REPO: str = "vallen300-bit/baker-master"
DRIFT_TASK_ID: str = "86c9k6kau"
ADVISORY_LOCK_KEY: int = 900900

_GH_BASE: str = "https://api.github.com"
_HTTP_TIMEOUT: float = 30.0
_PR_PAGE_SIZE: int = 100  # one page is enough — drift threshold is 5


# --- GitHub helpers --------------------------------------------------------


def _gh_headers() -> dict:
    """Return GitHub REST headers, with bearer token if available.

    ``GITHUB_TOKEN`` is the same PAT used by ``vault_mirror``. Public repo
    queries work without auth too, but baker-vault is private so the token
    is required there.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_iso8601_z(ts: str) -> datetime:
    """Parse GitHub's ``2026-04-29T17:24:51Z`` ISO 8601 timestamp."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def get_yaml_last_edit() -> Optional[dict]:
    """Most-recent commit affecting ``ROADMAP_PATH`` on baker-vault main.

    Returns a dict ``{"timestamp": datetime, "sha": str}`` or ``None`` on
    HTTP error / empty result. Caller treats ``None`` as a graceful no-op.
    """
    url = f"{_GH_BASE}/repos/{VAULT_REPO}/commits"
    params = {"path": ROADMAP_PATH, "sha": "main", "per_page": "1"}
    try:
        resp = httpx.get(
            url, headers=_gh_headers(), params=params, timeout=_HTTP_TIMEOUT
        )
        resp.raise_for_status()
        commits = resp.json()
    except Exception as e:
        logger.warning(
            "roadmap_drift: GitHub commit fetch failed (%s): %s", VAULT_REPO, e
        )
        return None

    if not commits:
        logger.warning(
            "roadmap_drift: no commits found for path=%s on %s",
            ROADMAP_PATH,
            VAULT_REPO,
        )
        return None

    head = commits[0]
    try:
        ts_str = head["commit"]["committer"]["date"]
        sha = head.get("sha", "?")
        return {"timestamp": _parse_iso8601_z(ts_str), "sha": sha[:7]}
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(
            "roadmap_drift: malformed GitHub commit payload: %s", e
        )
        return None


def list_merged_prs_since(repo: str, since: datetime) -> Optional[List[dict]]:
    """List PRs on ``repo``'s ``main`` with ``merged_at`` strictly after ``since``.

    Returns a list of ``{"number": int, "title": str}`` (newest first), or
    ``None`` on HTTP error so the caller can treat the whole detection cycle
    as "fetch failed" and skip the ClickUp write.

    Single-page query (100 PRs sorted by updated desc). With a 5-PR drift
    threshold, that's more than enough — even a months-stale YAML produces
    DRIFT correctly because 100 ≥ 5.
    """
    url = f"{_GH_BASE}/repos/{repo}/pulls"
    params = {
        "state": "closed",
        "base": "main",
        "sort": "updated",
        "direction": "desc",
        "per_page": str(_PR_PAGE_SIZE),
    }
    try:
        resp = httpx.get(
            url, headers=_gh_headers(), params=params, timeout=_HTTP_TIMEOUT
        )
        resp.raise_for_status()
        prs = resp.json()
    except Exception as e:
        logger.warning("roadmap_drift: GitHub PR list failed (%s): %s", repo, e)
        return None

    merged: List[dict] = []
    for pr in prs:
        merged_at = pr.get("merged_at")
        if not merged_at:
            continue  # closed-without-merge PRs
        try:
            merged_dt = _parse_iso8601_z(merged_at)
        except ValueError:
            continue
        if merged_dt > since:
            merged.append(
                {"number": pr.get("number"), "title": pr.get("title", "")}
            )
    return merged


# --- Comment formatting ----------------------------------------------------


def format_drift_comment(
    yaml_dt: datetime,
    yaml_sha: str,
    vault_prs: List[dict],
    master_prs: List[dict],
    *,
    now: Optional[datetime] = None,
) -> str:
    """Compose the ClickUp comment body. Pure function, easy to unit-test."""
    if now is None:
        now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    yaml_str = yaml_dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(vault_prs) + len(master_prs)

    def _fmt(prs: List[dict]) -> str:
        if not prs:
            return "  (none)"
        return "\n".join(
            f"  - #{p.get('number')} {p.get('title', '')}" for p in prs
        )

    return (
        f"Drift detected {now_str}.\n"
        f"YAML last edit: {yaml_str} on {yaml_sha}\n"
        f"PRs merged since:\n"
        f"- baker-vault:\n{_fmt(vault_prs)}\n"
        f"- baker-master:\n{_fmt(master_prs)}\n"
        f"Total: {total} PRs without YAML update."
    )


# --- ClickUp write ---------------------------------------------------------


def _post_clickup_comment(body: str) -> bool:
    """Post ``body`` to ``DRIFT_TASK_ID``. Logs + swallows failures."""
    try:
        from clickup_client import ClickUpClient
    except Exception as e:
        logger.error("roadmap_drift: ClickUpClient import failed: %s", e)
        return False
    try:
        client = ClickUpClient._get_global_instance()
        result = client.post_comment(DRIFT_TASK_ID, body)
    except Exception as e:
        logger.warning("roadmap_drift: post_comment raised: %s", e)
        return False
    if result is None:
        logger.warning(
            "roadmap_drift: post_comment returned None (HTTP error or write-cap reached)"
        )
        return False
    return True


# --- Sentinel-health reporting --------------------------------------------


def _report_success(payload: dict) -> None:
    try:
        from triggers.sentinel_health import report_success
        report_success("roadmap_drift_sentinel", payload)
    except Exception:
        pass


def _report_failure(reason: str) -> None:
    try:
        from triggers.sentinel_health import report_failure
        report_failure("roadmap_drift_sentinel", reason)
    except Exception:
        pass


# --- Main entry point ------------------------------------------------------


def run_roadmap_drift_sentinel() -> dict:
    """APScheduler entry point — fires daily at 06:00 UTC.

    Status dict for observability:
        ``{"status": "no_drift" | "drift" | "yaml_fetch_failed"
                     | "pr_fetch_failed" | "skipped",
           "pr_count": int, "comment_posted": bool}``

    Never raises — all paths log + return so a single bad day cannot
    knock the scheduler over. Mirrors the ``_ai_head_weekly_audit_job``
    contract.
    """
    # Advisory lock — defensive belt-and-suspenders. The global scheduler
    # singleton (triggers/scheduler_lease.py) already prevents two
    # processes from firing the cron tick simultaneously; this xact lock
    # adds a second gate inside Postgres so a misconfigured override
    # (e.g., manual ``run_roadmap_drift_sentinel()`` invocation while the
    # cron tick fires) cannot double-write.
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
    except Exception as e:
        logger.error("roadmap_drift: store_back import failed: %s", e)
        _report_failure(f"store_back import: {e}")
        return {"status": "skipped", "reason": "store_back_import"}

    conn = None
    try:
        conn = store._get_conn()
    except Exception as e:
        logger.warning("roadmap_drift: _get_conn raised: %s", e)
    if not conn:
        logger.warning("roadmap_drift: no DB conn — skipping advisory lock")
        _report_failure("no_db_conn")
        return {"status": "skipped", "reason": "no_db_conn"}

    try:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT pg_try_advisory_xact_lock(%s)", (ADVISORY_LOCK_KEY,)
            )
            row = cur.fetchone()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning(
                "roadmap_drift: advisory lock query failed: %s", e
            )
            _report_failure(f"advisory_lock: {e}")
            return {"status": "skipped", "reason": "advisory_lock_error"}

        got_lock = bool(row and (row[0] if not isinstance(row, dict) else row.get("pg_try_advisory_xact_lock")))
        if not got_lock:
            logger.info(
                "roadmap_drift: advisory lock 900900 contended — another instance running, skipping"
            )
            return {"status": "skipped", "reason": "lock_contended"}
    finally:
        try:
            store._put_conn(conn)
        except Exception:
            pass

    # Fetch YAML last-edit
    yaml_meta = get_yaml_last_edit()
    if yaml_meta is None:
        _report_failure("yaml_fetch_failed")
        return {"status": "yaml_fetch_failed", "comment_posted": False}

    yaml_dt: datetime = yaml_meta["timestamp"]
    yaml_sha: str = yaml_meta["sha"]

    # Fetch PR lists for both repos (independent failures handled separately)
    vault_prs = list_merged_prs_since(VAULT_REPO, yaml_dt)
    master_prs = list_merged_prs_since(MASTER_REPO, yaml_dt)
    if vault_prs is None or master_prs is None:
        _report_failure("pr_fetch_failed")
        return {"status": "pr_fetch_failed", "comment_posted": False}

    pr_count = len(vault_prs) + len(master_prs)
    logger.info(
        "roadmap_drift: yaml_last_edit=%s sha=%s vault_prs=%d master_prs=%d total=%d threshold=%d",
        yaml_dt.isoformat(),
        yaml_sha,
        len(vault_prs),
        len(master_prs),
        pr_count,
        DRIFT_THRESHOLD,
    )

    if pr_count < DRIFT_THRESHOLD:
        _report_success(
            {"status": "no_drift", "pr_count": pr_count}
        )
        return {
            "status": "no_drift",
            "pr_count": pr_count,
            "comment_posted": False,
        }

    # Drift detected — write comment
    body = format_drift_comment(yaml_dt, yaml_sha, vault_prs, master_prs)
    posted = _post_clickup_comment(body)
    if posted:
        _report_success(
            {"status": "drift", "pr_count": pr_count, "comment_posted": True}
        )
    else:
        _report_failure("clickup_post_failed")
    return {
        "status": "drift",
        "pr_count": pr_count,
        "comment_posted": posted,
    }
