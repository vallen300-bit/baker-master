"""DEADLINE_ASSIGNED_TO_BACKFILL_1 — desk attribution backfill (Scope A).

Dry-run-by-default tool that proposes `deadlines.assigned_to` values from
`matter_slug` via the canonical desk-matter map, surfaces unmapped rows for
Director review, and (on `--apply` with a Director-ratified mapping file)
executes the bulk UPDATE.

Behavior:
  Default (no args) → DRY RUN: write proposal to /tmp/backfill_assigned_to_proposal_<ts>.md
  `--apply <path>`  → write mode: UPDATE rows per ratified file (3 safety rails)

Safety rails on --apply:
  1. Ratified mapping file path required (positional after --apply).
  2. Mapping file must be <24h old (mtime check).
  3. Every row must have non-empty proposed assigned_to (no partials).
  4. `BAKER_BACKFILL_DRY_RUN_ONLY=1` env-var override blocks --apply entirely.

Usage:
  python3 scripts/backfill_assigned_to.py                          # dry run
  python3 scripts/backfill_assigned_to.py --apply <ratified.md>    # write mode

Reads:
  - baker-vault/_ops/agents/_desk-matter-map.yml (desk → [matter_slug])
  - baker-vault/slugs.yml (canonical slugs + aliases via kbl.slug_registry)
  - deadlines table (SELECT)

Writes:
  - Dry run: /tmp/backfill_assigned_to_proposal_<UTC-ts>.md
  - Apply: UPDATE deadlines SET assigned_to = ... (idempotent — only if still NULL/empty)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kbl import slug_registry  # noqa: E402
from models.deadlines import get_conn, put_conn  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("backfill_assigned_to")

DESK_MATTER_MAP_REL = "_ops/agents/_desk-matter-map.yml"
QUERY_LIMIT = 500          # belt-and-suspenders; brief Q5 says total ≈ 67
APPLY_STALENESS_SEC = 24 * 3600
DESC_TRUNCATE = 80


def _resolve_vault_path() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise RuntimeError("BAKER_VAULT_PATH unset; cannot locate desk-matter map")
    p = Path(vault)
    if not p.is_dir():
        raise RuntimeError(f"BAKER_VAULT_PATH does not exist or is not a directory: {p}")
    return p


def _load_desk_matter_map(vault: Path) -> dict[str, list[str]]:
    """Return matter_slug → list[desk_slug]. Inverse of the YAML's matters: section."""
    path = vault / DESK_MATTER_MAP_REL
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    matters = raw.get("matters") or {}
    if not isinstance(matters, dict):
        raise RuntimeError(f"{path}: 'matters:' key missing or not a dict")
    out: dict[str, list[str]] = {}
    for slug, desks in matters.items():
        if not isinstance(desks, list):
            raise RuntimeError(f"{path}: matters[{slug!r}] must be a list of desks")
        out[str(slug)] = [str(d) for d in desks]
    return out


def _query_active_unassigned() -> list[tuple]:
    """SELECT id, description, due_date, priority, matter_slug, severity
    FROM deadlines WHERE status='active' AND assigned_to NULL/empty.
    """
    conn = get_conn()
    if conn is None:
        raise RuntimeError("get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, description, due_date, priority, matter_slug, severity
                FROM deadlines
                WHERE status = 'active'
                  AND (assigned_to IS NULL OR assigned_to = '')
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


def _classify(
    rows: list[tuple],
    desk_matter_map: dict[str, list[str]],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (bucket_M, bucket_A, bucket_U).

    Bucket M (Mapped):    matter_slug → canonical → owned by exactly 1 desk.
    Bucket A (Ambiguous): matter_slug → canonical → owned by >1 desk.
    Bucket U (Unmapped):  matter_slug null, non-canonical, or canonical missing
                          from desk-matter-map.
    """
    m_rows: list[dict] = []
    a_rows: list[dict] = []
    u_rows: list[dict] = []
    for row in rows:
        rid, desc, due, prio, raw_slug, severity = row
        record = {
            "id": rid,
            "description": (desc or "")[:DESC_TRUNCATE],
            "due_date": due.isoformat() if due else "",
            "priority": prio or "",
            "severity": severity or "",
            "matter_slug_raw": raw_slug,
            "matter_slug_canonical": None,
            "proposed_assigned_to": None,
            "bucket_reason": "",
        }
        if not raw_slug:
            record["bucket_reason"] = "matter_slug NULL"
            u_rows.append(record)
            continue
        canonical = slug_registry.normalize(raw_slug)
        if canonical is None:
            record["bucket_reason"] = f"raw {raw_slug!r} does not resolve to a canonical slug"
            u_rows.append(record)
            continue
        record["matter_slug_canonical"] = canonical
        desks = desk_matter_map.get(canonical)
        if not desks:
            record["bucket_reason"] = f"canonical {canonical!r} not in desk-matter map"
            u_rows.append(record)
            continue
        if len(desks) == 1:
            record["proposed_assigned_to"] = desks[0]
            record["bucket_reason"] = f"single-desk owner ({desks[0]})"
            m_rows.append(record)
        else:
            record["bucket_reason"] = f"multi-desk ({len(desks)}): {', '.join(desks)}"
            a_rows.append(record)
    return m_rows, a_rows, u_rows


def _format_row(r: dict) -> str:
    raw = r["matter_slug_raw"] or "—"
    can = r["matter_slug_canonical"] or "—"
    prop = r["proposed_assigned_to"] or "—"
    return (
        f"| {r['id']} | {r['description']} | {raw} → {can} | "
        f"{prop} | {r['bucket_reason']} |"
    )


def _write_proposal(
    m_rows: list[dict],
    a_rows: list[dict],
    u_rows: list[dict],
    out_path: Path,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append(f"# Backfill proposal — generated {ts}")
    lines.append("")
    lines.append(f"- Bucket M (Mapped, auto-apply candidate): **{len(m_rows)} rows**")
    lines.append(f"- Bucket A (Ambiguous, manual review):     **{len(a_rows)} rows**")
    lines.append(f"- Bucket U (Unmapped, manual review):      **{len(u_rows)} rows**")
    lines.append("")
    lines.append("Director: ratify the M-section block as-is OR reply with adjustments.")
    lines.append("The ratified-mapping file is the input to `--apply`.")
    lines.append("")
    for label, bucket in (("M (Mapped)", m_rows), ("A (Ambiguous)", a_rows), ("U (Unmapped)", u_rows)):
        lines.append(f"## Bucket {label} — {len(bucket)} rows")
        lines.append("")
        if not bucket:
            lines.append("_(empty)_")
            lines.append("")
            continue
        lines.append("| id | description | matter_slug raw → canonical | proposed assigned_to | bucket-reason |")
        lines.append("|---:|---|---|---|---|")
        for r in bucket:
            lines.append(_format_row(r))
        lines.append("")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_ratified_mapping(path: Path) -> list[tuple[int, str]]:
    """Read the ratified-mapping markdown file. Pull rows from the Bucket M table
    (the only section eligible for auto-apply). Return list of (id, proposed_desk).
    Raise on partials (empty proposed_assigned_to).
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
        prop = cells[3]
        if not prop or prop == "—":
            raise RuntimeError(
                f"row id={rid} in ratified mapping has empty proposed assigned_to — "
                "every M-section row must have a desk"
            )
        out.append((rid, prop))
    return out


def _apply_updates(pairs: list[tuple[int, str]]) -> dict:
    """Run idempotent UPDATEs. Return summary dict."""
    affected = 0
    skipped = 0
    errors = 0
    conn = get_conn()
    if conn is None:
        raise RuntimeError("get_conn returned None — DB unreachable")
    try:
        cur = conn.cursor()
        try:
            for rid, desk in pairs:
                try:
                    cur.execute(
                        """
                        UPDATE deadlines
                        SET assigned_to = %s,
                            updated_at = NOW()
                        WHERE id = %s
                          AND (assigned_to IS NULL OR assigned_to = '')
                        """,
                        (desk, rid),
                    )
                    if cur.rowcount > 0:
                        affected += cur.rowcount
                        logger.info("UPDATE id=%s assigned_to=%s OK", rid, desk)
                    else:
                        skipped += 1
                        logger.info("SKIP id=%s (already assigned or not active)", rid)
                except Exception as e:
                    errors += 1
                    logger.warning("UPDATE id=%s FAILED: %s", rid, e)
                    try:
                        conn.rollback()
                    except Exception:
                        pass
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
    return {"affected": affected, "skipped": skipped, "errors": errors}


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Backfill deadlines.assigned_to from matter_slug")
    p.add_argument(
        "--apply", metavar="RATIFIED_FILE",
        help="Path to Director-ratified mapping file; runs UPDATEs. "
             "Default is DRY RUN (no --apply).",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    vault = _resolve_vault_path()
    desk_matter_map = _load_desk_matter_map(vault)

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
        # Safety rail 3: parser enforces no partial rows (raises if any empty desk)
        pairs = _parse_ratified_mapping(ratified_path)
        if not pairs:
            logger.error("no rows found in Bucket M of %s — nothing to apply", ratified_path)
            return 2
        logger.info("APPLY mode: %d rows from %s", len(pairs), ratified_path)
        summary = _apply_updates(pairs)
        logger.info(
            "APPLY summary: affected=%d skipped=%d errors=%d",
            summary["affected"], summary["skipped"], summary["errors"],
        )
        return 0 if summary["errors"] == 0 else 1

    # DRY RUN
    rows = _query_active_unassigned()
    m_rows, a_rows, u_rows = _classify(rows, desk_matter_map)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(f"/tmp/backfill_assigned_to_proposal_{ts}.md")
    _write_proposal(m_rows, a_rows, u_rows, out_path)
    logger.info(
        "DRY RUN complete: %d total | M=%d A=%d U=%d → %s",
        len(rows), len(m_rows), len(a_rows), len(u_rows), out_path,
    )
    print(str(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
