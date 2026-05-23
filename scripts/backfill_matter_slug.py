"""DEADLINE_MATTER_SLUG_BACKFILL_1 — retroactive matter_slug backfill (Scope B).

Dry-run-by-default tool that proposes ``deadlines.matter_slug`` values for
rows where the column is NULL, by calling the classifier
(``orchestrator.pipeline._match_matter_slug``) and resolving the matter_name
through ``kbl.slug_registry.normalize`` to a canonical slug.

Behavior:
  Default (no args) → DRY RUN: write proposal to
    /tmp/backfill_matter_slug_proposal_<ts>.md
  ``--apply <path>``  → write mode: UPDATE rows per ratified file
    (3 safety rails + per-row SAVEPOINT).

Safety rails on --apply:
  1. Ratified mapping file path required (positional after --apply).
  2. Mapping file must be <24h old (mtime check).
  3. Every M-section row must have non-empty proposed_slug.
  4. ``BAKER_BACKFILL_DRY_RUN_ONLY=1`` env-var override blocks --apply entirely.

Per-row SAVEPOINT pattern fixes the predecessor v2_followup bug where a
single mid-batch UPDATE error rolled back all prior successful UPDATEs in
the transaction. Each row gets ``SAVEPOINT row_sp`` / ``RELEASE`` / on error
``ROLLBACK TO SAVEPOINT row_sp`` so the loop can continue.

Usage:
  python3 scripts/backfill_matter_slug.py                          # dry run
  python3 scripts/backfill_matter_slug.py --apply <ratified.md>    # write

Reads:
  - deadlines table (SELECT id, description, source_snippet, source_type)
  - matter_registry via ``SentinelStoreBack._get_global_instance``
    (the classifier reads it)
  - baker-vault/slugs.yml via ``kbl.slug_registry``

Writes:
  - Dry run: /tmp/backfill_matter_slug_proposal_<UTC-ts>.md
  - Apply: UPDATE deadlines SET matter_slug = ...
    (idempotent — only where matter_slug IS NULL)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbl import slug_registry  # noqa: E402
from models.deadlines import get_conn, put_conn  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_matter_slug")

QUERY_LIMIT = 500            # belt-and-suspenders; brief notes ~69 rows
APPLY_STALENESS_SEC = 24 * 3600
DESC_TRUNCATE = 80


def _check_required_env() -> None:
    """Fail fast if required envs are missing. Lists all missing in one error.

    Uniform fail-fast: runs on every invocation (dry-run + --apply) — heavy
    init below (SentinelStoreBack → voyage client + pg pool) raises cryptic
    errors when envs are absent. AC4(b): same behavior every path.
    """
    required: list[str] = []
    # Voyage client (used in SentinelStoreBack init)
    if not os.environ.get("VOYAGE_API_KEY"):
        required.append("VOYAGE_API_KEY")
    # Postgres: DATABASE_URL takes precedence; otherwise split vars required
    # (mirrors kbl/db.py _build_dsn() precedence; POSTGRES_PORT optional;
    # POSTGRES_SSLMODE not consulted by the connect path, so not listed).
    if not os.environ.get("DATABASE_URL"):
        for var in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
            if not os.environ.get(var):
                required.append(var)
    if required:
        msg = (
            "ERROR: missing required environment variables:\n"
            + "\n".join(f"  - {v}" for v in required)
            + "\nSet these in your shell or source from 1Password.\n"
            + "Examples:\n"
            + "  export VOYAGE_API_KEY=\"$(op read 'op://Baker API Keys/VOYAGE_API_KEY/credential')\"\n"
            + "  # ... etc\n"
            + "Exiting (no init was performed)."
        )
        print(msg, file=sys.stderr)
        sys.exit(2)


def _query_null_matter_slug() -> list[tuple]:
    """SELECT active/pending_confirm deadlines with NULL matter_slug.

    Returns rows of (id, description, source_snippet, source_type).
    """
    conn = get_conn()
    if conn is None:
        raise RuntimeError("get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, description, source_snippet, source_type
                FROM deadlines
                WHERE status IN ('active', 'pending_confirm')
                  AND matter_slug IS NULL
                ORDER BY id
                LIMIT %s
                """,
                (QUERY_LIMIT,),
            )
            rows = cur.fetchall()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
    finally:
        try:
            put_conn(conn)
        except Exception:
            pass
    return list(rows)


def _classify(rows: list[tuple]) -> tuple[list[dict], list[dict]]:
    """Return (bucket_M, bucket_U).

    M (Matched):   classifier returned a name + normalize resolved to canonical.
    U (Unmatched): classifier returned None OR normalize returned None.

    There is no Ambiguous bucket — the classifier itself returns at most one
    best-scoring match, and normalize is a deterministic lookup.
    """
    from orchestrator.pipeline import _match_matter_slug
    from memory.store_back import SentinelStoreBack

    store = SentinelStoreBack._get_global_instance()

    m_rows: list[dict] = []
    u_rows: list[dict] = []
    for row in rows:
        rid, desc, snippet, source_type = row
        record = {
            "id": rid,
            "description": (desc or "")[:DESC_TRUNCATE],
            "source_type": source_type or "",
            "matter_name_raw": None,
            "proposed_slug": None,
            "bucket_reason": "",
        }
        try:
            matter_name = _match_matter_slug(desc or "", snippet or "", store)
        except Exception as e:
            record["bucket_reason"] = f"classifier raised: {e}"
            u_rows.append(record)
            continue
        record["matter_name_raw"] = matter_name
        if matter_name is None:
            record["bucket_reason"] = "classifier returned None (no match)"
            u_rows.append(record)
            continue
        canonical = slug_registry.normalize(matter_name)
        if canonical is None:
            record["bucket_reason"] = (
                f"matter_name {matter_name!r} does not resolve to a canonical slug"
            )
            u_rows.append(record)
            continue
        record["proposed_slug"] = canonical
        record["bucket_reason"] = f"classified → {canonical}"
        m_rows.append(record)
    return m_rows, u_rows


def _format_row(r: dict) -> str:
    raw = r["matter_name_raw"] or "—"
    prop = r["proposed_slug"] or "—"
    return (
        f"| {r['id']} | {r['description']} | {raw} → {prop} | "
        f"{r['source_type']} | {r['bucket_reason']} |"
    )


def _write_proposal(
    m_rows: list[dict],
    u_rows: list[dict],
    out_path: Path,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append(f"# Backfill proposal (matter_slug) — generated {ts}")
    lines.append("")
    lines.append(f"- Bucket M (Matched, auto-apply candidate): **{len(m_rows)} rows**")
    lines.append(f"- Bucket U (Unmatched, manual review):      **{len(u_rows)} rows**")
    lines.append("")
    lines.append("Director: ratify the M-section block as-is OR reply with adjustments.")
    lines.append("The ratified-mapping file is the input to `--apply`.")
    lines.append("")
    for label, bucket in (("M (Matched)", m_rows), ("U (Unmatched)", u_rows)):
        lines.append(f"## Bucket {label} — {len(bucket)} rows")
        lines.append("")
        if not bucket:
            lines.append("_(empty)_")
            lines.append("")
            continue
        lines.append("| id | description | matter_name raw → canonical slug | source_type | reason |")
        lines.append("|---:|---|---|---|---|")
        for r in bucket:
            lines.append(_format_row(r))
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_ratified_mapping(path: Path) -> list[tuple[int, str]]:
    """Read the ratified-mapping markdown file. Pull rows from the Bucket M
    table. Return list of (id, proposed_slug). Raise on partials.
    """
    text = path.read_text(encoding="utf-8")
    out: list[tuple[int, str]] = []
    in_m_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## Bucket M"):
            in_m_section = True
            continue
        if line.startswith("## Bucket "):
            in_m_section = False
            continue
        if not in_m_section:
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5:
            continue
        # Skip header + separator
        if cells[0].lower() == "id" or set(cells[0]) <= {"-", ":"}:
            continue
        try:
            rid = int(cells[0])
        except ValueError:
            continue
        # cells[2] = "matter_name raw → canonical slug" e.g. "Cupial → cupial"
        raw_arrow = cells[2]
        if "→" in raw_arrow:
            proposed = raw_arrow.split("→", 1)[1].strip()
        else:
            proposed = raw_arrow.strip()
        if not proposed or proposed == "—":
            raise RuntimeError(
                f"row id={rid} in ratified mapping has empty proposed_slug — "
                "every M-section row must have a canonical slug"
            )
        out.append((rid, proposed))
    return out


def _apply_updates(pairs: list[tuple[int, str]]) -> dict:
    """Run idempotent UPDATEs with per-row SAVEPOINT.

    Fixes predecessor v2_followup: per-row error rolls back only that row,
    not the whole transaction. Prior successful UPDATEs survive to commit.
    """
    affected = 0
    skipped = 0
    failed: list[dict] = []
    conn = get_conn()
    if conn is None:
        raise RuntimeError("get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            for rid, slug in pairs:
                cur.execute("SAVEPOINT row_sp")
                try:
                    cur.execute(
                        """
                        UPDATE deadlines
                        SET matter_slug = %s,
                            updated_at = NOW()
                        WHERE id = %s
                          AND matter_slug IS NULL
                        """,
                        (slug, rid),
                    )
                    if cur.rowcount > 0:
                        affected += cur.rowcount
                        cur.execute("RELEASE SAVEPOINT row_sp")
                        logger.info("UPDATE id=%s matter_slug=%s OK", rid, slug)
                    else:
                        skipped += 1
                        cur.execute("RELEASE SAVEPOINT row_sp")
                        logger.info(
                            "SKIP id=%s (already populated or row missing)", rid,
                        )
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                    failed.append({"id": rid, "error": str(e)})
                    logger.warning("UPDATE id=%s FAILED: %s", rid, e)
            try:
                conn.commit()
            except Exception as e:
                logger.warning("commit failed: %s", e)
        finally:
            cur.close()
    finally:
        try:
            put_conn(conn)
        except Exception:
            pass
    return {"affected": affected, "skipped": skipped, "failed": failed}


def _query_stray_matter_slugs() -> list[tuple]:
    """SELECT rows where matter_slug is non-NULL but not in the canonical set.

    Returns rows of (id, matter_slug, description). DEADLINE_SIGNAL_HYGIENE_1
    Scope C: pre-apply audit, surfaces raw matter_name leaks (e.g.
    'Oskolkov-RG7', 'Financing Vienna & Baden-Baden') that bypassed the
    canonical-slug normalize() return.
    """
    conn = get_conn()
    if conn is None:
        raise RuntimeError("get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, matter_slug, description
                FROM deadlines
                WHERE matter_slug IS NOT NULL
                  AND matter_slug != ''
                ORDER BY id
                LIMIT %s
                """,
                (QUERY_LIMIT,),
            )
            rows = cur.fetchall()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            cur.close()
        return list(rows)
    finally:
        try:
            put_conn(conn)
        except Exception:
            pass


def _classify_strays(rows: list[tuple]) -> tuple[list, list]:
    """Partition stray rows into (fixable, null_out).

    fixable = (id, current_slug, normalized_slug) — re-normalize() produces
              a canonical slug; UPDATE deadlines SET matter_slug = normalized.
    null_out = (id, current_slug, None) — no canonical match; UPDATE
              deadlines SET matter_slug = NULL.
    """
    canonical = slug_registry.canonical_slugs()
    fixable: list[tuple] = []
    null_out: list[tuple] = []
    for rid, current_slug, _desc in rows:
        if current_slug in canonical:
            continue  # already canonical — not a stray
        normalized = slug_registry.normalize(current_slug)
        if normalized and normalized in canonical:
            fixable.append((rid, current_slug, normalized))
        else:
            null_out.append((rid, current_slug, None))
    return fixable, null_out


def _parse_stray_proposal(
    path: Path,
) -> tuple[list[tuple], list[tuple]]:
    """Read the ratified Scope C cleanup proposal markdown file. Pull rows
    from Bucket F (fixable) + Bucket N (null_out). Return
    (fixable, null_out) where each entry is (id, current_slug, proposed)
    — proposed is the canonical slug for fixable, None for null_out.

    Raises RuntimeError on a Bucket F row whose proposed slug is missing.
    Mirrors the audit pattern of _parse_ratified_mapping() — apply runs
    EXACTLY on the rows ratified, never on a fresh re-derivation.
    """
    text = path.read_text(encoding="utf-8")
    fixable: list[tuple] = []
    null_out: list[tuple] = []
    section: Optional[str] = None  # "F" or "N" or None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## Bucket F"):
            section = "F"
            continue
        if line.startswith("## Bucket N"):
            section = "N"
            continue
        if line.startswith("## "):
            section = None
            continue
        if section not in ("F", "N"):
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        # Skip header + separator
        if cells[0].lower() == "id" or set(cells[0]) <= {"-", ":"}:
            continue
        try:
            rid = int(cells[0])
        except ValueError:
            continue
        current = cells[1].strip("`").strip()
        if section == "F":
            if len(cells) < 3:
                raise RuntimeError(
                    f"Bucket F row id={rid} missing proposed_slug column"
                )
            proposed = cells[2].strip("`").strip()
            if not proposed or proposed == "—":
                raise RuntimeError(
                    f"row id={rid} in Bucket F has empty proposed_slug — "
                    "every fixable row must have a canonical slug"
                )
            fixable.append((rid, current, proposed))
        else:
            null_out.append((rid, current, None))
    return fixable, null_out


def _write_stray_proposal(
    fixable: list[tuple], null_out: list[tuple], path: Path
) -> None:
    """Emit a markdown proposal file for stray cleanup (mirrors backfill format)."""
    lines: list[str] = []
    lines.append("# DEADLINE_SIGNAL_HYGIENE_1 — Scope C stray cleanup proposal")
    lines.append("")
    lines.append(
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    lines.append(
        f"Total stray rows: {len(fixable) + len(null_out)} "
        f"(fixable={len(fixable)}, null_out={len(null_out)})"
    )
    lines.append("")
    lines.append("## Bucket F — Fixable (UPDATE matter_slug = canonical)")
    lines.append("")
    if fixable:
        lines.append("| id | current_slug | proposed_slug |")
        lines.append("|----|--------------|---------------|")
        for rid, current, proposed in fixable:
            lines.append(f"| {rid} | `{current}` | `{proposed}` |")
    else:
        lines.append("_(none)_")
    lines.append("")
    lines.append("## Bucket N — Null-out (UPDATE matter_slug = NULL)")
    lines.append("")
    if null_out:
        lines.append("| id | current_slug |")
        lines.append("|----|--------------|")
        for rid, current, _ in null_out:
            lines.append(f"| {rid} | `{current}` |")
    else:
        lines.append("_(none)_")
    lines.append("")
    lines.append(
        "Apply via: `python3 scripts/backfill_matter_slug.py "
        "--cleanup-strays --apply` (Director-gated)"
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _apply_stray_cleanup(
    fixable: list[tuple], null_out: list[tuple]
) -> dict:
    """Per-row SAVEPOINT pattern. Idempotent re-runs are safe because the
    next dry-run re-classifies and only acts on remaining strays.
    """
    conn = get_conn()
    if conn is None:
        raise RuntimeError("get_conn returned None — DB unreachable")
    affected = 0
    failed: list[tuple] = []
    try:
        cur = conn.cursor()
        try:
            for rid, _current, proposed in fixable:
                try:
                    cur.execute("SAVEPOINT row_sp")
                    cur.execute(
                        "UPDATE deadlines SET matter_slug = %s, updated_at = NOW() "
                        "WHERE id = %s AND matter_slug IS NOT NULL "
                        "  AND matter_slug NOT IN (SELECT %s)",
                        (proposed, rid, proposed),
                    )
                    cur.execute("RELEASE SAVEPOINT row_sp")
                    affected += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                    failed.append((rid, str(e)[:120]))
            for rid, _current, _ in null_out:
                try:
                    cur.execute("SAVEPOINT row_sp")
                    cur.execute(
                        "UPDATE deadlines SET matter_slug = NULL, updated_at = NOW() "
                        "WHERE id = %s AND matter_slug IS NOT NULL",
                        (rid,),
                    )
                    cur.execute("RELEASE SAVEPOINT row_sp")
                    affected += 1
                except Exception as e:
                    cur.execute("ROLLBACK TO SAVEPOINT row_sp")
                    failed.append((rid, str(e)[:120]))
            try:
                conn.commit()
            except Exception as e:
                logger.warning("commit failed: %s", e)
        finally:
            cur.close()
    finally:
        try:
            put_conn(conn)
        except Exception:
            pass
    return {"affected": affected, "failed": failed}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Backfill deadlines.matter_slug via classifier (dry-run by default)",
    )
    p.add_argument(
        "--apply", metavar="RATIFIED_FILE",
        help="Path to Director-ratified proposal file; runs UPDATEs. "
             "Default is DRY RUN (no --apply). For backfill, points to the "
             "main proposal (Bucket M). For --cleanup-strays, points to "
             "the stray-cleanup proposal (Bucket F + Bucket N).",
    )
    p.add_argument(
        "--cleanup-strays", action="store_true",
        help="DEADLINE_SIGNAL_HYGIENE_1 Scope C: identify rows where "
             "matter_slug is non-NULL but not canonical; dry-run produces "
             "proposal of fixable + null_out buckets. With --apply <path>, "
             "applies the rows ratified in that proposal file (24h staleness "
             "guard mirrors the main --apply pattern).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    _check_required_env()  # FAIL FAST before any heavy init
    args = _build_arg_parser().parse_args(argv)

    # DEADLINE_SIGNAL_HYGIENE_1 Scope C path — separate from main backfill.
    if args.cleanup_strays:
        if args.apply:
            # Director-gated apply: parse the ratified proposal file +
            # apply only those rows. No re-derivation at exec time —
            # otherwise prod state drift between dry-run + apply could
            # silently widen the applied set beyond what was ratified.
            # Safety rail 4: env-var kill switch
            if os.environ.get("BAKER_BACKFILL_DRY_RUN_ONLY") == "1":
                logger.error("BAKER_BACKFILL_DRY_RUN_ONLY=1 — --apply blocked")
                return 2
            ratified_path = Path(args.apply)
            # Safety rail 1: ratified file must exist
            if not ratified_path.is_file():
                logger.error("ratified proposal file not found: %s", ratified_path)
                return 2
            # Safety rail 2: 24h staleness guard
            age = time.time() - ratified_path.stat().st_mtime
            if age > APPLY_STALENESS_SEC:
                logger.error(
                    "ratified file is %.1fh old (>24h staleness limit); "
                    "regenerate proposal via --cleanup-strays",
                    age / 3600,
                )
                return 2
            # Safety rail 3: parser enforces non-empty proposed_slug on Bucket F
            fixable, null_out = _parse_stray_proposal(ratified_path)
            if not fixable and not null_out:
                logger.error(
                    "no rows found in Bucket F or Bucket N of %s — "
                    "nothing to apply",
                    ratified_path,
                )
                return 2
            logger.info(
                "Scope C APPLY mode: F=%d N=%d rows from %s",
                len(fixable), len(null_out), ratified_path,
            )
            summary = _apply_stray_cleanup(fixable, null_out)
            logger.info(
                "Scope C APPLY summary: affected=%d failed=%d",
                summary["affected"], len(summary["failed"]),
            )
            return 0 if not summary["failed"] else 1

        # DRY RUN — derive strays + write proposal
        rows = _query_stray_matter_slugs()
        fixable, null_out = _classify_strays(rows)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = Path(f"/tmp/cleanup_stray_matter_slugs_{ts}.md")
        _write_stray_proposal(fixable, null_out, out_path)
        logger.info(
            "Scope C DRY RUN: %d stray | F=%d N=%d → %s",
            len(fixable) + len(null_out), len(fixable), len(null_out), out_path,
        )
        print(str(out_path))
        return 0

    if args.apply:
        # Safety rail 4: env-var kill switch
        if os.environ.get("BAKER_BACKFILL_DRY_RUN_ONLY") == "1":
            logger.error("BAKER_BACKFILL_DRY_RUN_ONLY=1 — --apply blocked")
            return 2
        ratified_path = Path(args.apply)
        if not ratified_path.is_file():
            logger.error("ratified file not found: %s", ratified_path)
            return 2
        # Safety rail 2: staleness guard (24h)
        age = time.time() - ratified_path.stat().st_mtime
        if age > APPLY_STALENESS_SEC:
            logger.error(
                "ratified file is %.1fh old (>24h staleness limit); regenerate proposal",
                age / 3600,
            )
            return 2
        # Safety rail 3: parser enforces no partial rows
        pairs = _parse_ratified_mapping(ratified_path)
        if not pairs:
            logger.error("no rows found in Bucket M of %s — nothing to apply", ratified_path)
            return 2
        logger.info("APPLY mode: %d rows from %s", len(pairs), ratified_path)
        summary = _apply_updates(pairs)
        logger.info(
            "APPLY summary: affected=%d skipped=%d failed=%d",
            summary["affected"], summary["skipped"], len(summary["failed"]),
        )
        return 0 if not summary["failed"] else 1

    # DRY RUN
    rows = _query_null_matter_slug()
    m_rows, u_rows = _classify(rows)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(f"/tmp/backfill_matter_slug_proposal_{ts}.md")
    _write_proposal(m_rows, u_rows, out_path)
    logger.info(
        "DRY RUN complete: %d total | M=%d U=%d → %s",
        len(rows), len(m_rows), len(u_rows), out_path,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
