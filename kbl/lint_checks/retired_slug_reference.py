"""Check 1 — retired_slug_reference (error, deterministic).

Flags any wiki .md file referencing a slug whose status is `retired` in
``baker-vault/slugs.yml``. Detection covers four shapes:
  * frontmatter ``primary_matter: <slug>`` / list-valued ``related_matters``
  * wiki-links ``[[<slug>/...]]`` / ``[[<slug>]]``
  * markdown links ``[..](<slug>/...)``
  * path components — ``wiki/<slug>/...`` is itself a violation if slug is
    retired (the directory shouldn't exist post-retirement)
"""
from __future__ import annotations

from pathlib import Path

from . import _common as C

CHECK_NAME = "retired_slug_reference"


def run(vault_path: Path, registries: dict) -> list[C.LintHit]:
    retired: set[str] = set(registries.get("retired_slugs") or [])
    if not retired:
        return []

    hits: list[C.LintHit] = []
    wiki_root = vault_path / "wiki"
    if not wiki_root.is_dir():
        return hits

    for md in C.iter_md_files(wiki_root):
        rel = str(md.relative_to(vault_path)).replace("\\", "/")
        # path-component check
        parts = rel.split("/")
        for slug in retired:
            if slug in parts[1:]:  # skip 'wiki' itself
                hits.append(C.LintHit(
                    check=CHECK_NAME,
                    severity=C.Severity.ERROR,
                    path=rel,
                    line=None,
                    message=f"path contains retired slug `{slug}`",
                ))
                break

        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        fm = C.parse_frontmatter(text)
        for key in ("primary_matter", "related_matters"):
            v = fm.get(key)
            if v is None:
                continue
            values = v if isinstance(v, list) else [v]
            for val in values:
                if val in retired:
                    hits.append(C.LintHit(
                        check=CHECK_NAME,
                        severity=C.Severity.ERROR,
                        path=rel,
                        line=C.find_line(text, val),
                        message=f"frontmatter `{key}` references retired slug `{val}`",
                    ))

        for token in C.extract_link_tokens(text):
            head = token.split("/", 1)[0].strip()
            if head in retired:
                hits.append(C.LintHit(
                    check=CHECK_NAME,
                    severity=C.Severity.ERROR,
                    path=rel,
                    line=C.find_line(text, head),
                    message=f"link references retired slug `{head}`",
                ))

    return hits
