"""Programmatic fixture builder for WIKI_LINT_1 tests.

Builds a deterministic baker-vault tree under a caller-supplied
``tmp_path``. Stamps mtimes explicitly so checks that depend on file
age (grandfather clause, inbox_overdue, stale_active_matter) are
reproducible across runs and across CI vs local.
"""
from __future__ import annotations

import datetime as _dt
import os
import time
from pathlib import Path

# Reference "today" used by tests. Lines up with the brief's
# 2026-04-26 dispatch date.
TODAY = _dt.date(2026, 4, 26)
NOW = _dt.datetime(2026, 4, 26, 12, 0, 0)


def _epoch(d: _dt.datetime | _dt.date) -> float:
    if isinstance(d, _dt.date) and not isinstance(d, _dt.datetime):
        d = _dt.datetime.combine(d, _dt.time(12, 0))
    return time.mktime(d.timetuple())


SLUGS_YML = """version: 99
matters:
  - slug: flat-old
    status: active
    description: "Flat-pattern, pre-cutoff (grandfathered)"
    aliases: []
  - slug: flat-new
    status: active
    description: "Flat-pattern, post-cutoff (must have _links.md)"
    aliases: []
  - slug: orphan-flat
    status: active
    description: "Flat-pattern, no inbound + no signals"
    aliases: []
  - slug: nested-good
    status: active
    description: "Nested-pattern, fully populated"
    aliases: []
  - slug: nested-missing
    status: active
    description: "Nested-pattern, missing required files"
    aliases: []
  - slug: movie-x
    status: active
    description: "Nested parent matter"
    aliases: []
  - slug: movie-sub
    status: active
    description: "Sub-matter under movie-x"
    aliases: []
  - slug: defunct
    status: retired
    description: "Retired slug — must not be referenced"
    aliases: []
"""


def build_fixture_vault(tmp_path: Path) -> Path:
    """Create a fixture baker-vault tree under ``tmp_path``.

    Returns the vault root.
    """
    vault = tmp_path / "baker-vault"
    wiki = vault / "wiki"
    wiki.mkdir(parents=True)
    (vault / "slugs.yml").write_text(SLUGS_YML, encoding="utf-8")

    files: dict[str, str] = {
        "wiki/index.md": "---\ntitle: index\n---\n# Index\n",

        # Flat, pre-cutoff (grandfathered): missing _links.md → warn
        "wiki/flat-old/2026-01-10_initial.md": (
            "---\nprimary_matter: flat-old\nrelated_matters: [nested-good]\n---\n"
            "# Flat-old initial note\n\nLink to nested: [[nested-good]].\n"
        ),

        # Flat, post-cutoff: missing _links.md → error
        "wiki/flat-new/2026-04-25_initial.md": (
            "---\nprimary_matter: flat-new\n---\n# Flat-new initial note\n"
        ),

        # Orphan-flat: complete (has _links.md), zero inbound links
        "wiki/orphan-flat/_links.md": "# orphan-flat links\n\n(none)\n",

        # Nested-good: full set + retired-slug reference in _overview.md
        "wiki/matters/nested-good/_index.md": (
            "# nested-good index\n\nSees [[flat-old]] and [[matters/movie-x]].\n"
        ),
        "wiki/matters/nested-good/_overview.md": (
            "# nested-good overview\n\nMentions retired slug: [[defunct]].\n"
        ),
        "wiki/matters/nested-good/gold.md": (
            "# nested-good gold\nStatus ACTIVE. Funding €1.2M.\n"
        ),
        "wiki/matters/nested-good/interactions/2026-04-25_call.md": (
            "# Recent interaction\nToday's call.\n"
        ),

        # Nested-missing: only _overview.md (missing _index + gold) → 2 errors
        "wiki/matters/nested-missing/_overview.md": (
            "# nested-missing overview\n"
        ),

        # movie-x parent + sub-matter
        "wiki/matters/movie-x/_index.md": (
            "# movie-x\nSub: [[matters/movie-x/sub-matters/movie-sub]] and [[matters/nested-good]].\n"
        ),
        "wiki/matters/movie-x/gold.md": "# movie-x gold\n",
        "wiki/matters/movie-x/_overview.md": "# movie-x overview\n",
        "wiki/matters/movie-x/sub-matters/movie-sub/_index.md": (
            "# movie-sub\nBack to parent: [[matters/movie-x]].\n"
        ),
        "wiki/matters/movie-x/sub-matters/movie-sub/gold.md": "# movie-sub gold\n",
        "wiki/matters/movie-x/sub-matters/movie-sub/_overview.md": "# movie-sub overview\n",

        # Inbox: one stuck, one fresh
        "wiki/_inbox/2026-01-01_old-stuck.md": "# Stuck inbox file (>14 days)\n",
        "wiki/_inbox/2026-04-25_fresh.md": "# Fresh inbox file (<14 days)\n",
    }
    for rel, body in files.items():
        target = vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    # Stamp deterministic mtimes.
    pre_cutoff = _epoch(_dt.datetime(2026, 1, 10))
    post_cutoff = _epoch(_dt.datetime(2026, 4, 25))
    old_inbox = _epoch(_dt.datetime(2026, 1, 1))
    fresh_inbox = _epoch(_dt.datetime(2026, 4, 25))

    flat_old_files = [
        "wiki/flat-old/2026-01-10_initial.md",
    ]
    flat_new_files = [
        "wiki/flat-new/2026-04-25_initial.md",
    ]
    for rel in flat_old_files:
        os.utime(vault / rel, (pre_cutoff, pre_cutoff))
    for rel in flat_new_files:
        os.utime(vault / rel, (post_cutoff, post_cutoff))
    os.utime(vault / "wiki/orphan-flat/_links.md", (pre_cutoff, pre_cutoff))
    os.utime(vault / "wiki/_inbox/2026-01-01_old-stuck.md", (old_inbox, old_inbox))
    os.utime(vault / "wiki/_inbox/2026-04-25_fresh.md", (fresh_inbox, fresh_inbox))

    # Recent files for nested-good (so it isn't flagged stale)
    recent = _epoch(_dt.datetime(2026, 4, 25))
    for rel in (
        "wiki/matters/nested-good/_index.md",
        "wiki/matters/nested-good/_overview.md",
        "wiki/matters/nested-good/gold.md",
        "wiki/matters/nested-good/interactions/2026-04-25_call.md",
        "wiki/matters/movie-x/_index.md",
        "wiki/matters/movie-x/gold.md",
        "wiki/matters/movie-x/_overview.md",
        "wiki/matters/movie-x/sub-matters/movie-sub/_index.md",
        "wiki/matters/movie-x/sub-matters/movie-sub/gold.md",
        "wiki/matters/movie-x/sub-matters/movie-sub/_overview.md",
    ):
        os.utime(vault / rel, (recent, recent))

    return vault
