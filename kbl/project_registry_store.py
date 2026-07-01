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
# The desk prefix is the routing authority (see module docstring): desk_owner
# MUST equal DESK_CODES[prefix] — a contradicting desk_owner is rejected, never
# silently stored, so a BB number can never be owned by a non-BB desk.
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
    # fullmatch (not match): trailing text/junk must be rejected, never stored —
    # else 'BB-AUK-001 extra' would persist with a match_key the hard lane (which
    # keys off the DESK/MATTER/digit groups) could never reach.
    m = _NUMBER_RE.fullmatch(project_number.strip())
    if m is None:
        raise ValueError(f"project_number {project_number!r} is not DESK-MATTER-### form")
    desk_code = m.group(1).upper()
    if desk_code not in DESK_CODES:
        raise ValueError(f"unknown desk code {desk_code!r} (allowed: {sorted(DESK_CODES)})")
    # Prefix is the routing authority — desk_owner must not contradict it.
    expected_owner = DESK_CODES[desk_code]
    if desk_owner != expected_owner:
        raise ValueError(
            f"desk_owner {desk_owner!r} contradicts desk prefix {desk_code!r} "
            f"(prefix routes to {expected_owner!r}); the prefix is authoritative"
        )

    # Canonicalize the stored display form + match_key from the matched groups so
    # they always round-trip: display 'BB-AUK-001' <-> match_key 'BBAUK001'. The
    # hard lane keys off the same groups, so a tolerant input ('BB-AUK001') still
    # resolves to its canonical row.
    canonical_number = f"{m.group(1)}-{m.group(2)}-{m.group(3)}".upper()
    key = _match_key(canonical_number)
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
                    canonical_number, key, desk_code, desk_owner, matter_slug,
                    clickup_list_id,
                    json.dumps(participants or []),
                    json.dumps(aliases or []),
                ),
            )
        conn.commit()
        return canonical_number
    except Exception:
        conn.rollback()
        raise


def _as_list(v: Any) -> list:
    """Normalise a JSONB column to a list. psycopg2's default jsonb typecaster
    returns parsed Python objects, but normalise defensively: None -> [], a str is
    json-decoded (keeps reads correct if the global jsonb caster is ever unset —
    otherwise ``for a in "<str>"`` would iterate characters), anything non-list
    -> []. Self-audit (codex G3 re-gate#2): JSONB shape on read."""
    if v is None:
        return []
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return v if isinstance(v, list) else []


def _row_to_dict(row: tuple) -> dict:
    return {
        "project_number": row[0], "desk_code": row[1], "desk_owner": row[2],
        "matter_slug": row[3], "clickup_list_id": row[4],
        "participants": _as_list(row[5]), "aliases": _as_list(row[6]),
        "status": row[7],
    }


_SELECT = (
    "SELECT project_number, desk_code, desk_owner, matter_slug, clickup_list_id, "
    "participants, aliases, status FROM project_registry "
)

# Hard lane needs each row's match_key (trailing, index 8) to map a DB hit back to
# its position in the text-ordered key list (F4 determinism). _row_to_dict reads
# indices 0-7 only, so the extra column is harmless to it.
_HARD_SELECT = (
    "SELECT project_number, desk_code, desk_owner, matter_slug, clickup_list_id, "
    "participants, aliases, status, match_key FROM project_registry "
)


def resolve_project_number(text: str) -> Optional[dict]:
    """HARD LANE: extract DESK-MATTER-### codes from free text (subject/body) and
    return the first registered ACTIVE match in TEXT ORDER, else None.

    When several registered numbers appear, the earliest-occurring one wins,
    deterministically — a regex hit absent from the registry is skipped (so the
    first *registered* match is returned, not merely the first regex hit). Conflict
    detection across multiple registered numbers is Box 5's responsibility
    (downstream), not this primitive's. A regex hit absent from the registry is
    rejected as a clearance (false-positive guard — codex guardrail).

    F4 (codex G3 re-gate#2): the prior version collected keys into a set (lost text
    order) and used ``LIMIT 1`` with no ORDER BY, so multi-number text resolved
    non-deterministically. Now keys preserve first-occurrence order and the winner
    is chosen in Python by smallest text index."""
    if not text:
        return None
    # Ordered, de-duped match keys — preserve first-occurrence text order.
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for m in _NUMBER_RE.finditer(text):
        k = _match_key(f"{m.group(1)}{m.group(2)}{m.group(3)}")
        if k and k not in seen:
            seen.add(k)
            ordered_keys.append(k)
    if not ordered_keys:
        return None
    try:
        with get_conn() as conn:
            ensure_project_registry_table(conn)
            with conn.cursor() as cur:
                # match_key is UNIQUE, so at most len(ordered_keys) rows match;
                # LIMIT len keeps the query bounded without ever truncating a hit.
                cur.execute(
                    _HARD_SELECT
                    + "WHERE status = 'active' AND match_key = ANY(%s) LIMIT %s",
                    (ordered_keys, len(ordered_keys)),
                )
                rows = cur.fetchall()
        if not rows:
            return None
        by_key = {r[8]: r for r in rows}  # r[8] = match_key (unique)
        for k in ordered_keys:
            r = by_key.get(k)
            if r is not None:
                return _row_to_dict(r)
        return None
    except Exception as e:
        logger.warning(f"resolve_project_number failed: {e}")
        return None


def extract_project_codes(text: str) -> list[str]:
    """Conflict pre-check primitive (F4): DISTINCT valid-SHAPED DESK-MATTER-### codes
    in first-occurrence text order. PURE regex — reuses the module-level ``_NUMBER_RE``,
    NO registry/DB hit and no second compiled pattern.

    Box 5's hard fast lane calls this FIRST: ``>1`` distinct code => cross-matter
    CONFLICT => do NOT fast-board (route to full desk TICKET). Canonical upper form
    ('BB-AUK-001') matches ``register_project``'s stored display, so 'bb auk 001' and
    'BB-AUK001' collapse to one code. Regex shape ALONE never clears (#4679.3) — the
    real clearance still requires ``resolve_project_number`` (registry, ACTIVE) AND a
    participant binding; this only filters shape + counts distinct codes for the
    conflict gate."""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _NUMBER_RE.finditer(text):
        code = f"{m.group(1)}-{m.group(2)}-{m.group(3)}".upper()
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


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
                    _SELECT + "WHERE status = 'active' AND participants @> %s::jsonb "
                    "ORDER BY project_number LIMIT 10",
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
    out: list[dict] = []
    try:
        with get_conn() as conn:
            ensure_project_registry_table(conn)
            with conn.cursor() as cur:
                # ORDER BY makes the bounded 200-row window (and the [:10] slice
                # below) deterministic when active rows exceed the cap — self-audit
                # (codex G3 re-gate#2): soft-lane ordering.
                cur.execute(
                    _SELECT + "WHERE status = 'active' ORDER BY project_number LIMIT 200"
                )
                rows = cur.fetchall()
        for r in rows:
            for a in _as_list(r[6]):  # aliases JSONB
                a = (a or "").strip()
                # True word boundary (not space-padding) so an alias still
                # matches against punctuation: 'Annaberg:', '(Annaberg)',
                # 'Aukera-Annaberg'. re.escape handles punctuation + multi-word
                # aliases ('aukera annaberg').
                if a and re.search(r"\b" + re.escape(a) + r"\b", text, re.IGNORECASE):
                    out.append(_row_to_dict(r))
                    break
    except Exception as e:
        logger.warning(f"resolve_by_alias failed: {e}")
    return out[:10]


def seed_bb_pilot(conn: Any) -> int:
    """Seed Baden-Baden pilot rows. Callable one-off; NOT auto-run. Returns count.
    matter_slug='aukera' is the Director-ratified canonical slug for the BB-AUK-001
    pilot (slugs.yml v23; is_canonical('aukera') is True). 'AUK' is the display
    mnemonic in the project number, not the slug; 'annaberg' stays as a human alias."""
    rows = [
        dict(project_number="BB-AUK-001", desk_owner="baden-baden-desk",
             matter_slug="aukera", clickup_list_id=None,
             participants=[{"channel": "email", "value": "balazs@brisengroup.com"}],
             aliases=["annaberg", "aukera annaberg"]),
    ]
    n = 0
    for r in rows:
        register_project(conn, **r)
        n += 1
    return n
