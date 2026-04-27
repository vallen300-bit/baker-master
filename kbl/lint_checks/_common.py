"""Shared types + helpers for wiki lint checks (WIKI_LINT_1).

Pattern detection rule (per spec §"Pattern detector false-positives"):
presence of ``_index.md`` at the matter directory root → nested.
Otherwise flat. The same matter slug may appear in either layout, but
each occurrence is classified locally — never mixed.

Sub-page resolution rule (Director-ratified 2026-04-26):
file paths under ``wiki/matters/<slug>/**`` belong to ``<slug>``;
``wiki/matters/<parent>/sub-matters/<sub>/**`` belongs to ``<sub>``.
Reserved filenames (``_index.md``, ``_overview.md``, ``gold.md``,
``proposed-gold.md``, ``red-flags.md``, ``_links.md``) inherit from
their parent directory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


class Severity(str, Enum):
    ERROR = "error"
    WARN = "warn"
    INFO = "info"


@dataclass(frozen=True)
class LintHit:
    check: str
    severity: Severity
    path: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class MatterDir:
    """A matter dir discovered on disk."""
    slug: str
    path: Path                # absolute
    rel: str                  # relative to vault root, posix-style
    nested: bool              # True if `_index.md` present


# Files that are "reserved" — they belong to the parent matter dir.
RESERVED_FILES = frozenset({
    "_index.md",
    "_overview.md",
    "gold.md",
    "proposed-gold.md",
    "red-flags.md",
    "_links.md",
})

# Grandfather cutoff for missing_required_files (check 2): flat-pattern
# matter dirs that already existed before this date are downgraded to
# warn instead of error when their convention files are missing.
GRANDFATHER_CUTOFF = "2026-04-23"

# Path prefixes inside `wiki/` that are NOT matter dirs.
SKIP_PREFIXES = ("_inbox",)


def _is_nested_root(p: Path) -> bool:
    return (p / "_index.md").is_file()


def discover_matter_dirs(vault_path: Path) -> list[MatterDir]:
    """Walk vault/wiki/ → enumerate matter dirs.

    Flat:    wiki/<slug>/                       (skips _inbox, matters)
    Nested:  wiki/matters/<slug>/                (slug is dir name)
    Sub:     wiki/matters/<parent>/sub-matters/<sub>/  (sub is its own slug)
    """
    wiki_root = vault_path / "wiki"
    if not wiki_root.is_dir():
        return []

    out: list[MatterDir] = []

    # Top-level entries
    for entry in sorted(wiki_root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name.startswith(".") or name in SKIP_PREFIXES:
            continue
        if name == "matters":
            # `wiki/matters/<slug>/` is nested-by-location, regardless of
            # _index.md presence (the latter is one of the files we lint
            # FOR — its absence is a finding, not a pattern flip).
            for sub in sorted(entry.iterdir()):
                if not sub.is_dir() or sub.name.startswith("."):
                    continue
                out.append(MatterDir(
                    slug=sub.name,
                    path=sub,
                    rel=str(sub.relative_to(vault_path)).replace("\\", "/"),
                    nested=True,
                ))
                sm_root = sub / "sub-matters"
                if sm_root.is_dir():
                    for sm in sorted(sm_root.iterdir()):
                        if not sm.is_dir() or sm.name.startswith("."):
                            continue
                        out.append(MatterDir(
                            slug=sm.name,
                            path=sm,
                            rel=str(sm.relative_to(vault_path)).replace("\\", "/"),
                            nested=True,
                        ))
            continue
        # `wiki/<slug>/` is flat by default. Edge case: legacy migration
        # in flight may have produced `wiki/<slug>/_index.md` — when that
        # happens, treat as nested so the lint accepts the migrated shape
        # rather than falsely flagging _links.md missing.
        out.append(MatterDir(
            slug=name,
            path=entry,
            rel=str(entry.relative_to(vault_path)).replace("\\", "/"),
            nested=_is_nested_root(entry),
        ))
    return out


def resolve_to_parent_slug(rel_path: str, known_slugs: set[str]) -> str | None:
    """Map any wiki/ relative path to its owning matter slug.

    Per sub-page resolution rule:
      * ``wiki/matters/<parent>/sub-matters/<sub>/...`` → ``<sub>`` (if known).
      * ``wiki/matters/<slug>/...``                     → ``<slug>``.
      * ``wiki/<slug>/...``                             → ``<slug>``.
    Returns None for paths inside ``wiki/_inbox/`` or unrecognized slugs.
    """
    parts = [p for p in rel_path.split("/") if p]
    if len(parts) < 2 or parts[0] != "wiki":
        return None
    if parts[1] == "_inbox":
        return None
    if parts[1] == "matters":
        if len(parts) < 3:
            return None
        # sub-matter wins
        if len(parts) >= 5 and parts[3] == "sub-matters":
            sub = parts[4]
            if sub in known_slugs:
                return sub
        parent = parts[2]
        if parent in known_slugs:
            return parent
        return None
    candidate = parts[1]
    if candidate in known_slugs:
        return candidate
    return None


# Wiki-link / markdown-link / frontmatter-list scanners.
_WIKI_LINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[#\|][^\]]*)?\]\]")
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict:
    """Best-effort frontmatter extractor (no PyYAML dependency required for
    the lint surface area we touch — a thin parser handles ``key: value``
    + ``key: [a, b, c]`` + ``key:\\n  - a\\n  - b``)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    body = m.group(1)
    out: dict = {}
    current_key: str | None = None
    for raw in body.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            current_key = None
            continue
        if not line.startswith(" "):
            if ":" not in line:
                current_key = None
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value == "":
                out[key] = []
                current_key = key
            elif value.startswith("[") and value.endswith("]"):
                inner = value[1:-1].strip()
                items = [
                    s.strip().strip("'\"") for s in inner.split(",") if s.strip()
                ]
                out[key] = items
                current_key = None
            else:
                out[key] = value.strip("'\"")
                current_key = None
        else:
            stripped = line.strip()
            if stripped.startswith("- ") and current_key is not None:
                val = stripped[2:].strip().strip("'\"")
                lst = out.setdefault(current_key, [])
                if isinstance(lst, list):
                    lst.append(val)
    return out


def iter_md_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for p in root.rglob("*.md"):
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            continue
        yield p


def extract_link_tokens(text: str) -> list[str]:
    """Return raw tokens of every [[wiki-link]] + (markdown-link) target."""
    out: list[str] = []
    out.extend(m.group(1) for m in _WIKI_LINK_RE.finditer(text))
    out.extend(m.group(1) for m in _MARKDOWN_LINK_RE.finditer(text))
    return out


def find_line(text: str, needle: str) -> int | None:
    """1-based first line containing ``needle``; None if absent."""
    for i, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return i
    return None
