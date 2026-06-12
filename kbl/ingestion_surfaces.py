"""Canonical ingestion-surface list loader.

The source of truth is baker-vault:
``_ops/processes/ingestion-surfaces.md``. Baker-master reads it through the
existing Render vault mirror so AH1 can update the vault file without a
dashboard code change.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

INGESTION_SURFACES_PATH = "_ops/processes/ingestion-surfaces.md"
_CACHE_TTL_SECONDS = 300
_CACHE: dict[str, Any] = {"expires_at": 0.0, "snapshot": None}


def _parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown

    end = markdown.find("\n---", 4)
    if end == -1:
        return {}, markdown

    raw = markdown[4:end]
    body = markdown[end + len("\n---") :].lstrip()
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def _parse_table_rows(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    in_table = False

    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        if cells[0] == "#" or set(cells[0]) <= {"-"}:
            in_table = True
            continue
        if set(cells[1]) <= {"-"}:
            in_table = True
            continue

        try:
            surface_no = int(cells[0])
        except ValueError:
            continue

        in_table = True
        rows.append(
            {
                "number": surface_no,
                "surface": cells[1],
                "contents": cells[2],
                "access": cells[3],
                "sweep": cells[4],
            }
        )

    return rows


def parse_ingestion_surfaces_markdown(
    markdown: str,
    *,
    source_path: str = INGESTION_SURFACES_PATH,
    last_commit_sha: str | None = None,
    sha256: str | None = None,
) -> dict[str, Any]:
    """Parse the canonical vault markdown into the API shape."""
    meta, body = _parse_frontmatter(markdown or "")
    rows = _parse_table_rows(body)
    return {
        "version": meta.get("version"),
        "ratified": meta.get("ratified"),
        "owner": meta.get("owner"),
        "purpose": meta.get("purpose"),
        "source_path": source_path,
        "source_last_commit_sha": last_commit_sha,
        "source_sha256": sha256,
        "row_count": len(rows),
        "surfaces": rows,
        "error": None,
    }


def _error_snapshot(message: str) -> dict[str, Any]:
    return {
        "version": None,
        "ratified": None,
        "owner": None,
        "purpose": None,
        "source_path": INGESTION_SURFACES_PATH,
        "source_last_commit_sha": None,
        "source_sha256": None,
        "row_count": 0,
        "surfaces": [],
        "error": message,
    }


def load_ingestion_surfaces(*, force_refresh: bool = False) -> dict[str, Any]:
    """Load surfaces from the vault mirror with a short in-process cache."""
    now = time.monotonic()
    cached = _CACHE.get("snapshot")
    if not force_refresh and cached and now < float(_CACHE.get("expires_at") or 0):
        return cached

    try:
        from vault_mirror import read_ops_file

        record = read_ops_file(INGESTION_SURFACES_PATH)
        if record.get("error"):
            snapshot = _error_snapshot(str(record.get("error")))
        else:
            snapshot = parse_ingestion_surfaces_markdown(
                record.get("content_utf8") or "",
                source_path=record.get("path") or INGESTION_SURFACES_PATH,
                last_commit_sha=record.get("last_commit_sha"),
                sha256=record.get("sha256"),
            )
    except Exception as exc:  # noqa: BLE001 - prompt/UI must degrade gracefully.
        logger.warning("ingestion surfaces load failed: %s", exc)
        snapshot = _error_snapshot(str(exc))

    _CACHE["snapshot"] = snapshot
    _CACHE["expires_at"] = now + _CACHE_TTL_SECONDS
    return snapshot


def build_ingestion_surfaces_prompt_block() -> str:
    """Return a compact prompt block for Ask Baker, or empty on failure."""
    snapshot = load_ingestion_surfaces()
    rows = snapshot.get("surfaces") or []
    if not rows:
        return ""

    header = (
        "## CANONICAL INGESTION SURFACES\n"
        "When asked what data surfaces Baker sweeps, use this current "
        "baker-vault checklist. Fill every row for full sweeps; topic rows "
        "may be skipped only with a written reason.\n\n"
        "| # | Surface | Access | Sweep |\n"
        "|---|---------|--------|-------|"
    )
    table = "\n".join(
        f"| {row['number']} | {row['surface']} | {row['access']} | {row['sweep']} |"
        for row in rows
    )
    version = snapshot.get("version") or "unknown"
    ratified = snapshot.get("ratified") or "unknown"
    return f"{header}\n{table}\n\nVersion: {version}. Ratified: {ratified}."
