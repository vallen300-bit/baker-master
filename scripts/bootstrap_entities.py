"""Entity row append generator (CORTEX_BOOTSTRAP_MATTER_1).

Reads ``briefs/_inputs/bootstrap_entities_<batch>.yml`` and emits a staged
append-batch file under ``vault_scaffolding/live_mirror/v1/`` for the Mac
Mini to merge into ``baker-vault/entities.yml``.

Validates per row:
- slug uniqueness vs current ``entities.yml`` (canonical + alias index)
- intra-batch slug uniqueness
- ``status`` ∈ {active, retired, draft}
- ``description`` ≥ 10 chars

CHANDA #9: NEVER writes ``baker-vault/entities.yml`` directly. Only stages.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT_ROOT = Path.home() / "baker-vault"

KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VALID_STATUS = frozenset({"active", "retired", "draft"})
MIN_DESCRIPTION_LEN = 10


class EntityBootstrapError(ValueError):
    """Raised when input config or registry state fails validation."""


def load_input(path: Path) -> list[dict]:
    """Read + parse the entity-batch YAML."""
    if not path.is_file():
        raise EntityBootstrapError(f"input file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise EntityBootstrapError(f"input YAML parse error: {e}") from e
    if not isinstance(data, dict):
        raise EntityBootstrapError("input YAML must be a mapping at top level")
    rows = data.get("entities")
    if not isinstance(rows, list) or len(rows) < 1:
        raise EntityBootstrapError("input must define a non-empty 'entities' list")
    return rows


def load_current_registry(vault_root: Path) -> tuple[int, set[str]]:
    """Return (current_version, known-slug-set) from entities.yml.

    known-slug-set includes both canonical slugs and aliases (case-folded).
    Raises if entities.yml unreachable.
    """
    ent_yml = vault_root / "entities.yml"
    if not ent_yml.is_file():
        raise EntityBootstrapError(f"entities.yml not found at {ent_yml}")
    try:
        data = yaml.safe_load(ent_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise EntityBootstrapError(f"entities.yml parse error: {e}") from e
    version = data.get("version")
    if not isinstance(version, int):
        raise EntityBootstrapError(
            f"entities.yml must carry an integer 'version'; got {version!r}"
        )
    known: set[str] = set()
    for row in data.get("entities", []) or []:
        if not isinstance(row, dict):
            continue
        slug = row.get("slug")
        if isinstance(slug, str):
            known.add(slug.lower())
        for a in row.get("aliases") or []:
            if isinstance(a, str):
                known.add(a.lower())
    return version, known


def validate_rows(rows: list[dict], known: set[str]) -> list[dict]:
    """Validate each row + intra-batch dedup. Returns the cleaned rows."""
    cleaned: list[dict] = []
    seen_in_batch: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise EntityBootstrapError(
                f"entities[{i}] must be a mapping, got {type(row).__name__}"
            )
        slug = row.get("slug")
        if not isinstance(slug, str) or not KEBAB_SLUG_RE.match(slug):
            raise EntityBootstrapError(
                f"entities[{i}].slug must be lowercase kebab-case, got {slug!r}"
            )
        slug_lc = slug.lower()
        if slug_lc in seen_in_batch:
            raise EntityBootstrapError(
                f"entities[{i}].slug={slug!r} duplicated within this batch"
            )
        if slug_lc in known:
            raise EntityBootstrapError(
                f"entities[{i}].slug={slug!r} already in entities.yml "
                f"(canonical or alias collision)"
            )
        status = row.get("status", "active")
        if status not in VALID_STATUS:
            raise EntityBootstrapError(
                f"entities[{i}].status must be one of {sorted(VALID_STATUS)}, "
                f"got {status!r}"
            )
        desc = row.get("description")
        if not isinstance(desc, str) or len(desc.strip()) < MIN_DESCRIPTION_LEN:
            raise EntityBootstrapError(
                f"entities[{i}].description must be a string ≥{MIN_DESCRIPTION_LEN} chars, "
                f"got {desc!r}"
            )
        aliases = row.get("aliases") or []
        if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
            raise EntityBootstrapError(
                f"entities[{i}].aliases must be a list of strings (or omitted)"
            )
        for a in aliases:
            if a.lower() in known or a.lower() in seen_in_batch:
                raise EntityBootstrapError(
                    f"entities[{i}].aliases[{a!r}] collides with existing slug or alias"
                )
        seen_in_batch.add(slug_lc)
        for a in aliases:
            seen_in_batch.add(a.lower())
        cleaned.append({
            "slug": slug,
            "status": status,
            "description": desc.strip(),
            "aliases": list(aliases),
        })
    return cleaned


def determine_staging_dir(repo_root: Path) -> Path:
    primary = repo_root / "vault_scaffolding" / "live_mirror" / "v1"
    if primary.parent.is_dir():
        return primary
    fallback = repo_root / "outputs" / "matter_bootstrap"
    print(
        f"[INFO] vault_scaffolding/live_mirror/v1/ not found.\n"
        f"       Emitting batch to fallback: {fallback}\n"
        f"       Move manually to baker-vault when ready (CHANDA #9).",
        file=sys.stderr,
    )
    return fallback


def render_batch(
    rows: list[dict], current_version: int, today: str, batch_label: str
) -> str:
    """Render the staged append-batch YAML.

    Bumps version by +1; carries Mac Mini merge instructions in header
    comments. Mac Mini owns the actual entities.yml rewrite.
    """
    header = (
        f"# Append-batch staged by scripts/bootstrap_entities.py\n"
        f"# Batch: {batch_label}\n"
        f"# Generated: {today}\n"
        f"#\n"
        f"# Mac Mini merge instructions (CHANDA #9):\n"
        f"#   1. Confirm baker-vault/entities.yml version == {current_version}\n"
        f"#   2. Append every row in `new_entities` below to the `entities:` list\n"
        f"#   3. Bump entities.yml `version` to {current_version + 1}\n"
        f"#   4. Set `updated_at` to {today}\n"
        f"#\n"
    )
    payload = {
        "version": current_version + 1,
        "updated_at": today,
        "new_entities": rows,
    }
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return header + body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--input", type=Path, required=True,
        help="Path to entity-batch YAML (briefs/_inputs/bootstrap_entities_<batch>.yml).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate input + print intended writes without staging anything.",
    )
    parser.add_argument(
        "--vault-root", type=Path, default=DEFAULT_VAULT_ROOT,
        help=f"Path to baker-vault checkout (default: {DEFAULT_VAULT_ROOT}).",
    )
    parser.add_argument(
        "--out-root", type=Path, default=None,
        help="Override staging dir (defaults to vault_scaffolding/live_mirror/v1/).",
    )
    parser.add_argument(
        "--today", type=str,
        default=datetime.now(timezone.utc).date().isoformat(),
        help="ISO date for batch metadata (default: today UTC).",
    )
    args = parser.parse_args(argv)

    try:
        rows_raw = load_input(args.input)
        version, known = load_current_registry(args.vault_root)
        rows = validate_rows(rows_raw, known)
    except EntityBootstrapError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    out_root = (
        args.out_root if args.out_root is not None
        else determine_staging_dir(REPO_ROOT)
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch_label = args.input.stem
    batch_filename = f"entities.yml.append-batch-{batch_label}-{timestamp}.yml"
    target = out_root / batch_filename

    rendered = render_batch(rows, version, args.today, batch_label)

    if args.dry_run:
        print(f"[DRY-RUN] Would write {target}")
        print(f"[DRY-RUN] Bumps version {version} -> {version + 1}")
        print(f"[DRY-RUN] Adds {len(rows)} new entities: "
              f"{sorted(r['slug'] for r in rows)}")
        return 0

    out_root.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    print(
        f"[OK] Staged {len(rows)} new entities to {target}\n"
        f"     Version bump: {version} -> {version + 1}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
