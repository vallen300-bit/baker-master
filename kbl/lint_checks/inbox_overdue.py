"""Check 7 — inbox_overdue (info, deterministic).

Flags files in ``wiki/_inbox/`` older than ``WIKI_LINT_INBOX_DAYS``
(default 14 days). Filename date prefix wins; falls back to mtime.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

from . import _common as C

CHECK_NAME = "inbox_overdue"

_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})_")


def _file_date(p: Path) -> _dt.date | None:
    m = _DATE_PREFIX.match(p.name)
    if m:
        try:
            return _dt.date.fromisoformat(m.group(1))
        except ValueError:
            pass
    try:
        ts = p.stat().st_mtime
    except OSError:
        return None
    return _dt.datetime.utcfromtimestamp(ts).date()


def run(vault_path: Path, registries: dict) -> list[C.LintHit]:
    inbox = vault_path / "wiki" / "_inbox"
    if not inbox.is_dir():
        return []
    days = int(registries.get("inbox_days", 14))
    today = registries.get("today_utc")
    if isinstance(today, str):
        today = _dt.date.fromisoformat(today)
    elif today is None:
        today = _dt.datetime.utcnow().date()
    cutoff = today - _dt.timedelta(days=days)

    hits: list[C.LintHit] = []
    for md in C.iter_md_files(inbox):
        d = _file_date(md)
        if d is None or d > cutoff:
            continue
        rel = str(md.relative_to(vault_path)).replace("\\", "/")
        hits.append(C.LintHit(
            check=CHECK_NAME,
            severity=C.Severity.INFO,
            path=rel,
            line=None,
            message=f"inbox file dated {d.isoformat()} is older than {days} days",
        ))
    return hits
