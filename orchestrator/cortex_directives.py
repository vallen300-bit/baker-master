"""Per-matter directives playbook provisioning (Cortex Phase 6 schema).

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.

Idempotent provisioning of ``wiki/matters/<slug>/curated/directives.md`` per
matter. Used by:
  * ``scripts/bootstrap_matter.py`` — new-matter creation hook
  * ``scripts/migrate_directives_for_existing_matters.py`` — run-once for
    existing non-retired matters (live count at run-time)

CHANDA #9 (current form): writes stage to ``vault_scaffolding/live_mirror/v1/``.
Mac Mini's vault mirror picks up new files on next sync (~5 min).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DIRECTIVES_FILENAME = "curated/directives.md"


def render_directives_template(matter_slug: str, matter_name: str, today: str) -> str:
    """Render the empty-state directives.md template with frontmatter.

    Frontmatter intentionally minimal (matches Cortex curated/ frontmatter
    discipline). Frontmatter conforms to ``kbl/ingest_endpoint.py`` validator
    (REQUIRED_KEYS=type/slug/name/updated/author/tags/related,
    VALID_TYPES={matter,person,entity}, VALID_VOICES={silver,gold}).
    type='matter' because this file IS the matter's directives playbook —
    no validator skip, no validator extension. directive_count and
    schema_version are documentation-only fields below the required block.
    """
    return f"""---
type: matter
slug: {matter_slug}
name: {matter_name} — Directives Playbook
updated: {today}
author: agent
tags: [directives, playbook, cortex-phase6]
related: []
voice: silver
directive_count: 0
schema_version: 1
---
# {matter_name} — Directives Playbook

This file accumulates **directives** discovered through Cortex cycles for matter
`{matter_slug}`. Each directive is a stable rule, principle, or pattern surfaced
by Phase 6 Reflector after Director ratification.

## How directives work

1. Phase 4 proposals cite directives they drew on: `[directive: <id>]`
2. Phase 6 Reflector observes cycle outcome (Director Triaga ratify / decline / 14d silence)
3. Counters update in Postgres `cortex_directives` table:
   - Triaga ratify → `helpful_count++`
   - Triaga decline → `harmful_count++`
   - 14d silence → `stale_count++`
4. Score = `helpful / (helpful + harmful)`, ignoring stale and pending

## ID format

- Matter-scoped: `{matter_slug}-<topic>-<NNN>` (e.g., `{matter_slug}-001`, `{matter_slug}-strategy-002`)
- Cross-matter generics: `_global-<NNN>`

## Directives

_(none yet — populated as Phase 6 Reflector ratifies cycles)_
"""


def provision_directive_schema(
    matter_slug: str,
    matter_name: str,
    out_dir: Path,
    today: Optional[str] = None,
    *,
    force: bool = False,
) -> bool:
    """Idempotent provisioning of ``<matter>/curated/directives.md``.

    Args:
        matter_slug: kebab-case slug (e.g. ``mo-vie-am``)
        matter_name: human-readable display name
        out_dir: target directory — typically vault_scaffolding staging path
                 (e.g., ``repo_root/vault_scaffolding/live_mirror/v1/matters/<slug>/``)
        today: ISO date string (default: today). Plumbed for test reproducibility.
        force: if True, overwrite existing directives.md. Default False = no-op
               if file exists (the idempotent path).

    Returns:
        True if file was created (or overwritten with force=True).
        False if file already existed and force=False.

    Raises:
        ValueError: if matter_slug or matter_name fails basic validation.
        OSError: if directory creation or file write fails (caller decides).
    """
    if not matter_slug or not isinstance(matter_slug, str):
        raise ValueError(f"matter_slug must be non-empty string, got {matter_slug!r}")
    if not matter_name or not isinstance(matter_name, str):
        raise ValueError(f"matter_name must be non-empty string, got {matter_name!r}")

    target = out_dir / DIRECTIVES_FILENAME
    if target.exists() and not force:
        logger.info(
            "directives.md exists at %s — idempotent skip (use force=True to overwrite)",
            target,
        )
        return False

    today_str = today or date.today().isoformat()
    content = render_directives_template(matter_slug, matter_name, today_str)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    logger.info("provisioned directives.md at %s", target)
    return True
