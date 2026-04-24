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
