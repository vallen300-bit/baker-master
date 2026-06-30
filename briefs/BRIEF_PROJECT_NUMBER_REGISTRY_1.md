# BRIEF: PROJECT_NUMBER_REGISTRY_1 — Human + machine project-number registry (Baker OS V2 Box 5 foundation)

## Context
Baker OS V2 / Signal Journey Management (codex-arch design, Director-directed) needs a **project number** a human (e.g. Balazs) puts in an email subject or WhatsApp, that Baker resolves to a matter + desk + people + ClickUp list, and that the ClickUp Dispatcher reads natively. No such scheme exists today — Baker has matter *slugs* (kebab strings, not human-typeable in a subject) and opaque ClickUp IDs. This brief builds the **registry** (the master lookup table) + a resolver + the soft-lane lookup primitives. It does NOT wire the fast lane itself (Box 5 — separate downstream brief).

**Director-ratified format (bus #4679): `DESK-MATTER-###`** — e.g. `BB-AUK-001`. Desk-prefix classifier (BB/AO/MOV/HAG/BR/ORIG) + matter mnemonic + sequence. Email-readable, stable across ClickUp list/task changes, deterministic for Box 5 regex extraction, maps cleanly to ClickUp internally. The desk prefix routes to the responsible desk before any lookup.

**Builder (codex #4680): a B-code** via normal dispatch — NOT Deputy/Codex (those are gate/second-pair only).

## Estimated time: ~1.5h
## Complexity: Low
## Prerequisites: none (additive new module + table). Confirm `DESK_CODES` values + the canonical Aukera/Annaberg slug before non-pilot seeding.

---

## Harness V2

- **Context Contract (read ONLY):** `orchestrator/airport_ticketing_bridge.py:262` (`ensure_airport_ticket_table` idempotent-table template), `kbl/db.py:45` (`get_conn` contextmanager — default tuple cursor, explicit commit/rollback), `kbl/slug_registry.py` (public accessors: `is_canonical`, `normalize`, `canonical_slugs`, `aliases_for`). Do not read more of the codebase than needed.
- **Task class:** additive new module — net-new `kbl/project_registry_store.py` + new `tests/test_project_registry.py`. Touches NO live code, no migration file, no env vars, no deps. Blast radius ~0.
- **Done rubric / done-state class:** **Build-done only** (PR merged + AC1-AC5 green). NO live AC / NO `POST_DEPLOY_AC_VERDICT` — library primitive with no prod caller and no deploy (table self-heals via `CREATE TABLE IF NOT EXISTS` on boot). Non-pilot seed is a separate downstream step, NOT this build.
- **Gate plan:** G1 (builder) `pytest tests/test_project_registry.py` + `py_compile` + `bash scripts/check_singletons.sh` → G3 codex-verifier (effort medium — additive, low-risk) → G4 lead `/security-review` → lead merge. No deploy.

---

## Feature 1: project_registry table + resolver + soft-lane primitives

### Problem
There is no human-friendly, machine-resolvable project identifier in Baker. A scheduled-flight passenger (email/WhatsApp from a known participant referencing a project) cannot be deterministically cleared to the right desk without an LLM guess — risking wrong-desk routing on high-value legal/money/deadline signals. Humans also forget the number, so the registry must also expose **soft-lane** recognition primitives (participant, matter-alias) for the missing-number case.

### Current State
- Matter identity = canonical slugs in `baker-vault/slugs.yml`, loaded by `kbl/slug_registry.py`. Public accessors (verified at origin/main d88abd8): `is_canonical(slug) -> bool`, `normalize(raw) -> Optional[str]`, `canonical_slugs() -> set[str]`, `aliases_for(slug) -> list[str]`. Kebab strings, NOT subject-friendly.
- DB access (verified `kbl/db.py:45`): `from kbl.db import get_conn` — `get_conn()` is a `@contextmanager` yielding a psycopg2 connection with the **default tuple cursor** (no RealDict). In `with get_conn() as conn:` it does NOT auto-commit — callers `conn.commit()` explicitly, `conn.rollback()` in except.
- Idempotent-table precedent to mirror (verified): `orchestrator/airport_ticketing_bridge.py:262 ensure_airport_ticket_table(conn)` uses `CREATE TABLE IF NOT EXISTS …` so the schema self-heals on Render restart without a migration file (codex constraint: idempotent `_ensure_*` boot, not migration-only, or columns drift on restart).
- No `project_number` / registry concept exists (only a retiring Todoist `project_id` — do not use).

### Engineering Craft Gates
- **Diagnose:** N/A — new feature, no bug/regression.
- **Prototype:** N/A — format (`DESK-MATTER-###`) is Director-ratified, not a code-level uncertainty.
- **TDD/verification:** APPLIES. Public seam = `register_project()` / `resolve_project_number()` / `resolve_by_participant()` / `resolve_by_alias()`. Write `tests/test_project_registry.py` first with the vertical behaviours below (real Postgres via `TEST_DATABASE_URL`, auto-skip if unset — repo convention). No implementation-coupled mocks.

### Implementation

**New file: `kbl/project_registry_store.py`**

```python
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
```

### Key Constraints
- **Do NOT wire this into Box 5 / the alert→signal pipeline.** Registry + resolver + soft-lane primitives only. The soft-lane DECISION logic (≥2 independent signals, no conflict, sender-only forbidden, weak/conflict → VISIBLE_HOLD) is Box 5's job — a separate brief. This module only supplies the lookups.
- **`matter_slug` must validate against `slug_registry.is_canonical`** — fail loud, never store an unknown slug.
- **Every SELECT has a LIMIT** (1 / 10 / 200). **Every write except has `conn.rollback()`**; read excepts return safe empty/None.
- **Idempotent boot** — `ensure_project_registry_table` at the top of each public fn; no migration file (avoid restart drift).
- **`get_conn()` = contextmanager, tuple cursor** — index rows positionally (`_row_to_dict`); explicit `conn.commit()` after writes.
- **Store display form (`BB-AUK-001`) + normalised `match_key` (`BBAUK001`)**; both UNIQUE.
- **Reject non-registered regex hits** — `resolve_project_number` returns None for any extracted number absent from the registry (codex guardrail #3).

### Verification
`tests/test_project_registry.py` (live-PG, auto-skip without `TEST_DATABASE_URL`):
1. `register_project("BB-AUK-001", "baden-baden-desk", <canonical slug>)` then `resolve_project_number("Re: BB-AUK-001 funding")` → dict with `desk_owner=baden-baden-desk`.
2. Tolerant: `resolve_project_number("update on bb auk 001")` and `"BB-AUK001"` both resolve to the same row.
3. Unknown: `resolve_project_number("ref ZZ-XX-99")` → `None`.
4. Guard: `register_project(..., matter_slug="not-a-slug")` → raises `ValueError`.
5. Guard: `register_project(project_number="BB-001")` (no matter segment) → raises `ValueError`.
6. Soft #1: `resolve_by_participant("email", "balazs@brisengroup.com")` → returns the seeded project.
7. Soft #2: `resolve_by_alias("notes on Annaberg this week")` → returns the seeded project.

---

## Files Modified
- `kbl/project_registry_store.py` — NEW. Table ensure + register + 3 resolvers (hard + 2 soft) + BB seed.
- `tests/test_project_registry.py` — NEW. 7 vertical behaviour tests.

## Do NOT Touch
- `orchestrator/airport_ticketing_bridge.py` — the airport rail; this registry feeds it later, does not modify it.
- `orchestrator/dispatcher_relay.py` — Dispatcher consumes the number later (separate brief).
- `kbl/bridge/alerts_to_signal.py` / `kbl/pipeline_tick.py` — Box 5 wiring is out of scope.
- `baker-vault/slugs.yml` — separate-repo PR only; this registry READS slugs, never writes them.

### Surface contract: N/A — backend data/registry module, no UI surface.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('kbl/project_registry_store.py', doraise=True)"` clean.
2. `pytest tests/test_project_registry.py -v` — 7 pass (or skip without `TEST_DATABASE_URL`; CI provisions it).
3. Confirm canonical Aukera/Annaberg slug before any real seed (`slug_registry.canonical_slugs()`).
4. Confirm `DESK_CODES` values against the agent registry before non-pilot use.
5. Table self-heals on a fresh DB (call any public fn → table exists).

## Verification SQL
```sql
SELECT project_number, desk_code, desk_owner, matter_slug, clickup_list_id
FROM project_registry
ORDER BY created_at DESC
LIMIT 20;
```
