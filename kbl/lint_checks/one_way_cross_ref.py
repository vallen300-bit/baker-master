"""Check 4 — one_way_cross_ref (warn, deterministic).

Builds the directed cross-ref graph from each matter's hub file
(``_links.md`` for flat, ``_index.md`` for nested) plus frontmatter
``related_matters`` across all the matter's md files. Flags edges
A → B without a reciprocal B → A.

Sub-page resolution: links to ``<parent>/sub/foo`` resolve to
``<parent>``; links into ``<parent>/sub-matters/<sub>/...`` resolve
to ``<sub>``.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from . import _common as C

CHECK_NAME = "one_way_cross_ref"


def _hub_file(m: C.MatterDir) -> Path | None:
    primary = m.path / ("_index.md" if m.nested else "_links.md")
    if primary.is_file():
        return primary
    return None


def _edges_from(matters: list[C.MatterDir], slugs: set[str]) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = defaultdict(set)
    for m in matters:
        targets: set[str] = set()
        hub = _hub_file(m)
        if hub is not None:
            try:
                text = hub.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for tok in C.extract_link_tokens(text):
                # token may be a wiki-relative path or a bare slug
                if "/" in tok:
                    parts = tok.split("/")
                    head = parts[0]
                    if head == "wiki" and len(parts) > 1:
                        rel = "/".join(parts)
                    else:
                        rel = "wiki/" + "/".join(parts)
                    resolved = C.resolve_to_parent_slug(rel, slugs)
                else:
                    resolved = tok if tok in slugs else None
                if resolved and resolved != m.slug:
                    targets.add(resolved)
        # Also fold in frontmatter related_matters across all md files in dir
        for md in C.iter_md_files(m.path):
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm = C.parse_frontmatter(text)
            rel_list = fm.get("related_matters") or []
            if isinstance(rel_list, str):
                rel_list = [rel_list]
            for s in rel_list:
                if s in slugs and s != m.slug:
                    targets.add(s)
        edges[m.slug] |= targets
    return edges


def run(vault_path: Path, registries: dict) -> list[C.LintHit]:
    matters = C.discover_matter_dirs(vault_path)
    if not matters:
        return []
    slugs = {m.slug for m in matters}
    edges = _edges_from(matters, slugs)

    by_slug = {m.slug: m for m in matters}
    hits: list[C.LintHit] = []
    for src, dsts in edges.items():
        for dst in sorted(dsts):
            if src in edges.get(dst, set()):
                continue
            origin = by_slug.get(src)
            if origin is None:
                continue
            hits.append(C.LintHit(
                check=CHECK_NAME,
                severity=C.Severity.WARN,
                path=origin.rel,
                line=None,
                message=f"`{src}` links to `{dst}` but `{dst}` has no reciprocal back-edge",
            ))
    return hits
