"""Generic matter scaffolding generator (CORTEX_BOOTSTRAP_MATTER_1).

Generalizes ``scripts/bootstrap_hagenauer_wiki.py`` to any matter slug.
Reads an input YAML at ``briefs/_inputs/bootstrap_<slug>.yml`` and emits
the full ``wiki/matters/<slug>/`` skeleton (7 .md files + ``curated/``)
under the staging path ``vault_scaffolding/live_mirror/v1/matters/<slug>/``.

Reference template: ``wiki/matters/mrci/cortex-config.md`` (Wave 2 canonical).

CHANDA #9: Baker NEVER writes ``baker-vault/`` directly. The Mac Mini
mirrors the staged scaffolding. Verify with::

    python scripts/bootstrap_matter.py --dry-run --input <input.yml>
    python scripts/bootstrap_matter.py --input <input.yml>
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_VAULT_ROOT = Path.home() / "baker-vault"
NEEDS_CONTENT_MARKER = "[NEEDS_DIRECTOR_CONTENT]"

KEBAB_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

VALID_AUTONOMY = frozenset({"auto_execute", "recommend_wait", "escalate"})
VALID_HORIZONS = frozenset({"one_shot", "short_finite", "long_finite", "infinite_repeated"})

REQUIRED_INPUT_FIELDS = (
    "matter_slug", "matter_name", "absorbed_from", "absorbed_by",
    "authority_chain", "ratified_at",
)

INPUT_DEFAULTS = {
    "autonomy_level": "recommend_wait",
    "sense_sources": [{"email": "matter_keywords"}, {"whatsapp": "contact_phones"}],
    "default_specialists": ["legal", "finance", "game-theory"],
    "specialist_cap_per_cycle": 5,
    "specialist_timeout_seconds": 60,
    "specialist_retries": 2,
    "cycle_timeout_seconds": 300,
    "auto_trigger": {"severity_floor": "high", "confidence_floor": 0.8},
    "games_relevant": True,
    "counterparty_iteration_horizon": "infinite_repeated",
    "counterparty_reputation_stake": 8,
    "counterparty_observed_strategy": "generous_tft",
}


class BootstrapError(ValueError):
    """Raised when input config or vault state fails validation."""


def load_input(path: Path) -> dict:
    """Read + parse the per-matter input YAML."""
    if not path.is_file():
        raise BootstrapError(f"input file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise BootstrapError(f"input YAML parse error: {e}") from e
    if not isinstance(data, dict):
        raise BootstrapError("input YAML must be a mapping at top level")
    return data


def apply_defaults(cfg: dict) -> dict:
    """Merge defaults onto the input config (input wins on collision)."""
    out = dict(INPUT_DEFAULTS)
    out.update(cfg)
    if "auto_trigger" in cfg and isinstance(cfg["auto_trigger"], dict):
        merged = dict(INPUT_DEFAULTS["auto_trigger"])
        merged.update(cfg["auto_trigger"])
        out["auto_trigger"] = merged
    return out


def validate_input(cfg: dict, *, vault_root: Path | None) -> None:
    """Validate the merged input config. Raises BootstrapError on any miss."""
    missing = [k for k in REQUIRED_INPUT_FIELDS if k not in cfg or cfg[k] in (None, "")]
    if missing:
        raise BootstrapError(f"input missing required fields: {missing}")

    slug = cfg["matter_slug"]
    if not isinstance(slug, str) or not KEBAB_SLUG_RE.match(slug):
        raise BootstrapError(f"matter_slug must be lowercase kebab-case, got {slug!r}")

    if not isinstance(cfg["matter_name"], str) or not cfg["matter_name"].strip():
        raise BootstrapError("matter_name must be a non-empty string")

    ratified = str(cfg["ratified_at"])
    if not ISO_DATE_RE.match(ratified):
        raise BootstrapError(f"ratified_at must be YYYY-MM-DD, got {ratified!r}")

    autonomy = cfg.get("autonomy_level")
    if autonomy not in VALID_AUTONOMY:
        raise BootstrapError(
            f"autonomy_level must be one of {sorted(VALID_AUTONOMY)}, got {autonomy!r}"
        )

    horizon = cfg.get("counterparty_iteration_horizon")
    if horizon not in VALID_HORIZONS:
        raise BootstrapError(
            f"counterparty_iteration_horizon must be one of {sorted(VALID_HORIZONS)}, "
            f"got {horizon!r}"
        )

    entities = cfg.get("entities")
    if not isinstance(entities, dict):
        raise BootstrapError("entities must be a mapping with 'primary' + 'counterparties' keys")
    primary = entities.get("primary") or []
    counterparties = entities.get("counterparties") or []
    if not isinstance(primary, list) or len(primary) < 1:
        raise BootstrapError("entities.primary must be a non-empty list")
    if not isinstance(counterparties, list) or len(counterparties) < 1:
        raise BootstrapError("entities.counterparties must be a non-empty list")
    for bucket in ("primary", "team", "counterparties", "adjacent"):
        for s in entities.get(bucket) or []:
            if not isinstance(s, str) or not KEBAB_SLUG_RE.match(s):
                raise BootstrapError(
                    f"entities.{bucket} contains invalid slug {s!r} (must be kebab-case)"
                )

    patterns = cfg.get("trigger_patterns") or []
    if not isinstance(patterns, list) or len(patterns) < 1:
        raise BootstrapError("trigger_patterns must be a non-empty list of regex strings")
    for p in patterns:
        if not isinstance(p, str):
            raise BootstrapError(f"trigger_patterns entries must be strings, got {type(p).__name__}")
        try:
            re.compile(p)
        except re.error as e:
            raise BootstrapError(f"trigger_patterns regex {p!r} invalid: {e}") from e

    # Vault collision check (only when vault is reachable).
    if vault_root and vault_root.is_dir():
        existing = vault_root / "wiki" / "matters" / slug
        if existing.is_dir():
            raise BootstrapError(
                f"matter dir already exists in vault: {existing} — refuse to clobber"
            )


def _load_known_slugs(vault_root: Path) -> set[str]:
    """Union of canonical slugs + aliases across slugs.yml, people.yml, entities.yml.

    The matter cortex-config ``entities:`` block is a misnomer — buckets
    (primary/team/counterparties/adjacent) carry slugs from all 3 registries
    (e.g. ``team`` holds person slugs, ``adjacent`` holds matter slugs).
    """
    known: set[str] = set()
    for fname, key in (
        ("slugs.yml", "matters"),
        ("people.yml", "people"),
        ("entities.yml", "entities"),
    ):
        path = vault_root / fname
        if not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for row in data.get(key, []) or []:
            if isinstance(row, dict) and isinstance(row.get("slug"), str):
                known.add(row["slug"])
                for a in row.get("aliases") or []:
                    if isinstance(a, str):
                        known.add(a)
    return known


def check_entity_slugs_exist(cfg: dict, vault_root: Path | None) -> list[str]:
    """Return list of slugs referenced in cfg that are NOT in any registry.

    Soft-flag: caller decides whether to abort. Returns [] if vault unreachable.
    """
    if not vault_root or not vault_root.is_dir():
        return []
    known = _load_known_slugs(vault_root)
    if not known:
        return []
    referenced: list[str] = []
    entities = cfg.get("entities") or {}
    for bucket in ("primary", "team", "counterparties", "adjacent"):
        for s in entities.get(bucket) or []:
            referenced.append(s)
    return [s for s in referenced if s not in known]


def check_slug_in_registry(slug: str, vault_root: Path | None) -> bool | None:
    """Return True/False if slugs.yml is reachable, else None."""
    if not vault_root or not vault_root.is_dir():
        return None
    slugs_yml = vault_root / "slugs.yml"
    if not slugs_yml.is_file():
        return None
    try:
        data = yaml.safe_load(slugs_yml.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    for row in data.get("matters", []) or []:
        if isinstance(row, dict) and row.get("slug") == slug:
            return True
    return False


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _vault_frontmatter(
    matter_slug: str,
    matter_name: str,
    today: str,
    *,
    sub_slug: str | None,
    sub_name: str,
    voice: str | None = None,
) -> dict:
    """Build VAULT.md §2-compliant frontmatter for a sub-page."""
    fm = {
        "type": "matter",
        "slug": sub_slug if sub_slug else matter_slug,
        "name": sub_name,
        "updated": today,
        "author": "agent",
        "tags": [matter_slug],
        "related": [],
    }
    if voice:
        fm["voice"] = voice
    return fm


def render_cortex_config(cfg: dict, today: str) -> str:
    """Render cortex-config.md combining VAULT §2 + Cortex schema fields.

    Lead block has the 7 mandatory VAULT fields so ``validate_frontmatter``
    passes. Trailing block carries the Cortex-specific keys consumed by
    ``triggers/cortex_pre_review_gate`` (matter_slug, autonomy_level, etc.).
    Both share one ``---``-delimited frontmatter region.
    """
    matter_slug = cfg["matter_slug"]
    matter_name = cfg["matter_name"]

    vault_fm = _vault_frontmatter(
        matter_slug, matter_name, today,
        sub_slug=matter_slug,
        sub_name=f"Cortex Per-Matter Brain — {matter_name}",
    )

    cortex_fm = {
        "matter_slug": matter_slug,
        "matter_name": matter_name,
        "absorbed_from": cfg["absorbed_from"],
        "absorbed_at": today,
        "absorbed_by": cfg["absorbed_by"],
        "authority_chain": cfg["authority_chain"],
        "ratified_at": str(cfg["ratified_at"]),
        "autonomy_level": cfg["autonomy_level"],
        "sense_sources": cfg["sense_sources"],
        "entities": cfg["entities"],
        "trigger_patterns": cfg["trigger_patterns"],
        "default_specialists": cfg["default_specialists"],
        "specialist_cap_per_cycle": cfg["specialist_cap_per_cycle"],
        "specialist_timeout_seconds": cfg["specialist_timeout_seconds"],
        "specialist_retries": cfg["specialist_retries"],
        "cycle_timeout_seconds": cfg["cycle_timeout_seconds"],
        "auto_trigger": cfg["auto_trigger"],
        "games_relevant": cfg["games_relevant"],
        "counterparty_iteration_horizon": cfg["counterparty_iteration_horizon"],
        "counterparty_reputation_stake": cfg["counterparty_reputation_stake"],
        "counterparty_observed_strategy": cfg["counterparty_observed_strategy"],
        "state_file": "state.md",
        "gold_file": "proposed-gold.md",
        "curated_dir": "curated/",
    }

    fm_combined = {**vault_fm, **cortex_fm}
    fm_text = yaml.safe_dump(fm_combined, sort_keys=False, allow_unicode=True).rstrip("\n")

    body_lines = [
        "---",
        fm_text,
        "---",
        "",
        f"# Cortex Per-Matter Brain — {matter_name}",
        "",
        f"Per-matter Cortex config for the {matter_name} workstream. "
        f"Cortex Phase 2 loads this file when a signal carries "
        f"`matter_slug='{matter_slug}'`.",
        "",
        "## Project ↔ Owner GmbH structure",
        "",
        cfg.get("project_structure") or NEEDS_CONTENT_MARKER,
        "",
        "## Counterparty topology",
        "",
        cfg.get("counterparty_topology") or NEEDS_CONTENT_MARKER,
        "",
        "## Notes",
        "",
        cfg.get("notes") or NEEDS_CONTENT_MARKER,
        "",
    ]
    return "\n".join(body_lines)


def render_overview(matter_slug: str, matter_name: str, today: str) -> str:
    fm = _vault_frontmatter(
        matter_slug, matter_name, today,
        sub_slug=f"{matter_slug}-overview",
        sub_name=f"{matter_name} — Overview",
    )
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    return "\n".join([
        "---", fm_text, "---", "",
        f"# {matter_name} — Overview",
        "",
        NEEDS_CONTENT_MARKER,
        "",
        "## Core entities",
        "",
        "- (populate from `cortex-config.md` `entities:` block)",
        "",
        "## Scope notes",
        "",
        "- (populate with matter framing — what this matter is, why Brisen "
        "cares, current headline)",
        "",
    ])


def render_index(matter_slug: str, matter_name: str, today: str) -> str:
    """_index.md — stub TOC for the matter directory.

    Per VAULT.md §2, the directory's _index.md carries the parent slug.
    No NEEDS_DIRECTOR_CONTENT marker per brief: index is auto-populated.
    """
    fm = _vault_frontmatter(
        matter_slug, matter_name, today,
        sub_slug=matter_slug,
        sub_name=f"{matter_name} — Index",
    )
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    return "\n".join([
        "---", fm_text, "---", "",
        f"# {matter_name} — Index",
        "",
        f"Top-level table of contents for `wiki/matters/{matter_slug}/`. "
        "Cortex reads `cortex-config.md` directly; the rest of the files "
        "below are Director-curated context the per-matter cycle pulls "
        "into Phase 2.",
        "",
        "## Files",
        "",
        "- `cortex-config.md` — Cortex per-matter brain (frontmatter +"
        " absorbed prompt body)",
        "- `_overview.md` — distilled-knowledge anchor",
        "- `agenda.md` — active items + deadlines",
        "- `state.md` — Cortex live state (per-cycle updates)",
        "- `proposed-gold.md` — agent-drafted insights awaiting ratification "
        "(Director writes `gold.md` manually on ratification — CHANDA #4 "
        "`author:director` guard blocks agent-authored gold.md commits)",
        "- `curated/` — Phase-2 specialist outputs (post-reasoned)",
        "",
    ])


def render_agenda(matter_slug: str, matter_name: str, today: str) -> str:
    fm = _vault_frontmatter(
        matter_slug, matter_name, today,
        sub_slug=f"{matter_slug}-agenda",
        sub_name=f"{matter_name} — Agenda",
    )
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    return "\n".join([
        "---", fm_text, "---", "",
        f"# {matter_name} — Agenda",
        "",
        NEEDS_CONTENT_MARKER,
        "",
        "## Active items",
        "",
        "- (populate with current matter actions, owners, deadlines)",
        "",
        "## Parked / dormant",
        "",
        "- (populate with deferred items)",
        "",
    ])


def render_state(matter_slug: str, matter_name: str, today: str) -> str:
    """state.md — Cortex per-cycle live-state file (architecture §2.1)."""
    fm = _vault_frontmatter(
        matter_slug, matter_name, today,
        sub_slug=f"{matter_slug}-state",
        sub_name=f"{matter_name} — State",
    )
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    return "\n".join([
        "---", fm_text, "---", "",
        f"# {matter_name} — State",
        "",
        NEEDS_CONTENT_MARKER,
        "",
        "## Current cycle",
        "",
        "- (Cortex updates this section on every per-matter cycle)",
        "",
        "## Last 3 cycles",
        "",
        "- (rolling window — auto-pruned)",
        "",
    ])


def render_proposed_gold(matter_slug: str, matter_name: str, today: str) -> str:
    fm = _vault_frontmatter(
        matter_slug, matter_name, today,
        sub_slug=f"{matter_slug}-proposed-gold",
        sub_name=f"{matter_name} — Proposed Gold",
        voice="gold",
    )
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    return "\n".join([
        "---", fm_text, "---", "",
        f"# {matter_name} — Proposed Gold",
        "",
        NEEDS_CONTENT_MARKER,
        "",
        "## Director Gold (DV)",
        "",
        "(empty — Director appends GOLD comments here as the matter develops)",
        "",
        "---",
        "",
        "## Proposed Gold (agent-drafted)",
        "",
        "(empty — Cortex appends Hybrid C V1 proposals here for Director review)",
        "",
    ])


# ---------------------------------------------------------------------------
# Output orchestration
# ---------------------------------------------------------------------------


SKELETON_FILES = (
    ("cortex-config.md", "cortex-config"),
    ("_overview.md", "overview"),
    ("_index.md", "index"),
    ("agenda.md", "agenda"),
    ("state.md", "state"),
    ("proposed-gold.md", "proposed-gold"),
    ("curated/directives.md", "directives"),
)
# NB: gold.md intentionally NOT emitted (BOOTSTRAP_V2_GOLD_SKIP_1, 2026-04-30).
# CHANDA #4 author:director guard blocks any agent-authored gold.md commit;
# Director writes gold.md manually on ratification. Emission was 4 manual
# revert drops/day before this guard.
# curated/directives.md added by CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 (2026-04-30):
# every new matter auto-provisions the Phase 6 Reflector directive surface.


def determine_staging_root(repo_root: Path, matter_slug: str) -> Path:
    primary_parent = repo_root / "vault_scaffolding" / "live_mirror" / "v1" / "matters"
    if primary_parent.parent.is_dir():
        return primary_parent / matter_slug
    fallback = repo_root / "outputs" / "matter_bootstrap" / "matters" / matter_slug
    print(
        f"[INFO] vault_scaffolding/live_mirror/v1/ not found.\n"
        f"       Emitting to fallback: {fallback}\n"
        f"       Move manually to baker-vault when ready (CHANDA #9).",
        file=sys.stderr,
    )
    return fallback


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
    if kind == "proposed-gold":
        return render_proposed_gold(matter_slug, matter_name, today)
    if kind == "directives":
        from orchestrator.cortex_directives import render_directives_template
        return render_directives_template(matter_slug, matter_name, today)
    raise ValueError(f"unknown skeleton kind: {kind}")


def _extract_frontmatter(content: str) -> dict:
    if not content.startswith("---\n"):
        raise ValueError("skeleton missing leading '---' frontmatter delimiter")
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("skeleton frontmatter not terminated")
    return yaml.safe_load(content[4:end])


def write_targets(
    out_root: Path,
    cfg: dict,
    today: str,
    *,
    force: bool,
) -> int:
    """Emit all skeleton files + curated/.gitkeep. Returns count of files written."""
    from kbl.ingest_endpoint import validate_frontmatter

    if not force:
        for filename, _ in SKELETON_FILES:
            target = out_root / filename
            if target.exists():
                print(
                    f"ERROR: skeleton exists at {target}. "
                    f"Pass --force to overwrite.",
                    file=sys.stderr,
                )
                raise SystemExit(1)
        gitkeep = out_root / "curated" / ".gitkeep"
        if gitkeep.exists():
            print(
                f"ERROR: curated/.gitkeep exists at {gitkeep}. "
                f"Pass --force to overwrite.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    out_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for filename, kind in SKELETON_FILES:
        content = render_skeleton(filename, kind, cfg, today)
        fm = _extract_frontmatter(content)
        validate_frontmatter(fm)
        target = out_root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    (out_root / "curated").mkdir(parents=True, exist_ok=True)
    (out_root / "curated" / ".gitkeep").write_text("", encoding="utf-8")
    written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--input", type=Path, required=True,
        help="Path to per-matter input YAML (briefs/_inputs/bootstrap_<slug>.yml).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be emitted; write nothing.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing skeleton files (default: fail on collision).",
    )
    parser.add_argument(
        "--vault-root", type=Path, default=DEFAULT_VAULT_ROOT,
        help=f"Path to baker-vault checkout (default: {DEFAULT_VAULT_ROOT}).",
    )
    parser.add_argument(
        "--out-root", type=Path, default=None,
        help="Override staging root (defaults to repo's vault_scaffolding or outputs).",
    )
    parser.add_argument(
        "--today", type=str, default=date.today().isoformat(),
        help="ISO date for `updated` frontmatter field (default: today).",
    )
    args = parser.parse_args(argv)

    try:
        cfg_raw = load_input(args.input)
        cfg = apply_defaults(cfg_raw)
        validate_input(cfg, vault_root=args.vault_root)
    except BootstrapError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    matter_slug = cfg["matter_slug"]

    # Soft-flag: missing entity slugs in entities.yml.
    missing = check_entity_slugs_exist(cfg, args.vault_root)
    if missing:
        print(
            f"[WARN] entity slugs not found in entities.yml: {sorted(set(missing))}\n"
            f"       Run scripts/bootstrap_entities.py with these slugs before "
            f"the Mac Mini mirror, or add manually.",
            file=sys.stderr,
        )

    # Soft-flag: slug not in slugs.yml (warn only — required for matter writes
    # downstream but not for this generator).
    in_registry = check_slug_in_registry(matter_slug, args.vault_root)
    if in_registry is False:
        print(
            f"[WARN] matter_slug {matter_slug!r} not in slugs.yml — add it via "
            f"baker-vault PR before the matter goes live.",
            file=sys.stderr,
        )

    out_root = (
        args.out_root if args.out_root is not None
        else determine_staging_root(REPO_ROOT, matter_slug)
    )

    if args.dry_run:
        targets = [fn for fn, _ in SKELETON_FILES] + ["curated/.gitkeep"]
        print(f"[DRY-RUN] Would emit {len(targets)} files under {out_root}:")
        for t in targets:
            print(f"  - {t}")
        return 0

    written = write_targets(out_root, cfg, args.today, force=args.force)
    print(f"[OK] Emitted {written} skeleton files under {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
