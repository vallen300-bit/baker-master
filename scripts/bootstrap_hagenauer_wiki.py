"""Bootstrap Hagenauer matter-shape skeleton (HAGENAUER_WIKI_BOOTSTRAP_1).

One-shot generator that:
1. Reads `wiki/matters/oskolkov/` and `wiki/matters/movie/` from a baker-vault
   checkout, computes the canonical matter-shape (intersection = required,
   union extras = optional).
2. Emits skeleton `.md` files for `hagenauer-rg7` at a staging path
   (`vault_scaffolding/live_mirror/v1/matters/hagenauer-rg7/` if its parent
   tree exists, else `outputs/hagenauer_bootstrap/matters/hagenauer-rg7/`).
3. Each skeleton has VAULT.md §2-compliant frontmatter (validated against
   `kbl.ingest_endpoint.validate_frontmatter`) and a body listing the
   `14_HAGENAUER_MASTER/` source folders to draw content from, plus a
   `[NEEDS_DIRECTOR_CONTENT]` marker.

Does NOT write to baker-vault, does NOT call ingest, does NOT touch DB.
CHANDA #9: Baker never writes baker-vault directly. This generator stages
locally; Director or AI Head Tier B decides whether to mirror.

Architectural ambiguity (sub-page slug schema): see ship report — option (a)
parent-slug-as-tag is used here pending decision on registry inflation vs
new `type: matter-page`.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_VAULT_ROOT = Path.home() / "baker-vault"

REFERENCE_MATTERS = ("oskolkov", "movie")
HAGENAUER_SLUG = "hagenauer-rg7"
NEEDS_CONTENT_MARKER = "[NEEDS_DIRECTOR_CONTENT]"

# Director-curated mapping: which 14_HAGENAUER_MASTER subfolder(s) feed each
# canonical skeleton page. Empty list = no source folder (e.g. gold.md is
# populated only by lesson-promotion, never raw curation).
SOURCE_FOLDERS = {
    "_overview.md": [
        "01_Agreements_Contracts/",
        "06_Project_Documentation/",
    ],
    "_index.md": [
        "(all 10 numbered subfolders — top-level table of contents)",
    ],
    "_schema-legacy.md": [],
    "agenda.md": [
        "08_Correspondence/",
        "09_Negotiations_History/",
    ],
    "financial-facts.md": [
        "02_Claims_Against_Hagenauer/",
        "03_Payments_Invoices/",
    ],
    "gold.md": [],
    "proposed-gold.md": [],
    "red-flags.md": [
        "02_Claims_Against_Hagenauer/",
        "04_Subcontractors/",
    ],
}

GOLD_FILES = frozenset({"gold.md", "proposed-gold.md"})


def discover_matter_shape(vault_root: Path) -> dict:
    """Return required (intersection) + optional (union extras) matter-shape sets.

    Raises FileNotFoundError if either reference matter dir is missing.
    """
    reference_dirs = [vault_root / "wiki" / "matters" / m for m in REFERENCE_MATTERS]
    file_sets: list[set[str]] = []
    subdir_sets: list[set[str]] = []
    for d in reference_dirs:
        if not d.is_dir():
            raise FileNotFoundError(f"reference matter dir not found: {d}")
        files = {p.name for p in d.iterdir() if p.is_file() and p.suffix == ".md"}
        subdirs = {p.name for p in d.iterdir() if p.is_dir()}
        file_sets.append(files)
        subdir_sets.append(subdirs)
    required_files = sorted(set.intersection(*file_sets))
    optional_files = sorted(set.union(*file_sets) - set.intersection(*file_sets))
    required_subdirs = sorted(set.intersection(*subdir_sets))
    optional_subdirs = sorted(set.union(*subdir_sets) - set.intersection(*subdir_sets))
    return {
        "required_files": required_files,
        "optional_files": optional_files,
        "required_subdirs": required_subdirs,
        "optional_subdirs": optional_subdirs,
    }


def filename_to_slug(filename: str) -> str:
    """Convert a matter-shape filename to a kebab-case sub-page slug."""
    stem = Path(filename).stem.lstrip("_").replace("_", "-")
    return f"{HAGENAUER_SLUG}-{stem}"


def filename_to_name(filename: str) -> str:
    """Human-readable name for the frontmatter `name` field."""
    stem = Path(filename).stem.lstrip("_").replace("-", " ").replace("_", " ")
    return f"Hagenauer RG7 — {stem.title()}"


def build_frontmatter(filename: str, today: str) -> dict:
    """Build VAULT.md §2-compliant frontmatter dict for a skeleton file."""
    fm = {
        "type": "matter",
        "slug": filename_to_slug(filename),
        "name": filename_to_name(filename),
        "updated": today,
        "author": "agent",
        "tags": [HAGENAUER_SLUG],
        "related": [],
    }
    if filename in GOLD_FILES:
        fm["voice"] = "gold"
    return fm


def render_skeleton(filename: str, sources: list[str], today: str) -> str:
    """Render a full skeleton .md file (frontmatter + placeholder body)."""
    fm = build_frontmatter(filename, today)
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    lines = [
        "---",
        fm_text,
        "---",
        "",
        f"# {fm['name']}",
        "",
        NEEDS_CONTENT_MARKER,
        "",
        "## Source folders",
        "",
    ]
    if sources:
        for sf in sources:
            lines.append(f"- `14_HAGENAUER_MASTER/{sf}`")
    else:
        lines.append("- (none — placeholder for promoted / curated content)")
    lines += [
        "",
        "## Notes",
        "",
        "- Skeleton emitted by `scripts/bootstrap_hagenauer_wiki.py` "
        "(HAGENAUER_WIKI_BOOTSTRAP_1).",
        "- Replace this body with content distilled from the source folder(s) above.",
        f"- Strip the `{NEEDS_CONTENT_MARKER}` marker once content is curated.",
        "",
    ]
    return "\n".join(lines)


def render_subdir_readme(subdir_name: str, today: str) -> str:
    """Render a placeholder README inside a required subdir."""
    fm = {
        "type": "matter",
        "slug": f"{HAGENAUER_SLUG}-{subdir_name}-readme",
        "name": f"Hagenauer RG7 — {subdir_name} index",
        "updated": today,
        "author": "agent",
        "tags": [HAGENAUER_SLUG, subdir_name],
        "related": [],
    }
    fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
    return "\n".join([
        "---",
        fm_text,
        "---",
        "",
        f"# {subdir_name}/ — placeholder index",
        "",
        NEEDS_CONTENT_MARKER,
        "",
        f"This subdir mirrors the `{subdir_name}/` shape from "
        "the oskolkov + movie reference matters.",
        "",
    ])


def determine_staging_root(repo_root: Path) -> Path:
    """Pick `vault_scaffolding/live_mirror/v1/` if present, else `outputs/...`.

    Prints a stderr instruction if the fallback is used so Director knows to
    manually mirror to baker-vault later.
    """
    primary = (
        repo_root / "vault_scaffolding" / "live_mirror" / "v1" / "matters" / HAGENAUER_SLUG
    )
    if primary.parent.parent.is_dir():
        return primary
    fallback = repo_root / "outputs" / "hagenauer_bootstrap" / "matters" / HAGENAUER_SLUG
    print(
        f"[INFO] vault_scaffolding/live_mirror/v1/ not found.\n"
        f"       Emitting to fallback: {fallback}\n"
        f"       Move manually to baker-vault when ready (CHANDA #9).",
        file=sys.stderr,
    )
    return fallback


def collect_targets(shape: dict) -> list[tuple[Path, str]]:
    """Return [(relative_path, kind)] where kind in {'file','readme'}."""
    targets: list[tuple[Path, str]] = []
    for fn in shape["required_files"]:
        targets.append((Path(fn), "file"))
    for sd in shape["required_subdirs"]:
        targets.append((Path(sd) / "_README.md", "readme"))
    return targets


def write_targets(
    out_root: Path,
    targets: list[tuple[Path, str]],
    today: str,
    *,
    force: bool,
) -> int:
    """Write all targets under out_root. Returns number of files written.

    Raises SystemExit(1) if any target exists and force is False.
    Validates each emitted frontmatter against kbl.ingest_endpoint.validate_frontmatter.
    """
    from kbl.ingest_endpoint import validate_frontmatter

    if not force:
        for rel, _ in targets:
            target = out_root / rel
            if target.exists():
                print(
                    f"ERROR: skeleton exists at {target}. "
                    f"Pass --force to overwrite.",
                    file=sys.stderr,
                )
                raise SystemExit(1)

    out_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for rel, kind in targets:
        if kind == "file":
            content = render_skeleton(rel.name, SOURCE_FOLDERS.get(rel.name, []), today)
        else:
            content = render_subdir_readme(rel.parent.name, today)
        # Validate frontmatter — raises KBLIngestError on schema drift.
        fm = _extract_frontmatter(content)
        validate_frontmatter(fm)
        target = out_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    return written


def _extract_frontmatter(content: str) -> dict:
    """Parse the YAML frontmatter block from a rendered skeleton."""
    if not content.startswith("---\n"):
        raise ValueError("skeleton missing leading '---' frontmatter delimiter")
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("skeleton frontmatter not terminated")
    return yaml.safe_load(content[4:end])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be emitted; write nothing.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing skeleton files (default: fail).",
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

    shape = discover_matter_shape(args.vault_root)
    targets = collect_targets(shape)
    out_root = args.out_root if args.out_root is not None else determine_staging_root(REPO_ROOT)

    if args.dry_run:
        print(f"[DRY-RUN] Would emit {len(targets)} files under {out_root}:")
        for rel, _ in targets:
            print(f"  - {rel}")
        if shape["optional_files"]:
            print(
                f"\n[INFO] Optional matter-specific files (not emitted, "
                f"may be added later): {shape['optional_files']}"
            )
        if shape["optional_subdirs"]:
            print(f"[INFO] Optional subdirs: {shape['optional_subdirs']}")
        return 0

    written = write_targets(out_root, targets, args.today, force=args.force)
    print(f"[OK] Emitted {written} skeleton files under {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
