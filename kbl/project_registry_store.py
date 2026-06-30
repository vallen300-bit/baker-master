"""PROJECT_NUMBER_REGISTRY_1 — human + machine project-number registry.

A project number is the single shared key across three surfaces:
  human (email subject / WhatsApp)  <->  this registry  <->  ClickUp Dispatcher.

Format: DESK-MATTER-###, e.g. BB-AUK-001. The DESK prefix is a desk classifier so
the responsible desk is known from the prefix alone, before any lookup.

Hard lane: a registered number (+ Box 5 auth binding) resolves here.
Soft lane (number forgotten): Box 5 combines >=2 independent signals; this module
supplies two of them — resolve_by_participant() and resolve_by_alias(). NEITHER is
sufficient alone (sender-only matching is forbidden — codex #4680); Box 5 owns the
multi-signal/no-conflict decision.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from kbl.db import get_conn
import kbl.slug_registry as slug_registry

logger = logging.getLogger("baker.project_registry")

# Desk-code -> desk-slug classifier map (first segment of DESK-MATTER-###).
# PLACEHOLDER values — confirm canonical desk slugs before non-pilot use.
# desk_owner stored per-row is authoritative; this map only validates the prefix.
DESK_CODES: dict[str, str] = {
    "BB": "baden-baden-desk",
    "AO": "ao-desk",
    "MOV": "movie-desk",
    "HAG": "hagenauer-desk",
    "BR": "brisen-desk",
    "ORIG": "origination-desk",
}

# Tolerant extractor for DESK-MATTER-###. First separator REQUIRED (disambiguates
# desk from matter); last separator optional (BB-AUK001 still matches). 2-4 letters
# per alpha segment, 1-4 digits. Requiring the structure keeps false positives
# (invoice#, dates, amounts) low — codex guardrail: regex shape alone never clears.
_NUMBER_RE = re.compile(r"\b([A-Za-z]{2,4})[\s\-_]([A-Za-z]{2,4})[\s\-_]?(\d{1,4})\b")


def _match_key(raw: str) -> str:
    """Normalise for tolerant lookup: uppercase, alnum-only.
    'BB-AUK-001' / 'bb auk 001' / 'BB-AUK001' all -> 'BBAUK001'."""
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def _desk_code_of(project_number: str) -> Optional[str]:
    m = _NUMBER_RE.match(project_number.strip())
    return m.group(1).upper() if m else None


def ensure_project_registry_table(conn: Any) -> None:
    """Idempotent boot — safe to call on every use; survives Render restart."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS project_registry (
                id              BIGSERIAL PRIMARY KEY,
                project_number  TEXT NOT NULL UNIQUE,
                match_key       TEXT NOT NULL UNIQUE,
                desk_code       TEXT NOT NULL,
                desk_owner      TEXT NOT NULL,
                matter_slug     TEXT NOT NULL,
                clickup_list_id TEXT,
                participants    JSONB NOT NULL DEFAULT '[]'::jsonb,
                aliases         JSONB NOT NULL DEFAULT '[]'::jsonb,
                status          TEXT NOT NULL DEFAULT 'active',
                created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT project_registry_status_check
                    CHECK (status IN ('active', 'retired'))
            )
            """
        )
    conn.commit()


def register_project(
    conn: Any,
    *,
    project_number: str,
    desk_owner: str,
    matter_slug: str,
    clickup_list_id: Optional[str] = None,
    participants: Optional[list[dict]] = None,
    aliases: Optional[list[str]] = None,
) -> str:
    """Insert/upsert a project. Returns the canonical project_number.
    Fails loud if matter_slug is not canonical, the format is wrong, or the desk
    prefix is unknown."""
    if not slug_registry.is_canonical(matter_slug):
        raise ValueError(f"matter_slug {matter_slug!r} is not canonical (slugs.yml)")
    if not _NUMBER_RE.match(project_number.strip()):
        raise ValueError(f"project_number {project_number!r} is not DESK-MATTER-### form")
    desk_code = _desk_code_of(project_number)
    if desk_code not in DESK_CODES:
        raise ValueError(f"unknown desk code {desk_code!r} (allowed: {sorted(DESK_CODES)})")

    key = _match_key(project_number)
    try:
        ensure_project_registry_table(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO project_registry
                    (project_number, match_key, desk_code, desk_owner, matter_slug,
                     clickup_list_id, participants, aliases, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
                ON CONFLICT (match_key) DO UPDATE SET
                    project_number  = EXCLUDED.project_number,
                    desk_code       = EXCLUDED.desk_code,
                    desk_owner      = EXCLUDED.desk_owner,
                    matter_slug     = EXCLUDED.matter_slug,
                    clickup_list_id = EXCLUDED.clickup_list_id,
                    participants    = EXCLUDED.participants,
                    aliases         = EXCLUDED.aliases,
                    updated_at      = NOW()
                """,
                (
                    project_number.strip().upper(), key, desk_code, desk_owner, matter_slug,
                    clickup_list_id,
                    json.dumps(participants or []),
                    json.dumps(aliases or []),
                ),
            )
        conn.commit()
        return project_number.strip().upper()
    except Exception:
        conn.rollback()
        raise


def _row_to_dict(row: tuple) -> dict:
    return {
        "project_number": row[0], "desk_code": row[1], "desk_owner": row[2],
        "matter_slug": row[3], "clickup_list_id": row[4],
        "participants": row[5], "aliases": row[6], "status": row[7],
    }


_SELECT = (
    "SELECT project_number, desk_code, desk_owner, matter_slug, clickup_list_id, "
    "participants, aliases, status FROM project_registry "
)


def resolve_project_number(text: str) -> Optional[dict]:
    """HARD LANE: extract DESK-MATTER-### codes from free text (subject/body) and
    return the first ACTIVE registered match, else None. A regex hit absent from
    the registry is rejected (false-positive guard — codex guardrail)."""
    if not text:
        return None
    keys = {_match_key(f"{m.group(1)}{m.group(2)}{m.group(3)}")
            for m in _NUMBER_RE.finditer(text)}
    if not keys:
        return None
    try:
        with get_conn() as conn:
            ensure_project_registry_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    _SELECT + "WHERE status = 'active' AND match_key = ANY(%s) LIMIT 1",
                    (list(keys),),
                )
                row = cur.fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning(f"resolve_project_number failed: {e}")
        return None


def resolve_by_participant(channel: str, value: str) -> list[dict]:
    """SOFT-LANE signal #1 (number forgotten): ACTIVE projects whose participant
    set contains {channel, value}. NEVER sufficient alone (sender-only forbidden)."""
    if not channel or not value:
        return []
    needle = json.dumps([{"channel": channel, "value": value}])
    try:
        with get_conn() as conn:
            ensure_project_registry_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    _SELECT + "WHERE status = 'active' AND participants @> %s::jsonb LIMIT 10",
                    (needle,),
                )
                rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"resolve_by_participant failed: {e}")
        return []


def resolve_by_alias(text: str) -> list[dict]:
    """SOFT-LANE signal #2: ACTIVE projects whose registered alias (matter
    mnemonic/nickname) appears as a word in the text. One of several independent
    signals Box 5 combines; NEVER sufficient alone. Bounded scan (200 active)."""
    if not text:
        return []
    hay = f" {text.lower()} "
    out: list[dict] = []
    try:
        with get_conn() as conn:
            ensure_project_registry_table(conn)
            with conn.cursor() as cur:
                cur.execute(_SELECT + "WHERE status = 'active' LIMIT 200")
                rows = cur.fetchall()
        for r in rows:
            for a in (r[6] or []):  # aliases JSONB
                a = (a or "").strip().lower()
                if a and f" {a} " in hay:
                    out.append(_row_to_dict(r))
                    break
    except Exception as e:
        logger.warning(f"resolve_by_alias failed: {e}")
    return out[:10]


def seed_bb_pilot(conn: Any) -> int:
    """Seed Baden-Baden pilot rows. Callable one-off; NOT auto-run. Returns count.
    matter_slug below is a PLACEHOLDER — confirm the canonical Aukera/Annaberg slug
    via slug_registry.canonical_slugs() before running."""
    rows = [
        dict(project_number="BB-AUK-001", desk_owner="baden-baden-desk",
             matter_slug="annaberg", clickup_list_id=None,
             participants=[{"channel": "email", "value": "balazs@brisengroup.com"}],
             aliases=["annaberg", "aukera annaberg"]),
    ]
    n = 0
    for r in rows:
        register_project(conn, **r)
        n += 1
    return n
