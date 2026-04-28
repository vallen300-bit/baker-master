"""Cortex Phase 2 (load) — unified context loader.

Reads from the baker-vault mirror and Postgres:

  Vault (read-only, optional — graceful when BAKER_VAULT_PATH missing):
    wiki/matters/<slug>/cortex-config.md  — matter system prompt + frontmatter
    wiki/matters/<slug>/state.md          — current matter state
    wiki/matters/<slug>/proposed-gold.md  — Director-confirmed insights
    wiki/matters/<slug>/curated/*.md      — accumulated capability outputs
    wiki/_cortex/director-gold-global.md
    wiki/_cortex/cross-matter-patterns.md
    wiki/_cortex/brisen-style.md

  Postgres (recent activity, 14d default window):
    sent_emails           — Director outbound mentioning the matter slug
    signal_queue + email_messages — entity inbound for this matter
    baker_actions         — Baker writes referencing the matter

Schema deviations from BRIEF_CORTEX_3T_FORMALIZE_1A (caught in EXPLORE per
Lesson #44):
  - email_messages has NO primary_matter column — joins via signal_queue
    (which definitively has primary_matter per migration 20260418_step1_*)
  - sent_emails uses body_preview, not body / full_body

Spec: _ops/ideas/2026-04-27-cortex-3t-formalize-spec.md (RA-22)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 200KB cap on any single .md file to prevent OOM on accidentally-huge curated
# entries. Empirically sufficient for cortex-config + state + curated outputs.
MAX_FILE_BYTES = 200_000

DEFAULT_RECENT_DAYS = 14


def _vault_root() -> Path:
    """Resolve BAKER_VAULT_PATH, defaulting to ~/baker-vault (matches the
    convention used by orchestrator/gold_audit_job and triggers/embedded_scheduler).
    """
    return Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))


def _get_store():
    """Resolve the SentinelStoreBack singleton. Module-level so tests can
    monkeypatch a fake without fighting ``memory.store_back`` attribute
    pollution from earlier tests in the suite.
    """
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


async def load_phase2_context(
    matter_slug: str,
    days: int = DEFAULT_RECENT_DAYS,
) -> dict[str, Any]:
    """Load matter config + curated + cortex-meta + recent activity.

    Returns a dict with keys (always present, but may be empty):
        matter_config (str), state (str), proposed_gold (str),
        curated (dict[str, str]), cortex_meta (dict[str, str]),
        recent_activity (dict[str, list]).

    On vault unavailable, the vault-sourced keys are empty but the SQL-sourced
    `recent_activity` still runs. On DB unavailable, recent_activity values are
    empty lists. No exceptions cross the boundary — Phase 2 is graceful.
    """
    vault = _vault_root()
    vault_available = vault.is_dir()
    if not vault_available:
        logger.warning(
            "BAKER_VAULT_PATH=%s does not exist; Phase 2 returns empty vault context",
            vault,
        )

    matter_dir = (vault / "wiki" / "matters" / matter_slug) if vault_available else None
    matter_dir_available = bool(matter_dir and matter_dir.is_dir())

    if vault_available and not matter_dir_available:
        logger.warning(
            "Matter dir %s not found; Phase 2 returns empty matter context",
            matter_dir,
        )

    return {
        "matter_config":   _read_or_empty(matter_dir / "cortex-config.md") if matter_dir_available else "",
        "state":           _read_or_empty(matter_dir / "state.md") if matter_dir_available else "",
        "proposed_gold":   _read_or_empty(matter_dir / "proposed-gold.md") if matter_dir_available else "",
        "curated":         _load_curated_dir(matter_dir / "curated") if matter_dir_available else {},
        "cortex_meta":     _load_cortex_meta(vault) if vault_available else {},
        "recent_activity": await _load_recent_activity(matter_slug, days),
        "vault_available": vault_available,
    }


# --------------------------------------------------------------------------
# Vault readers
# --------------------------------------------------------------------------


def _read_or_empty(p: Path, max_bytes: int = MAX_FILE_BYTES) -> str:
    """Read .md file; cap at max_bytes; return empty if missing or unreadable."""
    if not p.is_file():
        return ""
    try:
        size = p.stat().st_size
        if size > max_bytes:
            logger.warning(f"{p} exceeds {max_bytes} bytes ({size}); truncating")
        return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except Exception as e:
        logger.error(f"Failed to read {p}: {e}")
        return ""


def _load_curated_dir(curated_dir: Path) -> dict[str, str]:
    """Load all .md files under curated/ as {filename: content}.

    Sorted for determinism; empty dict if directory missing.
    """
    if not curated_dir.is_dir():
        return {}
    result = {}
    for f in sorted(curated_dir.glob("*.md")):
        result[f.name] = _read_or_empty(f)
    return result


def _load_cortex_meta(vault: Path) -> dict[str, str]:
    """Load wiki/_cortex/{director-gold-global,cross-matter-patterns,brisen-style}.md."""
    cortex_dir = vault / "wiki" / "_cortex"
    return {
        "director_gold_global":  _read_or_empty(cortex_dir / "director-gold-global.md"),
        "cross_matter_patterns": _read_or_empty(cortex_dir / "cross-matter-patterns.md"),
        "brisen_style":          _read_or_empty(cortex_dir / "brisen-style.md"),
    }


# --------------------------------------------------------------------------
# Postgres recent-activity reader (3 SQL queries, all LIMIT-bounded)
# --------------------------------------------------------------------------


async def _load_recent_activity(matter_slug: str, days: int) -> dict[str, list]:
    """Director outbound + entity inbound + baker_actions for this matter.

    Schema corrections vs brief snippet (verified 2026-04-28 by EXPLORE step):
      - sent_emails: column is `body_preview` (NOT `body` / `full_body`)
      - email_messages: NO primary_matter column — JOIN through signal_queue
        which carries primary_matter (per migration 20260418_step1_*)
      - baker_actions: target_task_id + payload jsonb (matches brief)
    """
    result = {"director_outbound": [], "entity_inbound": [], "baker_actions": []}
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        logger.warning(
            "_load_recent_activity: no DB connection; returning empty activity"
        )
        return result

    try:
        cur = conn.cursor()

        # 1) Director outbound — sent_emails matching the matter slug in
        #    subject or body_preview within the last N days.
        cur.execute(
            """
            SELECT subject, to_address, created_at
            FROM sent_emails
            WHERE created_at >= NOW() - (%s || ' days')::interval
              AND (subject ILIKE %s OR body_preview ILIKE %s)
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (str(days), f"%{matter_slug}%", f"%{matter_slug}%"),
        )
        result["director_outbound"] = [
            {
                "subject": r[0],
                "to": r[1],
                "created_at": r[2].isoformat() if r[2] else None,
            }
            for r in cur.fetchall()
        ]

        # 2) Entity inbound — email_messages joined to signal_queue on
        #    Gmail message-id, filtered by signal_queue.primary_matter.
        cur.execute(
            """
            SELECT em.subject, em.sender_email, em.received_date
            FROM email_messages em
            JOIN signal_queue sq
              ON sq.payload->>'message_id' = em.message_id
            WHERE em.received_date >= NOW() - (%s || ' days')::interval
              AND sq.primary_matter = %s
            ORDER BY em.received_date DESC
            LIMIT 30
            """,
            (str(days), matter_slug),
        )
        result["entity_inbound"] = [
            {
                "subject": r[0],
                "from": r[1],
                "received_at": r[2].isoformat() if r[2] else None,
            }
            for r in cur.fetchall()
        ]

        # 3) baker_actions — references in target_task_id or jsonb payload.
        cur.execute(
            """
            SELECT action_type, target_task_id, created_at
            FROM baker_actions
            WHERE created_at >= NOW() - (%s || ' days')::interval
              AND (target_task_id ILIKE %s OR payload::text ILIKE %s)
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (str(days), f"%{matter_slug}%", f"%{matter_slug}%"),
        )
        result["baker_actions"] = [
            {
                "action_type": r[0],
                "target": r[1],
                "created_at": r[2].isoformat() if r[2] else None,
            }
            for r in cur.fetchall()
        ]
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"_load_recent_activity failed for {matter_slug}: {e}")
    finally:
        store._put_conn(conn)
    return result
