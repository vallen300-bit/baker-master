"""Run-once: provision directives.md for all non-retired matters.

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 (caller A).

Reads ``baker-vault/slugs.yml`` at run-time (live state, not snapshot). Filters
``status != retired``. Calls ``orchestrator.cortex_directives.provision_directive_schema``
for each. Stages writes to ``vault_scaffolding/live_mirror/v1/`` per CHANDA #9.

Idempotent: re-runs skip matters whose directives.md already exists.
Re-runnable safely after slugs.yml additions (live-organism friendly).

Usage::

    python scripts/migrate_directives_for_existing_matters.py [--dry-run] \\
                                                              [--force] \\
                                                              [--vault-root <path>] \\
                                                              [--staging-root <path>]

Exit codes:
    0 — all targeted matters provisioned (or skipped as no-op)
    2 — provisioning error mid-batch (partial completion logged)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.cortex_directives import provision_directive_schema  # noqa: E402

DEFAULT_VAULT_ROOT = Path.home() / "baker-vault"
DEFAULT_STAGING_ROOT = REPO_ROOT / "vault_scaffolding" / "live_mirror" / "v1" / "matters"

logger = logging.getLogger(__name__)


def load_active_matters(vault_root: Path) -> list[dict]:
    """Read slugs.yml; return list of {slug, name, status} for non-retired matters.

    Filters: ``status != 'retired'`` (per AI Head 1 Q3 ratification 2026-04-30).
    Includes both 'active' and 'development' streams.
    """
    slugs_yml = vault_root / "slugs.yml"
    if not slugs_yml.is_file():
        raise SystemExit(f"slugs.yml not found at {slugs_yml}")

    try:
        data = yaml.safe_load(slugs_yml.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SystemExit(f"slugs.yml parse error: {e}") from e

    matters = (data or {}).get("matters") or []
    out: list[dict] = []
    for row in matters:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug")
        status = row.get("status")
        if not slug or not isinstance(slug, str):
            continue
        if status == "retired":
            continue
        # Real slugs.yml rows have no `name:` key — derive a parseable display
        # name from the slug. Description is NOT a safe fallback: it contains
        # ': ', quotes, apostrophes that break unquoted YAML scalars in
        # render_directives_template. Director can hand-edit later.
        name = row.get("name") or " ".join(w.capitalize() for w in slug.split("-"))
        out.append({"slug": slug, "name": str(name)[:80], "status": status})
    return out


def provision_batch(
    matters: Iterable[dict],
    *,
    staging_root: Path,
    today: str,
    dry_run: bool,
    force: bool,
) -> tuple[int, int, list[str]]:
    """Provision directives.md for each matter. Returns (created, skipped, errors)."""
    created = 0
    skipped = 0
    errors: list[str] = []
    for m in matters:
        slug = m["slug"]
        name = m["name"]
        out_dir = staging_root / slug
        try:
            if dry_run:
                target = out_dir / "curated" / "directives.md"
                if target.exists():
                    logger.info("[dry-run] %s: would skip (exists)", slug)
                    skipped += 1
                else:
                    logger.info("[dry-run] %s: would create %s", slug, target)
                    created += 1
                continue

            was_created = provision_directive_schema(
                matter_slug=slug,
                matter_name=name,
                out_dir=out_dir,
                today=today,
                force=force,
            )
            if was_created:
                created += 1
            else:
                skipped += 1
        except Exception as e:  # noqa: BLE001 — surfaced as error in batch report
            errors.append(f"{slug}: {e}")
            logger.exception("provisioning failed for %s", slug)
    return created, skipped, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would happen, write nothing.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing directives.md (default: skip).",
    )
    parser.add_argument(
        "--vault-root", type=Path, default=DEFAULT_VAULT_ROOT,
        help="Path to baker-vault checkout (for slugs.yml read).",
    )
    parser.add_argument(
        "--staging-root", type=Path, default=DEFAULT_STAGING_ROOT,
        help="Staging directory under vault_scaffolding/live_mirror/v1/.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    matters = load_active_matters(args.vault_root)
    logger.info("loaded %d non-retired matters from %s", len(matters), args.vault_root)

    today = date.today().isoformat()
    created, skipped, errors = provision_batch(
        matters,
        staging_root=args.staging_root,
        today=today,
        dry_run=args.dry_run,
        force=args.force,
    )
    logger.info("created=%d skipped=%d errors=%d", created, skipped, len(errors))
    if errors:
        for e in errors:
            logger.error("  %s", e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
