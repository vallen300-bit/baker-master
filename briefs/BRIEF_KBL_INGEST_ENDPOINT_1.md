# BRIEF: KBL_INGEST_ENDPOINT_1 — Single HTTP chokepoint for wiki writes (matter/person/entity + Gold mirror)

## Context

M0 quintet row 3. Per Cortex-3T production roadmap (`_ops/ideas/2026-04-21-cortex3t-production-roadmap.md` §First-action briefs):

> **`BRIEF_KBL_INGEST_ENDPOINT`** — confirm or build the single chokepoint through which every wiki write must flow. Enforces frontmatter schema + slug lookup + Postgres + Qdrant atomicity + audit log.

**What exists today:**
- `wiki_pages` Postgres table (schema at `memory/store_back.py:2592-2609`): `slug`, `title`, `content`, `agent_owner`, `page_type`, `matter_slugs`, `backlinks`, `generation`, `updated_at`, `updated_by`.
- `scripts/ingest_vault_matter.py` — **CLI-only** script for bulk matter-directory ingest. Wipes + re-inserts per matter. No schema validation, no slug registry check, no Qdrant write, no ledger.
- `kbl/slug_registry.py` — matter slug loader (v9, 26 slugs). Public API: `is_canonical`, `canonical_slugs`, `active_slugs`, `normalize`.
- `invariant_checks/ledger_atomic.py` — atomic context manager shipped in PR #51 (LEDGER_ATOMIC_1). Binds primary write + `baker_actions` ledger row into one DB transaction.
- `vault_scaffolding/v1/schema/VAULT.md` shipped in PR #52 — 7-field frontmatter + 3-way taxonomy. Baker-vault mirror at commit `07089e3` with `author: director`.

**What's missing (this brief):**
- No single HTTP chokepoint for wiki writes. Current path (`ingest_vault_matter.py`) is CLI-only, skips schema validation, skips Qdrant, skips the atomic-ledger invariant shipped last PR.
- Downstream work blocked: M1 migration script, M2 sentinel auto-stub, M3 Cortex-3T reasoning-loop writes — all need this endpoint.

**Design choices (tight, defensible):**

1. **HTTP chokepoint:** `POST /api/kbl/ingest` on Baker's FastAPI app. Auth: existing `X-Baker-Key` header (same `verify_api_key` dependency used by 40+ routes in `outputs/dashboard.py`). Body: `{ frontmatter: {...}, body: "markdown string", trigger_source: "..." }`.

2. **Schema validation** — enforce VAULT.md §2 7-field frontmatter (`type`, `slug`, `name`, `updated`, `author`, `tags`, `related`) + taxonomy whitelist (`matter`/`person`/`entity`) + slug format rules (kebab-case for all, firstname-lastname for person).

3. **Slug registry validation** — MATTER slugs validated against `slugs.yml` via existing `kbl.slug_registry.is_canonical()`. PERSON + ENTITY slug registry loaders don't exist yet (KBL_SCHEMA_1 shipped the YAML files, not the loaders) — this brief format-validates only for those two types. Registry check for person/entity deferred to `KBL_PEOPLE_ENTITY_LOADERS_1` (follow-on, M0 row 3b).

4. **Atomic write** — Postgres `wiki_pages` UPSERT + `baker_actions` ledger entry bound via `atomic_director_action(conn, ...)`. Either both land or both roll back. CHANDA #2 preserved.

5. **Qdrant vector upsert** — post-atomic (non-blocking), same pattern as `cortex.publish_event()`. Collection `baker-wiki`, payload carries slug + type + wiki_page_id + tags + voice. Embedding via existing `models.cortex._embed_text` (Voyage voyage-3, 1024d).

6. **Gold mirror integration** — when `frontmatter.voice == "gold"`, the reassembled markdown is ALSO written to a staging path `vault_scaffolding/live_mirror/v1/<slug>.md` in baker-master. This staging dir is the pickup point for AI Head's post-merge SSH mirror to `~/baker-vault/` (preserves CHANDA #9 — Baker service NEVER writes to baker-vault directly). If `voice != "gold"`, no file write happens. Gold file discipline (Director-only initials, hybrid-C comment workflow) is a separate brief (`BRIEF_GOLD_COMMENT_WORKFLOW_1`, queued); this brief only ships the mirror-file write mechanic.

**What this brief does NOT ship (explicit):**
- `kbl/people_registry.py` / `kbl/entity_registry.py` loaders — follow-on (`KBL_PEOPLE_ENTITY_LOADERS_1`).
- Gold comment workflow (hybrid C — DV-only initials, newer-wins, Proposed Gold isolation) — follow-on (`BRIEF_GOLD_COMMENT_WORKFLOW_1`). This brief flags gold via frontmatter + writes the mirror file; the file's authorship/comment-merge semantics are out of scope.
- Migration of `scripts/ingest_vault_matter.py` to the new endpoint — that's M1 (`BRIEF_KBL_SEED_1`). This brief leaves the CLI script untouched for now.
- `baker_raw_query` MCP endpoint additions — out of scope.
- Deprecation of `_seed_wiki_from_view_files` — out of scope; seed logic is for empty-DB bootstrap only and doesn't interfere with the new endpoint.

**Source artefacts:**
- `_ops/ideas/2026-04-21-cortex3t-production-roadmap.md` §First-action briefs
- `baker-vault/schema/VAULT.md` (shipped 07089e3)
- `_ops/ideas/2026-04-21-gold-comment-workflow-spec.md` (Gold design; not implemented here)
- PR #51 merge `38a8997` (ledger_atomic.py)

## Estimated time: ~3–3.5h
## Complexity: Medium (HTTP route + validation + atomic multi-write + tests)
## Prerequisites: PR #51 LEDGER_ATOMIC_1 merged `38a8997`. PR #52 KBL_SCHEMA_1 merged `a47125c`. PR #53 MAC_MINI_WRITER_AUDIT_1 merged `327dbab`.

---

## Fix/Feature 1: `kbl/ingest_endpoint.py` — logic module

### Problem

No reusable ingest primitive exists. The FastAPI route, future CLI migration script, and future Cortex-3T writer all need to share ONE validated atomic ingest path. A module-level function decouples the business logic from the HTTP framing.

### Current State

- `kbl/` directory exists (26 files). `kbl/slug_registry.py` is the pattern exemplar (public-API-first, module-level cache, stdlib-only except yaml).
- No file named `ingest_endpoint.py` or `ingest.py` in `kbl/`.

### Implementation

**Create `kbl/ingest_endpoint.py`:**

```python
"""KBL ingest endpoint — single chokepoint for wiki writes.

Every agent-originated wiki write flows through this module. Enforces:
- 7-field frontmatter schema (per baker-vault schema/VAULT.md §2)
- Slug validation (matter slugs against slugs.yml; person/entity
  format-only pending KBL_PEOPLE_ENTITY_LOADERS_1)
- Postgres wiki_pages UPSERT + baker_actions audit log atomic
  (via invariant_checks.ledger_atomic — CHANDA #2)
- Qdrant vector upsert (post-atomic, non-blocking)
- Gold-tier mirror: when voice=gold, stages content to
  vault_scaffolding/live_mirror/v1/<slug>.md for AI Head
  SSH-mirror to baker-vault (CHANDA #9 preserved — Baker never
  writes baker-vault directly)

Exception model:
- KBLIngestError — caller-visible validation failure (HTTP 400)
- RuntimeError — infrastructure failure (HTTP 500)
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("baker.kbl.ingest_endpoint")

REQUIRED_FRONTMATTER_KEYS = (
    "type", "slug", "name", "updated", "author", "tags", "related",
)
VALID_TYPES = frozenset({"matter", "person", "entity"})
VALID_VOICES = frozenset({"silver", "gold"})
KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
PERSON_SLUG_RE = re.compile(r"^[a-z]+(-[a-z]+)+$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AUTHOR_RE = re.compile(r"^(director|agent|[a-z][a-z0-9_]*)$")


@dataclass
class IngestResult:
    wiki_page_id: int
    slug: str
    qdrant_point_id: Optional[int]
    gold_mirrored: bool
    mirror_path: Optional[str] = None


class KBLIngestError(ValueError):
    """Raised when ingest request fails schema / slug / content validation."""


def validate_frontmatter(fm: dict) -> None:
    """Raise KBLIngestError if fm doesn't conform to VAULT.md §2."""
    if not isinstance(fm, dict):
        raise KBLIngestError("frontmatter must be a dict")
    missing = [k for k in REQUIRED_FRONTMATTER_KEYS if k not in fm]
    if missing:
        raise KBLIngestError(f"frontmatter missing required keys: {missing}")

    t = fm["type"]
    if t not in VALID_TYPES:
        raise KBLIngestError(f"type must be one of {sorted(VALID_TYPES)}, got {t!r}")

    slug = fm["slug"]
    if not isinstance(slug, str) or not slug:
        raise KBLIngestError("slug must be non-empty string")
    if not KEBAB_SLUG_RE.match(slug):
        raise KBLIngestError(f"slug must be lowercase kebab-case, got {slug!r}")
    if t == "person" and not PERSON_SLUG_RE.match(slug):
        raise KBLIngestError(
            f"person slug must be firstname-lastname (all letters, hyphens), got {slug!r}"
        )

    name = fm["name"]
    if not isinstance(name, str) or not name:
        raise KBLIngestError("name must be non-empty string")

    if not ISO_DATE_RE.match(str(fm["updated"])):
        raise KBLIngestError(f"updated must be YYYY-MM-DD, got {fm['updated']!r}")

    author = fm["author"]
    if not isinstance(author, str) or not AUTHOR_RE.match(author):
        raise KBLIngestError(f"author invalid (must be 'director'/'agent'/'<agent_id>'): {author!r}")

    if not isinstance(fm["tags"], list):
        raise KBLIngestError("tags must be a list (empty list allowed)")
    if not isinstance(fm["related"], list):
        raise KBLIngestError("related must be a list (empty list allowed)")

    voice = fm.get("voice", "silver")
    if voice not in VALID_VOICES:
        raise KBLIngestError(f"voice (optional) must be one of {sorted(VALID_VOICES)}, got {voice!r}")


def validate_slug_in_registry(fm: dict) -> None:
    """For type=matter, slug must be canonical in slugs.yml.

    For type=person/entity, format-only validation (registry loader not yet
    shipped — see KBL_PEOPLE_ENTITY_LOADERS_1 follow-on).
    """
    if fm["type"] == "matter":
        from kbl.slug_registry import is_canonical
        if not is_canonical(fm["slug"]):
            raise KBLIngestError(
                f"matter slug {fm['slug']!r} not in slugs.yml registry"
            )
    # type=person / entity: format already validated in validate_frontmatter.
    # Registry check pending KBL_PEOPLE_ENTITY_LOADERS_1.


def ingest(
    frontmatter: dict,
    body: str,
    trigger_source: str = "kbl_ingest_endpoint",
    *,
    store=None,
    qdrant_client=None,
    mirror_root: Optional[Path] = None,
) -> IngestResult:
    """Atomic ingest: validate → wiki_pages UPSERT + ledger row → Qdrant → maybe gold-mirror.

    Args:
        frontmatter: dict with 7 VAULT.md §2 fields (+ optional voice).
        body: markdown body WITHOUT frontmatter delimiters.
        trigger_source: agent id / script name recorded in baker_actions.
        store: SentinelStoreBack instance. Defaults to module singleton.
        qdrant_client: Qdrant client. Defaults to cortex._get_qdrant() result.
        mirror_root: override for the gold-mirror staging dir (testing).

    Returns:
        IngestResult with wiki_page_id, slug, qdrant_point_id, gold_mirrored.

    Raises:
        KBLIngestError: validation failed (HTTP 400 at route layer).
        RuntimeError: infrastructure failure (HTTP 500 at route layer).
    """
    validate_frontmatter(frontmatter)
    validate_slug_in_registry(frontmatter)

    if not isinstance(body, str):
        raise KBLIngestError("body must be a string")

    if store is None:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
    if store is None:
        raise RuntimeError("SentinelStoreBack singleton unavailable")

    conn = store._get_conn()
    if conn is None:
        raise RuntimeError("DB connection unavailable")

    from invariant_checks.ledger_atomic import atomic_director_action

    wiki_page_id: Optional[int] = None
    voice = frontmatter.get("voice", "silver")
    content = _reassemble(frontmatter, body)
    page_type = f"kbl_{frontmatter['type']}"
    matter_slugs = list(frontmatter.get("tags", []))

    try:
        with atomic_director_action(
            conn,
            action_type=f"kbl:ingest:{frontmatter['type']}",
            payload={
                "slug": frontmatter["slug"],
                "name": frontmatter["name"][:120],
                "voice": voice,
                "author": frontmatter["author"],
            },
            trigger_source=trigger_source,
        ) as cur:
            cur.execute(
                """
                INSERT INTO wiki_pages
                    (slug, title, content, agent_owner, page_type,
                     matter_slugs, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    agent_owner = EXCLUDED.agent_owner,
                    page_type = EXCLUDED.page_type,
                    matter_slugs = EXCLUDED.matter_slugs,
                    updated_at = NOW(),
                    updated_by = EXCLUDED.updated_by,
                    generation = wiki_pages.generation + 1
                RETURNING id
                """,
                (
                    frontmatter["slug"],
                    frontmatter["name"],
                    content,
                    frontmatter["author"],
                    page_type,
                    matter_slugs,
                    trigger_source,
                ),
            )
            wiki_page_id = cur.fetchone()[0]
    except KBLIngestError:
        store._put_conn(conn)
        raise
    except Exception as e:
        store._put_conn(conn)
        logger.error("kbl.ingest atomic block failed (slug=%s): %s", frontmatter["slug"], e)
        raise RuntimeError(f"ingest atomic write failed: {e}") from e

    # Post-atomic side-effects (non-blocking) — same pattern as cortex.publish_event.
    try:
        qdrant_point_id = _upsert_vector(
            qdrant_client, frontmatter, body, wiki_page_id,
        )
    except Exception as e:
        logger.warning("kbl.ingest post-write vector upsert failed (non-fatal): %s", e)
        qdrant_point_id = None

    mirror_path: Optional[Path] = None
    if voice == "gold":
        try:
            mirror_path = _write_gold_mirror(frontmatter, body, mirror_root)
        except Exception as e:
            logger.warning("kbl.ingest gold mirror failed (non-fatal): %s", e)
            mirror_path = None

    store._put_conn(conn)
    return IngestResult(
        wiki_page_id=wiki_page_id,
        slug=frontmatter["slug"],
        qdrant_point_id=qdrant_point_id,
        gold_mirrored=mirror_path is not None,
        mirror_path=str(mirror_path) if mirror_path else None,
    )


# ─── Helpers ───────────────────────────────────────────────────────────────

def _reassemble(fm: dict, body: str) -> str:
    """Rebuild `---\\n<yaml>\\n---\\n\\n<body>` markdown."""
    import yaml
    fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{fm_yaml}\n---\n\n{body.lstrip()}"


def _upsert_vector(client, fm: dict, body: str, wiki_page_id: int) -> Optional[int]:
    """Qdrant upsert. Returns point_id or None if Qdrant/embedding unavailable."""
    if client is None:
        from models.cortex import _get_qdrant
        client = _get_qdrant()
    if client is None:
        logger.info("kbl.ingest: Qdrant unavailable — skipping vector upsert")
        return None
    from qdrant_client.models import PointStruct
    from models.cortex import _embed_text

    text = f"{fm['name']}\n\n{body[:2000]}"
    vec = _embed_text(text)
    if not vec:
        return None
    point_id = int(hashlib.sha256(f"kbl_{fm['slug']}".encode()).hexdigest()[:16], 16)
    client.upsert(
        collection_name="baker-wiki",
        points=[PointStruct(
            id=point_id,
            vector=vec,
            payload={
                "slug": fm["slug"],
                "type": fm["type"],
                "wiki_page_id": wiki_page_id,
                "tags": list(fm.get("tags", [])),
                "voice": fm.get("voice", "silver"),
            },
        )],
    )
    logger.info("kbl.ingest: upserted Qdrant point %s for slug=%s", point_id, fm["slug"])
    return point_id


def _write_gold_mirror(fm: dict, body: str, mirror_root: Optional[Path]) -> Path:
    """Write gold content to staging dir for AI Head SSH-mirror to baker-vault."""
    if mirror_root is None:
        repo = Path(__file__).resolve().parents[1]
        mirror_root = repo / "vault_scaffolding" / "live_mirror" / "v1"
    mirror_root.mkdir(parents=True, exist_ok=True)
    target = mirror_root / f"{fm['slug']}.md"
    target.write_text(_reassemble(fm, body), encoding="utf-8")
    logger.info("kbl.ingest: gold mirror staged at %s", target)
    return target
```

### Key Constraints

- **Single chokepoint** — any agent-side wiki write from this point forward SHOULD call `ingest()` rather than INSERT `wiki_pages` directly. This brief doesn't migrate existing callers; it provides the primitive.
- **Atomic first, side-effects second.** `wiki_pages` INSERT + `baker_actions` row happen in ONE transaction via `atomic_director_action`. Qdrant + gold mirror are post-atomic (both can fail without data-integrity impact).
- **`_put_conn(conn)` runs exactly once on every path** — success, validation failure, infrastructure failure. Matches `cortex.publish_event()` post-migration shape.
- **Person/entity slug validation is format-only** — registry check deferred. Explicit TODO comment in `validate_slug_in_registry()`.
- **No circular imports.** Lazy imports of `SentinelStoreBack`, `atomic_director_action`, `_embed_text`, `_get_qdrant` inside function bodies — same pattern as `cortex.py:18-24`.
- **No new env vars.** Reuses existing `BAKER_VAULT_PATH`, `VOYAGE_API_KEY`, `QDRANT_URL`.
- **No new DB tables.** Reuses `wiki_pages` + `baker_actions`.
- **Voice field is OPTIONAL.** Default `silver` matches the existing wiki convention. Only `gold` triggers the mirror write.
- **Gold mirror path is REPO-RELATIVE** (`vault_scaffolding/live_mirror/v1/<slug>.md`). On Render prod, this resolves inside the container — staging-only. AI Head SSH-mirror picks up from the Mac Mini's baker-master clone, not from Render.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('kbl/ingest_endpoint.py', doraise=True)"` — zero output.
2. `python3 -c "from kbl.ingest_endpoint import ingest, KBLIngestError, validate_frontmatter; print('OK')"` — prints OK.
3. Validation smoke: `python3 -c "from kbl.ingest_endpoint import validate_frontmatter; validate_frontmatter({'type':'matter','slug':'hagenauer-rg7','name':'x','updated':'2026-04-23','author':'agent','tags':[],'related':[]})"` — zero output, zero error.

---

## Fix/Feature 2: FastAPI route `POST /api/kbl/ingest` in `outputs/dashboard.py`

### Problem

The logic module (Feature 1) isn't exposed to HTTP callers until a route wires it. Pattern-match on existing `verify_api_key`-protected routes (~40 precedents in dashboard.py).

### Current State

File: `outputs/dashboard.py`.

Precedent route shape (dashboard.py:1066-1085 `@app.post("/api/matters"...)`):
- `@app.post("/path", tags=[...], dependencies=[Depends(verify_api_key)])`
- `async def handler(req: PydanticModel):`
- `try/except HTTPException:` re-raise; catch-all to `raise HTTPException(500, str(e))`.
- Returns `{"status": ..., "id": ..., ...}` dict.

### Implementation

**Step 1 — Add Pydantic model** near the existing request models (search for `class MatterRequest(BaseModel)` in dashboard.py to find the right block):

```python
class KBLIngestRequest(BaseModel):
    """POST /api/kbl/ingest body. See kbl.ingest_endpoint.ingest() for semantics."""
    frontmatter: dict
    body: str
    trigger_source: Optional[str] = "kbl_ingest_endpoint"
```

**Step 2 — Add route** in the same general section as other `/api/*` POSTs (e.g. just after the `/api/matters` block ending ~line 1104):

```python
@app.post("/api/kbl/ingest", tags=["kbl"], dependencies=[Depends(verify_api_key)])
async def kbl_ingest_endpoint(req: KBLIngestRequest):
    """Single chokepoint for wiki writes.

    Enforces VAULT.md §2 frontmatter schema, slug registry check
    (matters — via slugs.yml), atomic wiki_pages + baker_actions write
    (CHANDA #2), Qdrant upsert, and Gold mirror staging when voice=gold.
    """
    from kbl.ingest_endpoint import ingest, KBLIngestError
    try:
        result = ingest(
            frontmatter=req.frontmatter,
            body=req.body,
            trigger_source=req.trigger_source or "kbl_ingest_endpoint",
        )
        return {
            "status": "ingested",
            "wiki_page_id": result.wiki_page_id,
            "slug": result.slug,
            "qdrant_point_id": result.qdrant_point_id,
            "gold_mirrored": result.gold_mirrored,
            "mirror_path": result.mirror_path,
        }
    except KBLIngestError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"POST /api/kbl/ingest failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

### Key Constraints

- **Auth:** `Depends(verify_api_key)` — same `X-Baker-Key` header used by all other `/api/*` routes.
- **Tag `kbl`** — new route tag, consistent with `matters`, `preferences`, etc.
- **Do NOT add OpenAPI response models.** Matches the `/api/matters` style (dicts, no response model). Keeps the diff small.
- **Do NOT refactor existing routes** while adding this one. Surgical.
- **Import placement for `KBLIngestRequest`** — inline with other Pydantic request models. Do not create a new module for it.
- **FastAPI `logger`** already imported at top of dashboard.py — reuse.

### Verification

1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` — zero output.
2. `grep -n "KBLIngestRequest\|kbl_ingest_endpoint\|/api/kbl/ingest" outputs/dashboard.py` — exactly 1 Pydantic class def, 1 route decorator, 1 handler func. Three matches minimum.
3. `grep -n "verify_api_key" outputs/dashboard.py` — new route shows up in the existing list (not silently skipping auth).

---

## Fix/Feature 3: Pytest scenarios for `kbl/ingest_endpoint.py`

### Problem

Without exercised tests, atomicity + validation + gold-mirror behaviour is asserted only by hope. Ten scenarios cover the contract.

### Current State

- `tests/` has `test_ledger_atomic.py` (PR #51, 6 scenarios, hermetic sqlite3) as the closest shape precedent.
- Neither `kbl/slug_registry.py` nor existing ingest code has hermetic tests beyond `scripts/validate_eval_labels.py` checks.

### Implementation

**Create `tests/test_kbl_ingest_endpoint.py`:**

```python
"""Tests for kbl/ingest_endpoint.py.

Hermetic where possible: in-memory sqlite3 mirrors wiki_pages +
baker_actions schemas. Qdrant and Voyage are stubbed. Gold mirror
writes to a tmp_path fixture dir.

Atomicity tests use the same monkeypatch-context-manager pattern as
test_ledger_atomic.py — swap the ledger helper with a fail-on-exit
variant to simulate transaction failure.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from contextlib import contextmanager
import pytest

import kbl.ingest_endpoint as mod
from kbl.ingest_endpoint import (
    IngestResult,
    KBLIngestError,
    ingest,
    validate_frontmatter,
    validate_slug_in_registry,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def sqlite_conn():
    """In-memory sqlite3 with wiki_pages + baker_actions tables."""
    c = sqlite3.connect(":memory:")
    c.isolation_level = ""  # explicit txn — mirrors psycopg2 default
    cur = c.cursor()
    cur.execute("""
        CREATE TABLE wiki_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            agent_owner TEXT,
            page_type TEXT NOT NULL,
            matter_slugs TEXT,
            backlinks TEXT,
            generation INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE baker_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            target_task_id TEXT,
            target_space_id TEXT,
            payload TEXT,
            trigger_source TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            success INTEGER DEFAULT 1,
            error_message TEXT
        )
    """)
    c.commit()
    cur.close()
    yield c
    c.close()


@pytest.fixture
def fake_store(sqlite_conn, monkeypatch):
    """SentinelStoreBack stand-in exposing _get_conn / _put_conn."""
    class _FakeStore:
        def _get_conn(self):
            return sqlite_conn
        def _put_conn(self, _):
            pass
    fake = _FakeStore()

    # Stub SentinelStoreBack._get_global_instance for modules that look it up.
    import memory.store_back as sb_mod
    monkeypatch.setattr(sb_mod.SentinelStoreBack, "_get_global_instance",
                        classmethod(lambda cls: fake), raising=False)
    return fake


@pytest.fixture
def patch_ledger(monkeypatch):
    """Swap invariant_checks.ledger_atomic.atomic_director_action for a
    sqlite-compatible (no ::jsonb) variant."""
    @contextmanager
    def _sqlite_cm(conn, action_type, payload=None, trigger_source=None,
                    target_task_id=None, target_space_id=None):
        cur = conn.cursor()
        try:
            yield cur
            cur.execute(
                "INSERT INTO baker_actions "
                "(action_type, target_task_id, target_space_id, payload, "
                " trigger_source, success, error_message) "
                "VALUES (?, ?, ?, ?, ?, 1, NULL)",
                (
                    action_type,
                    target_task_id,
                    target_space_id,
                    json.dumps(payload) if payload else None,
                    trigger_source,
                ),
            )
            conn.commit()
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            try: cur.close()
            except Exception: pass

    import invariant_checks.ledger_atomic as la
    monkeypatch.setattr(la, "atomic_director_action", _sqlite_cm)
    yield _sqlite_cm


@pytest.fixture
def patch_vector(monkeypatch):
    """No-op _upsert_vector to avoid Qdrant + Voyage dependencies."""
    monkeypatch.setattr(mod, "_upsert_vector", lambda *a, **kw: None)


@pytest.fixture
def patch_sqlite_wiki_sql(monkeypatch):
    """Rewrite the wiki_pages INSERT in ingest() so sqlite understands it.

    Postgres uses `%s` placeholders + `ON CONFLICT (slug) DO UPDATE`;
    sqlite needs `?` + `ON CONFLICT(slug) DO UPDATE`. Swap at runtime
    by wrapping the cursor.execute used in the atomic block.
    """
    real_execute = sqlite3.Cursor.execute

    def _translated_execute(self, sql, params=()):
        sql2 = sql.replace("%s", "?")
        return real_execute(self, sql2, params)

    monkeypatch.setattr(sqlite3.Cursor, "execute", _translated_execute)


@pytest.fixture
def valid_matter_fm():
    return {
        "type": "matter",
        "slug": "hagenauer-rg7",  # Real slug from slugs.yml v9
        "name": "Hagenauer RG7",
        "updated": "2026-04-23",
        "author": "agent",
        "tags": [],
        "related": [],
    }


# ─── Validation tests ─────────────────────────────────────────────────────

def test_validate_frontmatter_happy(valid_matter_fm):
    validate_frontmatter(valid_matter_fm)  # no raise


@pytest.mark.parametrize("mutate,key", [
    (lambda fm: fm.pop("type"), "type"),
    (lambda fm: fm.pop("slug"), "slug"),
    (lambda fm: fm.pop("tags"), "tags"),
])
def test_validate_frontmatter_missing_required_key(valid_matter_fm, mutate, key):
    mutate(valid_matter_fm)
    with pytest.raises(KBLIngestError, match="missing required keys"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_bad_type(valid_matter_fm):
    valid_matter_fm["type"] = "thing"
    with pytest.raises(KBLIngestError, match="type must be"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_bad_slug_format(valid_matter_fm):
    valid_matter_fm["slug"] = "Hagenauer_RG7"  # underscore + caps = bad
    with pytest.raises(KBLIngestError, match="kebab-case"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_person_slug_must_be_firstname_lastname(valid_matter_fm):
    valid_matter_fm["type"] = "person"
    valid_matter_fm["slug"] = "ao"  # single-token fails person rule
    with pytest.raises(KBLIngestError, match="firstname-lastname"):
        validate_frontmatter(valid_matter_fm)


def test_validate_frontmatter_bad_date(valid_matter_fm):
    valid_matter_fm["updated"] = "23 April 2026"
    with pytest.raises(KBLIngestError, match="updated must be YYYY-MM-DD"):
        validate_frontmatter(valid_matter_fm)


def test_validate_slug_in_registry_rejects_unknown_matter(valid_matter_fm):
    valid_matter_fm["slug"] = "nonexistent-matter"
    # validate_frontmatter passes format checks; registry check rejects.
    validate_frontmatter(valid_matter_fm)
    with pytest.raises(KBLIngestError, match="not in slugs.yml registry"):
        validate_slug_in_registry(valid_matter_fm)


# ─── Ingest-flow tests ────────────────────────────────────────────────────

def test_ingest_happy_path(
    fake_store, sqlite_conn, patch_ledger, patch_vector, patch_sqlite_wiki_sql,
    valid_matter_fm,
):
    result = ingest(
        frontmatter=valid_matter_fm,
        body="Body content.",
        trigger_source="test",
        store=fake_store,
    )
    assert isinstance(result, IngestResult)
    assert result.slug == "hagenauer-rg7"
    assert result.wiki_page_id > 0
    assert result.gold_mirrored is False

    cur = sqlite_conn.cursor()
    cur.execute("SELECT slug, title, agent_owner, page_type FROM wiki_pages")
    row = cur.fetchone()
    assert row == ("hagenauer-rg7", "Hagenauer RG7", "agent", "kbl_matter")
    cur.execute("SELECT COUNT(*) FROM baker_actions")
    assert cur.fetchone()[0] == 1


def test_ingest_validation_failure_no_writes(
    fake_store, sqlite_conn, patch_ledger, patch_vector, valid_matter_fm,
):
    valid_matter_fm["type"] = "bogus"
    with pytest.raises(KBLIngestError):
        ingest(valid_matter_fm, "body", store=fake_store)
    cur = sqlite_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM wiki_pages")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM baker_actions")
    assert cur.fetchone()[0] == 0


def test_ingest_upsert_bumps_generation(
    fake_store, sqlite_conn, patch_ledger, patch_vector, patch_sqlite_wiki_sql,
    valid_matter_fm,
):
    ingest(valid_matter_fm, "first", store=fake_store)
    ingest(valid_matter_fm, "second", store=fake_store)
    cur = sqlite_conn.cursor()
    cur.execute("SELECT generation, content FROM wiki_pages WHERE slug = 'hagenauer-rg7'")
    row = cur.fetchone()
    assert row[0] == 2
    assert "second" in row[1]


def test_ingest_gold_voice_writes_mirror(
    fake_store, sqlite_conn, patch_ledger, patch_vector, patch_sqlite_wiki_sql,
    valid_matter_fm, tmp_path,
):
    valid_matter_fm["voice"] = "gold"
    result = ingest(
        valid_matter_fm, "gold body", store=fake_store,
        mirror_root=tmp_path,
    )
    assert result.gold_mirrored is True
    target = tmp_path / "hagenauer-rg7.md"
    assert target.exists()
    content = target.read_text()
    assert "gold body" in content
    assert "voice: gold" in content


def test_ingest_silver_voice_no_mirror(
    fake_store, sqlite_conn, patch_ledger, patch_vector, patch_sqlite_wiki_sql,
    valid_matter_fm, tmp_path,
):
    result = ingest(
        valid_matter_fm, "silver body", store=fake_store,
        mirror_root=tmp_path,
    )
    assert result.gold_mirrored is False
    assert list(tmp_path.iterdir()) == []


def test_ingest_atomic_rollback_on_ledger_failure(
    fake_store, sqlite_conn, patch_vector, patch_sqlite_wiki_sql,
    valid_matter_fm, monkeypatch,
):
    """Simulate ledger-write failure inside the atomic block → wiki_pages rolls back too."""

    @contextmanager
    def _failing_cm(conn, *a, **kw):
        cur = conn.cursor()
        try:
            yield cur
            raise sqlite3.OperationalError("simulated ledger failure")
        except Exception:
            try: conn.rollback()
            except Exception: pass
            raise
        finally:
            cur.close()

    import invariant_checks.ledger_atomic as la
    monkeypatch.setattr(la, "atomic_director_action", _failing_cm)

    with pytest.raises(RuntimeError, match="atomic write failed"):
        ingest(valid_matter_fm, "doomed", store=fake_store)

    cur = sqlite_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM wiki_pages")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM baker_actions")
    assert cur.fetchone()[0] == 0
```

### Key Constraints

- **Hermetic** — sqlite3 stdlib, no Neon / Qdrant / Voyage. Gold mirror uses `tmp_path`.
- **SQL translation shim** — `patch_sqlite_wiki_sql` fixture rewrites `%s` → `?` in cursor.execute calls so the Postgres-shaped INSERT lands correctly on sqlite. Tested idiom.
- **ON CONFLICT syntax** — sqlite3 supports `ON CONFLICT(slug) DO UPDATE` since 3.24 (2018). Stable enough.
- **Registry test** — `test_validate_slug_in_registry_rejects_unknown_matter` relies on `BAKER_VAULT_PATH` env var being set during test run (CI config). If the env is unset, the test fails with `SlugRegistryError` from the loader, not `KBLIngestError`. Guard: set `BAKER_VAULT_PATH=/Users/dimitry/baker-vault` via pytest conftest OR skip the test when the env is unset.
- **No mocks of third-party** — we don't mock Qdrant / Voyage; we replace `_upsert_vector` at the module level with a no-op. Documented in fixture docstring.
- **~280 LOC** — within the LEDGER_ATOMIC_1 precedent size (225 LOC).

### Verification

1. `python3 -c "import py_compile; py_compile.compile('tests/test_kbl_ingest_endpoint.py', doraise=True)"` — zero output.
2. `pytest tests/test_kbl_ingest_endpoint.py -v` — expect ~13 passed (7 validation + 6 flow).
3. `pytest tests/ 2>&1 | tail -3` — +13 passes, 0 regressions. (Baseline at dispatch = whatever main shows.)

---

## Files Modified

- NEW `kbl/ingest_endpoint.py` (~250 LOC).
- NEW `tests/test_kbl_ingest_endpoint.py` (~280 LOC).
- MODIFIED `outputs/dashboard.py` — Pydantic request model + 1 route (~25 LOC added).

**Total: 2 new + 1 modified, ~555 LOC added, 0 removed.**

## Do NOT Touch

- `scripts/ingest_vault_matter.py` — CLI script stays as-is. M1 migration brief handles the cutover.
- `memory/store_back.py` — no changes to `_ensure_wiki_pages_table`, `_seed_wiki_from_view_files`, `log_baker_action`.
- `invariant_checks/ledger_atomic.py` — reuse as-is. Zero edits.
- `kbl/slug_registry.py` — reuse `is_canonical`. Zero edits.
- `models/cortex.py` — reuse `_embed_text` and `_get_qdrant`. Zero edits.
- `baker-vault/` — no direct writes. Gold mirror stages to `vault_scaffolding/live_mirror/v1/<slug>.md` in baker-master. AI Head post-merge handles the SSH mirror.
- `CHANDA.md` / `CHANDA_enforcement.md` — no changes. This brief uses detector #2 (ledger_atomic) — no new invariants, no §7 row needed.
- `triggers/embedded_scheduler.py` — hot file for shared branch. Avoid.
- `memory/store_back.py:3360-3397` (`log_baker_action`) — keep existing callers working.
- `.github/workflows/` — no CI yet.

## Quality Checkpoints

Run in order. Paste literal output in ship report.

1. **Python syntax on all 3 files:**
   ```
   python3 -c "import py_compile; py_compile.compile('kbl/ingest_endpoint.py', doraise=True)"
   python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
   python3 -c "import py_compile; py_compile.compile('tests/test_kbl_ingest_endpoint.py', doraise=True)"
   ```
   All 3 zero output.

2. **Import smoke:**
   ```
   python3 -c "from kbl.ingest_endpoint import ingest, KBLIngestError, validate_frontmatter, IngestResult; print('OK')"
   ```
   Expect: `OK`.

3. **Route is registered:**
   ```
   grep -n "/api/kbl/ingest" outputs/dashboard.py
   ```
   Expect: exactly 1 match (the `@app.post` decorator).

4. **Pydantic model exists:**
   ```
   grep -n "class KBLIngestRequest" outputs/dashboard.py
   ```
   Expect: exactly 1 match.

5. **Auth wired:**
   ```
   grep -B1 "/api/kbl/ingest" outputs/dashboard.py | grep -c "verify_api_key"
   ```
   Expect: `1`. The new route is protected.

6. **New tests pass in isolation:**
   ```
   pytest tests/test_kbl_ingest_endpoint.py -v 2>&1 | tail -20
   ```
   Expect: `13 passed` (7 validation + 6 flow).

7. **Full-suite regression:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Expect +13 passes vs main baseline at dispatch time, 0 regressions.

8. **Singleton hook still green:**
   ```
   bash scripts/check_singletons.sh
   ```
   Expect: `OK: No singleton violations found.`

9. **No baker-vault writes in diff:**
   ```
   git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
   ```
   Expect: `OK: no baker-vault writes.`

10. **Gold-mirror staging dir is ignored for tracking:**
    The brief assumes `vault_scaffolding/live_mirror/v1/` will be populated at runtime. It does NOT add to `.gitignore` this brief — runtime-written content is ephemeral on Render and mirrored from Mac Mini. If a reviewer wants `.gitignore`, flag as fast-follow (out of scope for Q10 green).

11. **`_put_conn` called once per path:**
    Review `ingest()` body visually. Three exit paths:
    - success → `store._put_conn(conn)` before return
    - `KBLIngestError` re-raise → `store._put_conn(conn)` before raise
    - generic exception → `store._put_conn(conn)` before `raise RuntimeError(...)`
    Confirm via diff inspection.

## Verification SQL

Optional (post-deploy AI Head smoke):

```sql
-- Confirm new wiki_pages row + matching baker_actions entry landed after a test ingest
SELECT wp.id, wp.slug, wp.page_type, wp.agent_owner, wp.generation, wp.updated_at,
       ba.id AS action_id, ba.action_type, ba.trigger_source
FROM wiki_pages wp
LEFT JOIN baker_actions ba
  ON ba.action_type = 'kbl:ingest:' || REPLACE(wp.page_type, 'kbl_', '')
  AND ba.trigger_source = wp.updated_by
  AND ba.created_at > wp.updated_at - INTERVAL '5 seconds'
ORDER BY wp.updated_at DESC
LIMIT 10;
```

## Rollback

- `git revert <merge-sha>` — removes the 3 files. Runtime code doesn't call the endpoint yet (callers are M1+ downstream), so revert is safe.
- No DB migration to reverse.

---

## Ship shape

- **PR title:** `KBL_INGEST_ENDPOINT_1: POST /api/kbl/ingest single wiki-write chokepoint (CHANDA #2 atomic + Gold mirror)`
- **Branch:** `kbl-ingest-endpoint-1`
- **Files:** 3 — 2 new + 1 modified.
- **Commit style:** `kbl(ingest): single chokepoint endpoint + atomic wiki_pages/ledger/Qdrant + Gold mirror staging`
- **Ship report:** `briefs/_reports/B1_kbl_ingest_endpoint_1_20260423.md`. Include all 11 Quality Checkpoints + baseline pytest line + `git diff --stat`.

**Tier A auto-merge on B3 APPROVE + green CI** (standing per charter §3).

## Post-merge (AI Head, not B-code)

1. **Live-endpoint smoke** via the existing `/mcp` curl pattern or `X-Baker-Key` POST:
   ```
   curl -s -X POST "https://baker-master.onrender.com/api/kbl/ingest" \
     -H "X-Baker-Key: $BAKER_KEY" -H "Content-Type: application/json" \
     -d '{"frontmatter":{"type":"matter","slug":"hagenauer-rg7","name":"test","updated":"2026-04-23","author":"agent","tags":[],"related":[]},"body":"smoke"}' | jq .
   ```
   Expect `{"status":"ingested", ...}`. Verify wiki_pages row + baker_actions row landed atomically via `baker_raw_query`.
2. **Qdrant collection check** — confirm `baker-wiki` collection exists (or is auto-created on first upsert; if not, add it via a separate tiny one-off brief).
3. **Director-facing nothing** — endpoint is internal. No UI change.
4. Log to `actions_log.md`.

## Timebox

**3–3.5h.** If >5h, stop and report — likely sqlite3 SQL-translation friction or route-registration conflict.

**Working dir:** `~/bm-b1`.
