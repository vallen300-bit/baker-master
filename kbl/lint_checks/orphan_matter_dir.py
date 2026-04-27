"""Check 3 — orphan_matter_dir (warn, hybrid: filesystem + Postgres).

Flags matter dirs that have BOTH:
  * indegree=0 in the wiki cross-ref graph, AND
  * no signal in `signal_queue.primary_matter` within the past
    ``WIKI_LINT_ORPHAN_DAYS`` (default 90).

DDL drift note (LONGTERM.md rule): the spec named
``email_messages.primary_matter`` / ``meeting_transcripts.primary_matter`` /
``whatsapp_messages.primary_matter`` as inputs. Production schema only
has ``signal_queue.primary_matter`` (verified 2026-04-26 via
``information_schema.columns``). All inbound signals for KBL classify
through ``signal_queue`` — using it as the canonical "matter has been
touched recently" surface. The original three tables remain a V2 if the
DDL changes.

The PG query is fault-tolerant: any DB failure logs a warning and the
check returns the indegree-only subset (no orphan blocked by a transient
DB outage).

Tests inject ``signal_last_seen`` directly via ``registries`` — no live
DB call from pytest.
"""
from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path

from . import _common as C
from .one_way_cross_ref import _edges_from

logger = logging.getLogger("kbl.wiki_lint.orphan")

CHECK_NAME = "orphan_matter_dir"


def _query_signal_last_seen(slugs: list[str]) -> dict[str, _dt.datetime]:
    """Return {slug: max(created_at)} for given slugs in signal_queue.

    Returns ``{}`` on any failure (DB unreachable, schema drift). Caller
    treats absence as "no recent signal" → eligible for orphan flag.
    """
    if not slugs:
        return {}
    try:
        from kbl.db import get_conn
    except Exception as exc:
        logger.warning("orphan_matter_dir: cannot import kbl.db (%s)", exc)
        return {}
    try:
        with get_conn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT primary_matter, MAX(created_at)
                          FROM signal_queue
                         WHERE primary_matter = ANY(%s)
                         GROUP BY primary_matter
                        """,
                        (slugs,),
                    )
                    rows = cur.fetchall() or []
            except Exception:
                conn.rollback()
                raise
    except Exception as exc:
        logger.warning("orphan_matter_dir: signal_queue query failed: %s", exc)
        return {}
    return {r[0]: r[1] for r in rows if r[0] is not None and r[1] is not None}


def run(vault_path: Path, registries: dict) -> list[C.LintHit]:
    matters = C.discover_matter_dirs(vault_path)
    if not matters:
        return []
    slugs = {m.slug for m in matters}
    edges = _edges_from(matters, slugs)

    indegree: dict[str, int] = {s: 0 for s in slugs}
    for _src, dsts in edges.items():
        for d in dsts:
            indegree[d] = indegree.get(d, 0) + 1

    days = int(registries.get("orphan_days", 90))
    now = registries.get("now_utc")
    if isinstance(now, str):
        now = _dt.datetime.fromisoformat(now)
    elif now is None:
        now = _dt.datetime.utcnow()
    cutoff = now - _dt.timedelta(days=days)

    last_seen = registries.get("signal_last_seen")
    if last_seen is None:
        last_seen = _query_signal_last_seen(sorted(slugs))

    by_slug = {m.slug: m for m in matters}
    hits: list[C.LintHit] = []
    for slug, deg in indegree.items():
        if deg > 0:
            continue
        seen = last_seen.get(slug)
        if seen is not None:
            # Normalize tz: strip awareness so naive vs aware compare safely.
            if hasattr(seen, "tzinfo") and seen.tzinfo is not None:
                seen = seen.replace(tzinfo=None)
            if seen > cutoff:
                continue
        m = by_slug.get(slug)
        if m is None:
            continue
        seen_repr = seen.date().isoformat() if seen is not None else "never"
        hits.append(C.LintHit(
            check=CHECK_NAME,
            severity=C.Severity.WARN,
            path=m.rel,
            line=None,
            message=f"orphan: indegree=0 and last signal_queue activity {seen_repr} (>{days}d)",
        ))
    return hits
