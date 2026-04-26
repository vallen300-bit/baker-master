"""Check 2 — missing_required_files (error, deterministic).

Required files per pattern:
  * Flat   → ``_links.md``
  * Nested → ``_index.md`` ∧ ``gold.md`` ∧ ``_overview.md``

Grandfather clause: flat-pattern matter dirs that already existed before
``GRANDFATHER_CUTOFF`` are downgraded to **warn** for missing files. The
"created before" test uses the oldest mtime among the dir's `.md` files
as a stable proxy (no git history dependency on Render).
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

from . import _common as C

CHECK_NAME = "missing_required_files"

NESTED_REQUIRED = ("_index.md", "gold.md", "_overview.md")
FLAT_REQUIRED = ("_links.md",)


def _earliest_mtime_iso(p: Path) -> str | None:
    earliest: float | None = None
    for f in p.rglob("*.md"):
        try:
            ts = f.stat().st_mtime
        except OSError:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
    if earliest is None:
        return None
    return _dt.datetime.utcfromtimestamp(earliest).strftime("%Y-%m-%d")


def run(vault_path: Path, registries: dict) -> list[C.LintHit]:
    hits: list[C.LintHit] = []
    cutoff = registries.get("grandfather_cutoff", C.GRANDFATHER_CUTOFF)

    for m in C.discover_matter_dirs(vault_path):
        required = NESTED_REQUIRED if m.nested else FLAT_REQUIRED
        # Grandfather clause applies to BOTH patterns: matter dirs whose
        # earliest file mtime predates the cutoff are downgraded to warn.
        # Spec §"Hagenauer-first acceptance test" sets criterion 3 ("0
        # errors on real-vault dry-run"); pre-cutoff incomplete dirs were
        # the operator's reality at brief-time, so warn-not-error matches
        # the curate-then-ratchet plan (M1 bootstrap fills nested skeletons).
        earliest = _earliest_mtime_iso(m.path)
        is_grandfathered = earliest is not None and earliest < cutoff
        for fname in required:
            if (m.path / fname).is_file():
                continue
            severity = (
                C.Severity.WARN if is_grandfathered else C.Severity.ERROR
            )
            note = (
                f" (grandfathered: pre-{cutoff})" if is_grandfathered else ""
            )
            hits.append(C.LintHit(
                check=CHECK_NAME,
                severity=severity,
                path=m.rel,
                line=None,
                message=f"missing required file `{fname}` for "
                        f"{'nested' if m.nested else 'flat'} pattern{note}",
            ))
    return hits
