---
brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1
status: DRAFT — candidate for AI Head 1 sequencing
revision: v1 (author-time draft, simplification preamble §0)
authored_by: AI Head A (CLI)
authored_at: 2026-04-30
estimated_time: ~4-5h (incl. tests + migration dry-run)
complexity: Medium
trigger_class: TIER A — new Postgres tables + per-matter vault file emission via existing CHANDA-#9 staging path. Pre-merge: AI Head B cross-lane review per `_ops/processes/b-code-dispatch-coordination.md` §HIGH-class.
prerequisites: |
  None — Brief 1 (BAKER_VAULT_WRITE_1) NOT a hard prereq. This brief stages
  vault writes via existing `vault_scaffolding/live_mirror/v1/` path that
  Mac Mini already mirrors (CHANDA #9 current form). Brief 1 ships in
  parallel; if Brief 1 lands first, the migration script CAN be re-pointed
  to call `baker_mcp.vault_write` directly — but that's a follow-up, not
  this brief's scope.
sequencing: |
  Per AI Head 1 ratification 2026-04-30 (Q1 flip): Brief 4 ships BEFORE
  Brief 3 (Reflector consumer). This is schema-first discipline.
---

# BRIEF: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 — Per-matter directives schema + migration + bootstrap hook

## §0. Simplification preamble (DROPS + V2 triggers)

Per Director directive 2026-04-30 ("build simple, refine from practice"), this brief deliberately ships V1 minimal. Items dropped from earlier scope discussions, with V2 trigger criteria for re-introduction:

| Dropped from V1 | Reason | V2 trigger criterion |
|---|---|---|
| Cycle-outcome inspector (implicit-pass detection via "Director shipped what proposal recommended") | Heaviest engineering line: requires LLM-comparison call after each TTL, "shipped what" definition, contradicting-proposal detection | Add to V2 if **stale-rate >30% over first calendar month** of Reflector operation |
| ClickUp aux signal as auxiliary counter feed | Adds 4-row conflict matrix + mismatch-log table; only useful if Triaga signal alone is sparse | Add to V2 if **Triaga ratification coverage <50%** of cycles in first calendar month |
| `directive_signal_mismatch` log table | Falls out with ClickUp aux drop — no signal source to mismatch against | Re-introduce when ClickUp aux re-introduced |
| Drift detector for Brief 5 ClickUp surface contract | Already deferred by AI Head 1 ratification (C-followup) to a separate CHANDA candidate | Separate CHANDA item, not this brief |
| Periodic spot-audit (1% sampling) of citations via second-pass LLM | Director-rejected as over-engineering | N/A |

V1 ships with the **smallest surface that observes whether counters work at all**. Production data drives V2 selection.

## §1. Context

**Cortex Stage 2 V1** is in flight (Phase 1 sense → Phase 2 load → Phase 3 reason → Phase 4 propose → Phase 5 act → Phase 6 archive). Phases 1–5 have landed; Phase 6 (Reflector) is the next phase to ship. Reflector's job: observe cycle outcomes, increment helpful/harmful counters on **directives** that the Phase 4 proposal cited via `[directive: <id>]`. This brief ships the schema that Phase 6 Reflector consumes.

**Directives = stable rules, principles, or patterns** surfaced by Phase 6 Reflector after Director ratification. Each directive has an ID, a body (markdown), counters, and a status. Phase 4 proposals cite directives they drew on; Phase 6 Reflector observes the cycle outcome (Director Triaga ratify / decline / 14d silence) and updates counters.

**Architectural alignment:**
- Citation mechanism Director-ratified 2026-04-30 (caveat 2): per-directive citation in propose phase, format `[directive: <id>]`.
- Counter math Director-ratified 2026-04-30 + AI Head 1 confirmed: `score = helpful / (helpful + harmful)`, ignoring stale and pending counts. 14d TTL for silent-timeout → stale++.
- ID format ratified per AI Head 1 default-acceptance: `<matter-slug>-<topic>-<NNN>` for matter-scoped, `_global-<NNN>` for cross-matter directives.

**Live matter count (slugs.yml v15, 2026-04-30):**
- TOTAL: 36
- ACTIVE: 31
- RETIRED: 5
- DRAFT: 0

Per Director "live organism" framing, this brief reads `slugs.yml` at script run-time — the count above is author-time-snapshot only; migration script handles whatever's live on ship date.

**Foundation references:**
- `_ops/ideas/2026-04-27-cortex-architecture-final-locked.md` — RA-23 ratification (Cortex 6-phase architecture)
- `_ops/processes/cortex-stage2-v1-tracker.md` — current phase progress
- `briefs/BRIEF_CORTEX_BOOTSTRAP_MATTER_1.md` — bootstrap_matter.py predecessor (PR #96 merged 2026-04-30)
- `migrations/20260428_cortex_cycles.sql` — `cortex_cycles` table (cycle_id PK)
- `migrations/20260428_cortex_phase_outputs.sql` — phase artifact storage

---

## §2. Problem

### 2.1 Today

Phase 4 proposals are emitted with no traceable provenance — when Director ratifies a proposal, we cannot answer "which prior directive shaped that proposal?" without manual cross-reading. Phase 6 Reflector cannot increment counters on directives that don't exist as schema.

### 2.2 Concrete blockers

| Blocked use case | Why blocked |
|---|---|
| Phase 6 Reflector parses `[directive: movie-aukera-001]` from Phase 4 output | No `cortex_directives` table to look up directive_id |
| Reflector increments helpful/harmful on cited directives | Counters have no storage |
| Per-matter directives.md surface (human-readable Director playbook) | No file emitted by bootstrap; existing 31 matters have no playbook scaffolding |
| Untraceable proposals (no `[directive: …]` citation) flagged for prompt-engineering review | No `prompt_review_queue` table |
| Bootstrap of new matters auto-provisions directive surface | bootstrap_matter.py's SKELETON_FILES list does not include directives.md |

### 2.3 What this brief delivers

**One function reused by two callers** (per AI Head 1 brainstorming-#3 ratification: BOTH surfaces required):
1. **Migration**: `migrations/20260430_cortex_directives.sql` — creates `cortex_directives` + `prompt_review_queue` tables. One-shot schema bootstrap.
2. **Function**: `provision_directive_schema(matter_slug, vault_root, today, *, force=False)` in new module `orchestrator/cortex_directives.py`. Idempotent: ensures `wiki/matters/<slug>/curated/directives.md` exists with frontmatter; skips if present.
3. **Caller A (run-once)**: `scripts/migrate_directives_for_existing_matters.py` reads `slugs.yml` at run-time, filters `status != retired`, calls `provision_directive_schema` for each. Stages via `vault_scaffolding/live_mirror/v1/` per CHANDA #9.
4. **Caller B (bootstrap hook)**: `scripts/bootstrap_matter.py` SKELETON_FILES tuple gets one new entry `("curated/directives.md", "directives")`; new `render_directives()` function. Every new matter auto-provisions directive surface.

---

## §3. Solution

### 3.1 Postgres schema

**`migrations/20260430_cortex_directives.sql`:**

```sql
-- Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1
-- Two tables: cortex_directives (per-directive registry + counters)
--             prompt_review_queue (untraceable Phase 4 outputs)

CREATE TABLE IF NOT EXISTS cortex_directives (
    directive_id     TEXT PRIMARY KEY,
        -- Format: '<matter-slug>-<topic>-<NNN>' (e.g. 'movie-aukera-001')
        --      OR '_global-<NNN>' (cross-matter directives)
    matter_slug      TEXT NOT NULL,
        -- Use '_global' for cross-matter directives.
        -- Otherwise must match a slug in baker-vault/slugs.yml at write-time.
    body             TEXT NOT NULL,
        -- The directive content (markdown). Mirrored to vault directives.md.
    source_cycle     UUID REFERENCES cortex_cycles(cycle_id) ON DELETE SET NULL,
        -- The cycle_id that originally surfaced this directive (Phase 6
        -- Reflector promote step in Brief 3). NULL for migration-seeded
        -- directives or Director-manual entries.
    status           TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'deprecated', 'draft')),
    helpful_count    INTEGER NOT NULL DEFAULT 0,
        -- Director Triaga ratified a proposal that cited this directive
    harmful_count    INTEGER NOT NULL DEFAULT 0,
        -- Director Triaga declined a proposal that cited this directive
    stale_count      INTEGER NOT NULL DEFAULT 0,
        -- 14d silence after proposal cited this directive (no Triaga signal)
    pending_count    INTEGER NOT NULL DEFAULT 0,
        -- Currently in-flight: cited but Triaga TTL not yet expired
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_directives_matter_status
    ON cortex_directives (matter_slug, status);

-- Score-eligible partial index (helpful + harmful > 0): supports
-- "top-N directives" queries cheaply. Stale + pending excluded from score.
CREATE INDEX IF NOT EXISTS idx_cortex_directives_scored
    ON cortex_directives (matter_slug, status)
    WHERE helpful_count + harmful_count > 0;

COMMENT ON TABLE cortex_directives IS
    'Per-matter directives playbook (Cortex Phase 6 Reflector domain). '
    'Citation mechanism: Phase 4 proposals tag [directive: <id>]; '
    'Phase 6 Reflector observes cycle outcome → increments counters. '
    'V1 simplification: Triaga-only signal source. ClickUp aux + cycle-outcome '
    'inspector deferred to V2 per simplification preamble §0.';

CREATE TABLE IF NOT EXISTS prompt_review_queue (
    queue_id         BIGSERIAL PRIMARY KEY,
    cycle_id         UUID NOT NULL REFERENCES cortex_cycles(cycle_id) ON DELETE CASCADE,
    matter_slug      TEXT NOT NULL,
    proposal_text    TEXT NOT NULL,
        -- Phase 4 output that was missing a [directive: <id>] citation
    flagged_reason   TEXT NOT NULL
        CHECK (flagged_reason IN (
            'no_citation',           -- proposal has zero [directive: …] tags
            'unknown_directive_id',  -- citation references id absent from cortex_directives
            'malformed_citation'     -- regex match but invalid id format
        )),
    reviewed         BOOLEAN NOT NULL DEFAULT FALSE,
        -- Director or AI Head A reviewed → toggles true after eyeball pass
    review_notes     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_prompt_review_queue_unreviewed
    ON prompt_review_queue (created_at DESC)
    WHERE reviewed = FALSE;

COMMENT ON TABLE prompt_review_queue IS
    'Untraceable Phase 4 outputs (no/unknown/malformed [directive: <id>] citation). '
    'Weekly eyeball-review surface. Phase 6 Reflector inserts; Director or '
    'AI Head A flips reviewed=true after pass. Per Director caveat 2 ratification '
    '2026-04-30: untraceable proposals flag for prompt-engineering review.';
```

**Migration policy:**
- Idempotent (`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).
- Foreign key to `cortex_cycles(cycle_id)` requires that table to exist (it already does — migration `20260428_cortex_cycles.sql` already applied).
- No data backfill in the SQL migration itself — vault provisioning + counter seeding handled by Python migration script (caller A).
- Rollback documented at file end (commented `-- DROP TABLE` lines, like prior cortex migrations).

### 3.2 Provisioning function

**New module `orchestrator/cortex_directives.py`:**

```python
"""Per-matter directives playbook provisioning (Cortex Phase 6 schema).

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.
Idempotent provisioning of wiki/matters/<slug>/curated/directives.md per
matter. Used by:
  * scripts/bootstrap_matter.py — new matter creation hook
  * scripts/migrate_directives_for_existing_matters.py — run-once for
    existing 31 matters (live count at run-time)

CHANDA #9 (current form): writes stage to vault_scaffolding/live_mirror/v1/.
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
    discipline from BAKER_VAULT_WRITE_1 §3.4 — source/confidence/provenance
    are NOT required on this scaffolding file because no directive bodies
    exist yet; the file becomes a container that Phase 6 Reflector populates,
    and Reflector's writes will carry the standard frontmatter).
    """
    return f"""---
matter: {matter_slug}
matter_name: {matter_name}
type: directives_playbook
created_at: {today}
last_updated: {today}
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
    """Idempotent provisioning of <matter>/curated/directives.md.

    Args:
        matter_slug: kebab-case slug (e.g. 'mo-vie-am')
        matter_name: human-readable display name
        out_dir: target directory — typically vault_scaffolding staging path
                 (e.g., repo_root/vault_scaffolding/live_mirror/v1/matters/<slug>/)
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
```

### 3.3 Run-once migration script

**New file `scripts/migrate_directives_for_existing_matters.py`:**

```python
"""Run-once: provision directives.md for all active+development matters.

Brief: CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 (caller A).

Reads baker-vault/slugs.yml at run-time (live state, not snapshot). Filters
status != retired. Calls orchestrator.cortex_directives.provision_directive_schema
for each. Stages writes to vault_scaffolding/live_mirror/v1/ per CHANDA #9.

Idempotent: re-runs skip matters whose directives.md already exists.
Re-runnable safely after slugs.yml additions (live-organism friendly).

Usage:
    python scripts/migrate_directives_for_existing_matters.py [--dry-run] \\
                                                              [--force] \\
                                                              [--vault-root <path>]

Exit codes:
    0 — all targeted matters provisioned (or skipped as no-op)
    1 — input validation error (slugs.yml malformed, vault unreachable)
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
    """Read slugs.yml and return list of {slug, name, status} for non-retired matters.

    Filters: status != retired (per AI Head 1 Q3 ratification 2026-04-30).
    Includes both 'active' and 'development' streams.
    """
    slugs_yml = vault_root / "slugs.yml"
    if not slugs_yml.is_file():
        raise SystemExit(f"slugs.yml not found at {slugs_yml}")

    try:
        data = yaml.safe_load(slugs_yml.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise SystemExit(f"slugs.yml parse error: {e}") from e

    matters = data.get("matters") or []
    out = []
    for row in matters:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug")
        status = row.get("status")
        if not slug or not isinstance(slug, str):
            continue
        if status == "retired":
            continue
        # Use description as fallback display name; slug as final fallback.
        name = row.get("name") or row.get("description") or slug
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
        except Exception as e:
            errors.append(f"{slug}: {e}")
            logger.exception("provisioning failed for %s", slug)
    return created, skipped, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would happen, write nothing.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing directives.md (default: skip).")
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT,
                        help="Path to baker-vault checkout (for slugs.yml read).")
    parser.add_argument("--staging-root", type=Path, default=DEFAULT_STAGING_ROOT,
                        help="Staging directory under vault_scaffolding/live_mirror/v1/.")
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
```

### 3.4 Bootstrap hook

**Edit `scripts/bootstrap_matter.py`** — two surgical changes:

1. **Extend `SKELETON_FILES` tuple** (currently line 483-491):

```python
SKELETON_FILES = (
    ("cortex-config.md", "cortex-config"),
    ("_overview.md", "overview"),
    ("_index.md", "index"),
    ("agenda.md", "agenda"),
    ("state.md", "state"),
    ("gold.md", "gold"),
    ("proposed-gold.md", "proposed-gold"),
    ("curated/directives.md", "directives"),  # NEW — Brief CORTEX_CONFIG_DIRECTIVES_SCHEMA_1
)
```

2. **Add `render_directives` dispatcher case** in `render_skeleton()` (currently line 508-525):

```python
def render_skeleton(filename: str, kind: str, cfg: dict, today: str) -> str:
    matter_slug = cfg["matter_slug"]
    matter_name = cfg["matter_name"]
    if kind == "cortex-config":
        return render_cortex_config(cfg, today)
    if kind == "overview":
        return render_overview(matter_slug, matter_name, today)
    if kind == "index":
        return render_index(matter_slug, matter_name, today)
    if kind == "agenda":
        return render_agenda(matter_slug, matter_name, today)
    if kind == "state":
        return render_state(matter_slug, matter_name, today)
    if kind == "gold":
        return render_gold(matter_slug, matter_name, today)
    if kind == "proposed-gold":
        return render_proposed_gold(matter_slug, matter_name, today)
    if kind == "directives":  # NEW — Brief CORTEX_CONFIG_DIRECTIVES_SCHEMA_1
        from orchestrator.cortex_directives import render_directives_template
        return render_directives_template(matter_slug, matter_name, today)
    raise ValueError(f"unknown skeleton kind: {kind}")
```

**Note on the `_extract_frontmatter` validator** (currently line 528-534): the directives.md template starts with `---\n` and terminates frontmatter correctly, so the existing validator passes. The frontmatter keys (`matter`, `matter_name`, `type`, `created_at`, `last_updated`, `directive_count`, `schema_version`) do not need to match `kbl/ingest_endpoint.validate_frontmatter()` strict-mode rules because directives.md is not a curated-claim file — it's a playbook container. Verify by:

```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from kbl.ingest_endpoint import validate_frontmatter
fm = {'matter':'test','matter_name':'Test','type':'directives_playbook',
      'created_at':'2026-04-30','last_updated':'2026-04-30',
      'directive_count':0,'schema_version':1}
validate_frontmatter(fm)
print('OK')
"
```

**Confirmed mismatch** (verified 2026-04-30 against `kbl/ingest_endpoint.py:30-33`):
- `REQUIRED_FRONTMATTER_KEYS = ("type", "slug", "name", "updated", "author", "tags", "related")`
- `VALID_TYPES = frozenset({"matter", "person", "entity"})`

The directives.md frontmatter drafted above (matter / matter_name / type=`directives_playbook` / created_at / last_updated / directive_count / schema_version) will fail validation on **two grounds**: (a) missing 6 of 7 required keys, (b) `directives_playbook` is not in VALID_TYPES.

**Recommended path — Option A** (narrow skip in `write_targets`): gate the `validate_frontmatter` call on kind. One-line change in `scripts/bootstrap_matter.py:568-572`:

```python
for filename, kind in SKELETON_FILES:
    content = render_skeleton(filename, kind, cfg, today)
    fm = _extract_frontmatter(content)
    if kind != "directives":  # NEW — directives.md is a playbook container, not a KBL claim file
        validate_frontmatter(fm)
    (out_root / filename).write_text(content, encoding="utf-8")
    written += 1
```

**Why Option A over Option B** (extending KBL validator to allow `directives_playbook` type): Option B ripples through all KBL ingest paths and breaks the type-enum invariant downstream consumers rely on. Option A is 1 line, isolated to bootstrap, and matches the current architecture (directives.md is NOT a KBL claim — it's a playbook container that Phase 6 Reflector populates with separate frontmatter on each directive write).

### 3.5 What this brief does NOT touch

- `baker_vault/slugs.yml` — read-only here; never written. Separate-repo PR for any slug change.
- `cortex_phase_outputs` — Brief 3 (Reflector) consumer, not Brief 4.
- Cortex runner (`orchestrator/cortex_runner.py`) — Brief 4 ships schema only; runner integration is Brief 3's scope.
- Any directive seeding (initial directives) — V1 ships with empty playbooks. Director + AI Head A may seed manually post-deploy if desired (not migration script's job).
- `_session-state.md` overwrite tier (Brief 1 surface) — directives.md is append-only-by-Reflector, not session state.
- Render env vars — no new env required.
- Drift detector for Brief 5 ClickUp surface — explicit V2 (per simplification preamble §0).

---

## §4. Implementation order

1. **Apply migration SQL** — `migrations/20260430_cortex_directives.sql` to dev / Render-attached Postgres. Verify `cortex_directives` + `prompt_review_queue` tables created with correct columns + indexes.
2. **Implement `orchestrator/cortex_directives.py`** — `render_directives_template` + `provision_directive_schema`.
3. **Add hook to `bootstrap_matter.py`** — extend SKELETON_FILES + render_skeleton dispatch.
4. **Implement `scripts/migrate_directives_for_existing_matters.py`** — run-once migration.
5. **Tests** (see §5).
6. **Dry-run** the migration script: `python scripts/migrate_directives_for_existing_matters.py --dry-run` — confirm 31 matters listed (or whatever's live), zero existing.
7. **Commit + PR** — flag in PR body that this is a TIER A change (new tables) and request AI Head B cross-lane review.

---

## §5. Verification

### 5.1 Schema unit tests — `tests/test_cortex_directives_schema.py`

Use existing pytest live-PG harness (auto-skips without `TEST_DATABASE_URL`):

```python
def test_cortex_directives_table_created(live_db):
    """Verify migration applied and table exists with expected columns."""
    cur = live_db.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'cortex_directives'
        ORDER BY ordinal_position
    """)
    cols = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
    assert "directive_id" in cols and cols["directive_id"][0] == "text"
    assert "matter_slug" in cols and cols["matter_slug"][0] == "text"
    assert "helpful_count" in cols and cols["helpful_count"][0] == "integer"
    assert "harmful_count" in cols
    assert "stale_count" in cols
    assert "pending_count" in cols
    assert "status" in cols
    # ... etc
```

Required test cases (≥ 8):
1. `cortex_directives` table exists with all expected columns + types.
2. Indexes `idx_cortex_directives_matter_status` + `idx_cortex_directives_scored` exist.
3. Insert + select round-trip: directive with all fields populated.
4. Counter increment: UPDATE helpful_count → SELECT confirms +1.
5. Status CHECK constraint rejects invalid status (e.g., 'foo').
6. ON DELETE SET NULL: delete a `cortex_cycles` row → directive's `source_cycle` becomes NULL (not orphan).
7. `prompt_review_queue` table exists with all columns.
8. CHECK constraint on `prompt_review_queue.flagged_reason` rejects unknown values.

### 5.2 Provisioning function tests — `tests/test_cortex_directives_provision.py`

```python
def test_provision_creates_file(tmp_path):
    out_dir = tmp_path / "matters" / "test-matter"
    created = provision_directive_schema("test-matter", "Test Matter", out_dir, "2026-04-30")
    assert created is True
    target = out_dir / "curated" / "directives.md"
    assert target.is_file()
    content = target.read_text()
    assert content.startswith("---\n")
    assert "matter: test-matter" in content
    assert "directive_count: 0" in content


def test_provision_idempotent_skip(tmp_path):
    out_dir = tmp_path / "matters" / "test-matter"
    out_dir.joinpath("curated").mkdir(parents=True)
    out_dir.joinpath("curated", "directives.md").write_text("PRE-EXISTING\n")
    created = provision_directive_schema("test-matter", "Test Matter", out_dir, "2026-04-30")
    assert created is False
    assert (out_dir / "curated" / "directives.md").read_text() == "PRE-EXISTING\n"


def test_provision_force_overwrites(tmp_path):
    out_dir = tmp_path / "matters" / "test-matter"
    out_dir.joinpath("curated").mkdir(parents=True)
    out_dir.joinpath("curated", "directives.md").write_text("PRE-EXISTING\n")
    created = provision_directive_schema(
        "test-matter", "Test Matter", out_dir, "2026-04-30", force=True
    )
    assert created is True
    content = (out_dir / "curated" / "directives.md").read_text()
    assert "PRE-EXISTING" not in content
    assert "matter: test-matter" in content


def test_provision_validation_rejects_empty_slug(tmp_path):
    with pytest.raises(ValueError, match="matter_slug"):
        provision_directive_schema("", "Name", tmp_path, "2026-04-30")
```

Required: ≥ 4 happy + ≥ 2 rejection paths.

### 5.3 Migration script tests — `tests/test_migrate_directives.py`

Mock `slugs.yml` content + verify batch behavior:

```python
def test_migrate_filters_retired(tmp_path, monkeypatch):
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "slugs.yml").write_text("""
matters:
  - {slug: active-one, status: active, description: "A1"}
  - {slug: retired-one, status: retired, description: "R1"}
  - {slug: dev-one, status: active, description: "D1"}
""")
    matters = load_active_matters(vault_root)
    slugs = {m["slug"] for m in matters}
    assert "active-one" in slugs
    assert "dev-one" in slugs
    assert "retired-one" not in slugs


def test_migrate_dry_run_writes_nothing(tmp_path):
    # ... build minimal slugs.yml + invoke main(["--dry-run", ...])
    # Assert no files created under staging_root
```

Required: ≥ 3 cases (filter, dry-run, error path).

### 5.4 Bootstrap integration

After implementation, run a wet bootstrap on a throwaway slug:

```bash
# Build a minimal input YAML for a sandbox slug
cat > /tmp/bootstrap_test.yml <<EOF
matter_slug: bootstrap-test
matter_name: Bootstrap Test
absorbed_from: NONE
absorbed_by: NONE
authority_chain: ["AI Head A"]
ratified_at: "2026-04-30"
entities:
  primary: ["bootstrap-test"]
  counterparties: ["test-counterparty"]
trigger_patterns:
  - "test"
EOF
python scripts/bootstrap_matter.py --input /tmp/bootstrap_test.yml --dry-run
# Verify output mentions curated/directives.md
python scripts/bootstrap_matter.py --input /tmp/bootstrap_test.yml
# Verify file exists under vault_scaffolding/live_mirror/v1/matters/bootstrap-test/
ls vault_scaffolding/live_mirror/v1/matters/bootstrap-test/curated/directives.md
# Cleanup
rm -rf vault_scaffolding/live_mirror/v1/matters/bootstrap-test/
```

### 5.5 Live migration dry-run

Before any wet write:

```bash
python scripts/migrate_directives_for_existing_matters.py --dry-run \
    --vault-root ~/baker-vault
```

Expected output: `created=N skipped=0 errors=0` where N = current active+development count (31 at author time).

Then wet:

```bash
python scripts/migrate_directives_for_existing_matters.py \
    --vault-root ~/baker-vault
```

After this completes, `vault_scaffolding/live_mirror/v1/matters/<slug>/curated/directives.md` exists for each non-retired matter. Mac Mini's vault mirror picks up on next sync (~5 min) and commits to baker-vault.

### 5.6 Re-runnability check

Re-run migration: should produce `created=0 skipped=N errors=0`. Idempotency confirmed.

### 5.7 New-matter check post-bootstrap-hook

After bootstrap_matter.py change is merged, the NEXT new matter (Wave 4 fixture or Director-driven addition) automatically gets `curated/directives.md` — verify by running the existing `bootstrap_aukera.yml` flow on a sandbox slug.

---

## §6. Acceptance criteria

| # | Criterion | How to verify |
|---|---|---|
| AC1 | Migration `20260430_cortex_directives.sql` applied to live Postgres without error | `\d cortex_directives` and `\d prompt_review_queue` show expected columns |
| AC2 | `orchestrator/cortex_directives.py` module imports clean, `provision_directive_schema` callable | `python3 -c "from orchestrator.cortex_directives import provision_directive_schema; print('OK')"` |
| AC3 | `bootstrap_matter.py` SKELETON_FILES extended; new matters auto-emit directives.md | wet-run on sandbox slug shows `curated/directives.md` in output dir |
| AC4 | Run-once migration script provisions all non-retired matters | `python scripts/migrate_directives_for_existing_matters.py --dry-run` reports correct count; wet run produces files for each |
| AC5 | Idempotent: re-running migration script reports `created=0 skipped=N` | second invocation log |
| AC6 | All ≥ 14 tests pass (8 schema + 4 provision + 3+ migration) | `pytest tests/test_cortex_directives_*.py tests/test_migrate_directives.py -v` |
| AC7 | `bash scripts/check_singletons.sh` still passes | CI guard unchanged |
| AC8 | `python scripts/validate_eval_labels.py` still passes (no slug-registry change) | local validator |
| AC9 | No mention of cycle-outcome inspector, ClickUp aux signal, or mismatch-log table in shipped code | grep audit |

---

## §7. Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| `kbl/ingest_endpoint.validate_frontmatter` rejects directives.md frontmatter (no source/confidence/provenance keys) | Medium | §3.4 explicit: brief implementer extends validator OR skips validation for `type: directives_playbook` files. Flag in PR. |
| 31 matters at run-time but slugs.yml format changes between author-time (v15) and ship-date | Low | Migration script reads at run-time; `load_active_matters` is permissive (skips malformed rows) |
| Mac Mini vault mirror picks up directives.md but Director hasn't ratified the schema for production | Low | This is staging-only; mirror push to baker-vault HEAD remains controlled by Mac Mini sync — no Render→vault direct write |
| Foreign key to `cortex_cycles(cycle_id)` — what if a cycle is deleted? | Low | `ON DELETE SET NULL` keeps directive intact; `source_cycle` becomes NULL (still queryable) |
| Phase 6 Reflector (Brief 3) ships late and `cortex_directives` table sits empty for weeks | Low | Empty schema costs ~0; rollback documented; no behavior depends on directive presence |
| Two callers (bootstrap + migration) drift in template content | Low | Both call `render_directives_template` from one module — single source of truth |

---

## §8. Out of scope (defer to later briefs)

| Item | Where |
|---|---|
| Phase 6 Reflector implementation (citation parsing, counter increment, two-pronged write) | **Brief 3 — CORTEX_PHASE6_REFLECTOR_1** (Q1 ratification: ships AFTER this brief) |
| Cycle-outcome inspector (implicit-pass detection) | V2 if stale-rate > 30% |
| ClickUp aux signal for counters | V2 if Triaga coverage < 50% |
| `directive_signal_mismatch` log table | V2 alongside ClickUp aux re-introduction |
| Drift detector for Brief 5 ClickUp surface contract | Separate CHANDA candidate (deferred by AI Head 1) |
| Periodic spot-audit of citations (1% sampling, second-pass LLM) | Director-rejected as over-engineering — N/A |
| Director-manual directive seeding tool | Optional, post-deploy if desired |
| Per-matter directives.md → `cortex_directives` body sync | V2 (currently Postgres = counter authority, vault = body authority; sync is unidirectional via Reflector writes) |

---

## §9. PR notes

**Suggested PR title:** `feat(cortex): per-matter directives schema + bootstrap hook (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1)`

**Suggested PR body section to include:**

> **Trigger class: TIER A** — new external schema (Postgres tables) + new vault file class.
> Per `_ops/processes/b-code-dispatch-coordination.md` §HIGH-class, requires AI Head B cross-lane review pre-merge.
>
> **Simplification preamble** ([§0 in brief](briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md#0-simplification-preamble-drops--v2-triggers)) — V1 ships Triaga-only signal source. Cycle-outcome inspector + ClickUp aux signal explicitly deferred to V2 with documented trigger criteria (stale-rate > 30%, Triaga coverage < 50%). Per Director directive 2026-04-30 "build simple, refine from practice."
>
> **Live count at author time:** 31 active matters per slugs.yml v15. Migration script reads live at run-time (Director "live organism" framing).
>
> **Sequencing:** ships BEFORE Brief 3 (Phase 6 Reflector) per AI Head 1 Q1 flip ratification 2026-04-30.

**Branch suggestion:** `feature/cortex-directives-schema-1`

---

## §10. Authoring provenance

- Author: AI Head A (CLI)
- Authored: 2026-04-30
- Review status: V1 draft, no review pass yet (will request 3-pass once paired with Brief 3)
- Director ratifications folded:
  - 2026-04-30 caveat 2 (per-directive citation)
  - 2026-04-30 caveat 3 (22-matter scope, superseded by live-organism v15: 31 active)
  - 2026-04-30 simplification directive ("build simple, refine from practice")
- AI Head 1 ratifications folded:
  - Q1 (Brief 4 ships before Brief 3)
  - Q2 (counter math, 14d TTL)
  - Q3 (slugs.yml at run-time, status != retired)
  - #3 (BOTH surfaces required: run-once migration + bootstrap hook)
- Pen-lift: granted by AI Head 1 2026-04-30, deviation-flag-in-preamble path
