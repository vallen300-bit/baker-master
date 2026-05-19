#!/usr/bin/env python3
"""build_authority_profiles.py — scan ~/baker-vault/_ops/agents/*/LONGTERM.md,
extract person blocks, emit unified ~/baker-vault/_ops/people/authority-profiles.yml.

Extraction rule (v1, deliberately simple):
- Match lines like `**<Name>** — <description>` or `- **<Name>** — <description>`.
- Name = group(1). Authority = description text up to next newline.
- Multiple desks may mention the same person; merge profiles (descriptions deduped,
  source desks listed).
- Heuristic person-filter: name has ≥1 space (excludes single-word org names like
  "MRCI") AND does not end with a known org suffix (GmbH, AG, SA, Ltd, Inc, KG)
  AND is not in a known concept-tag denylist (Pattern A / Pattern B / etc).

authority_class heuristic (regex-driven, v1):
  - "monthly" → "monthly-consult"
  - "weekly" → "standing-consult-weekly"
  - "standing" + ("monthly"|"weekly"|"daily") → "standing-consult-<period>"
  - "Chairman" | "Director" | "CEO" | "GF" | "Geschäftsführer" → "principal"
  - "owner" + ("snagging"|"BAG"|"visit"|"review") → "standing-consult-<scope>"
  - default → "ad-hoc"

Hardcoded principals (never demoted to ad-hoc regardless of description):
  - Dimitry Vallen → principal

CLI:
  build_authority_profiles.py [--dry-run] [--write] [--vault-root PATH]
  Default vault-root = $HOME/baker-vault.
  Default = dry-run (per brief: never auto-commit; Director must ratify).
  --write: actually write the file.
  Exit non-zero on parse failure.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. pip install pyyaml", file=sys.stderr)
    sys.exit(2)


PERSON_LINE_RE = re.compile(
    r"^\s*-?\s*\*\*([^*\n]+?)\*\*\s*[—–-]\s*(.+?)\s*$",
    re.MULTILINE,
)

ORG_SUFFIXES = (
    "GmbH",
    "AG",
    "SA",
    "S.A.",
    "Ltd",
    "Inc",
    "KG",
    "Holding",
    "Bank",
    "Capital",
)

CONCEPT_DENYLIST = {
    "Pattern A (autonomous send)",
    "Pattern B (visible draft)",
    "Director-ratified",
    "Counterparty-signed",
    "Data-confirmed",
    "Laconic comm style",
    "Project executed via Lilienmatt GmbH",
    "Eastdil Secured (NOT Eastdeal)",
}

PRINCIPAL_OVERRIDES = {
    "dimitry-vallen": ("Dimitry Vallen", "principal"),
}


def slugify(name: str) -> str:
    """Convert 'Rolf Hübner' → 'rolf-hubner'."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_name = ascii_name.lower()
    ascii_name = re.sub(r"[^a-z0-9]+", "-", ascii_name)
    ascii_name = ascii_name.strip("-")
    return ascii_name


def is_person_name(name: str) -> bool:
    """Heuristic filter: include names that look like people, exclude orgs/concepts."""
    name = name.strip()
    if name in CONCEPT_DENYLIST:
        return False
    if any(name.endswith(" " + s) for s in ORG_SUFFIXES):
        return False
    if name.endswith(" GmbH") or name.endswith(" AG"):
        return False
    # Must contain a space (two-word minimum) OR explicit allowlist.
    if " " not in name:
        return False
    # Reject if starts with non-alpha (e.g. comes from a heading)
    if not name[0].isalpha():
        return False
    # Reject obvious non-person phrases (heuristic, conservative)
    lower = name.lower()
    if any(word in lower for word in ("project", "pattern", "ratified", "confirmed", "comm style", "locked", "license", "lender", "framing", "stack", "license-stack")):
        return False
    # Reject multi-person aggregates ("A / B / C") and names with digits.
    if "/" in name:
        return False
    if any(ch.isdigit() for ch in name):
        return False
    return True


def classify_authority(description: str) -> str:
    """Map free-form description to one of the canonical authority classes."""
    d = description.lower()
    if re.search(r"\b(chairman|director|\bceo\b|\bgf\b|geschäftsführer|geschaftsfuhrer)\b", d):
        return "principal"
    if "standing" in d and "monthly" in d:
        return "standing-consult-monthly"
    if "standing" in d and "weekly" in d:
        return "standing-consult-weekly"
    if "standing" in d and "daily" in d:
        return "standing-consult-daily"
    if "monthly" in d:
        return "monthly-consult"
    if "weekly" in d:
        return "standing-consult-weekly"
    if re.search(r"\bowner\b", d) and re.search(r"\b(snagging|bag|visit|review)\b", d):
        return "standing-consult-scope"
    return "ad-hoc"


def extract_role(description: str) -> str:
    """First clause of description (up to first ' · ' or '. ') is treated as role."""
    desc = description.strip()
    for sep in (" · ", ". ", " — ", "; "):
        if sep in desc:
            return desc.split(sep, 1)[0].strip()
    return desc[:120].strip()


def scan_vault(vault_root: Path) -> dict:
    """Walk _ops/agents/*/LONGTERM.md, return merged profiles dict."""
    agents_dir = vault_root / "_ops" / "agents"
    if not agents_dir.is_dir():
        raise FileNotFoundError(f"agents dir missing: {agents_dir}")

    profiles: dict[str, dict] = {}

    for longterm in sorted(agents_dir.glob("*/LONGTERM.md")):
        desk = longterm.parent.name
        try:
            text = longterm.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"WARN: skipping {longterm}: {e}", file=sys.stderr)
            continue

        for match in PERSON_LINE_RE.finditer(text):
            name = match.group(1).strip()
            description = match.group(2).strip()
            if not is_person_name(name):
                continue

            slug = slugify(name)
            if not slug:
                continue

            if slug not in profiles:
                profiles[slug] = {
                    "canonical_name": name,
                    "aliases": [],
                    "role": extract_role(description),
                    "authority_class": classify_authority(description),
                    "source_desks": [],
                    "raw_descriptions": [],
                }
            entry = profiles[slug]
            if desk not in entry["source_desks"]:
                entry["source_desks"].append(desk)
            entry["raw_descriptions"].append({"desk": desk, "text": description})

            # Derive aliases: first name + last word
            parts = name.split()
            for alias in (parts[0], parts[-1]):
                if alias and alias != name and alias not in entry["aliases"]:
                    entry["aliases"].append(alias)

    # Hardcoded principal overrides — never demoted regardless of description.
    for slug, (canonical, cls) in PRINCIPAL_OVERRIDES.items():
        if slug not in profiles:
            profiles[slug] = {
                "canonical_name": canonical,
                "aliases": [canonical.split()[0]],
                "role": "Chairman, Brisen Group",
                "authority_class": cls,
                "source_desks": ["__hardcoded__"],
                "raw_descriptions": [
                    {"desk": "__hardcoded__", "text": "Director Dimitry Vallen — hardcoded principal."}
                ],
            }
        else:
            profiles[slug]["authority_class"] = cls

    return profiles


def emit_yaml(profiles: dict) -> str:
    document = {"authority_profiles": profiles}
    return yaml.safe_dump(document, sort_keys=True, allow_unicode=True, width=120)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Print yml to stdout, do not write (default).")
    ap.add_argument("--write", action="store_true",
                    help="Actually write _ops/people/authority-profiles.yml.")
    ap.add_argument("--vault-root", default=os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")),
                    help="Path to baker-vault checkout.")
    args = ap.parse_args()

    vault_root = Path(args.vault_root).expanduser().resolve()
    try:
        profiles = scan_vault(vault_root)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output = emit_yaml(profiles)

    if args.write:
        out_dir = vault_root / "_ops" / "people"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "authority-profiles.yml"
        out_path.write_text(output, encoding="utf-8")
        print(f"wrote: {out_path} ({len(profiles)} profiles)", file=sys.stderr)
    else:
        sys.stdout.write(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
