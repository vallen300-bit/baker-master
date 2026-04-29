#!/usr/bin/env python3
"""Regenerate ``hot.md``, ``slugs.yml`` mutations, and per-matter
``proposed-gold.md`` candidates from ``baker-vault/wiki/_priorities.yml``.

Wave-1 Track-5b. Spec: ``baker-vault/_ops/processes/cortex-priorities-schema.md``
(spec_version: 1, ratified 2026-04-29).

Inputs
------
``baker-vault/wiki/_priorities.yml``  — live source-of-truth (Triaga ratifications
write here via Thread 5c).

Outputs (atomic; aborts on validation failure)
----------------------------------------------
1. ``baker-vault/wiki/hot.md``                              — full rewrite
2. ``baker-vault/slugs.yml``                                — adds + retires
3. ``baker-vault/wiki/matters/<slug>/proposed-gold.md``     — append candidates

Idempotence
-----------
Same ``_priorities.yml`` input → byte-identical ``hot.md`` output. Per spec:

* Sort matters within section by importance enum order, then slug alphabetical.
* Strip trailing whitespace per line.
* ``\\n`` line endings.
* The ``generated_at`` frontmatter timestamp is excluded from byte-identity
  compare via the ``generated_at`` override parameter (tests pin it).

Validation
----------
After applying ``slug_changes`` + ``dismissed[].slug_action: retire`` to
``slugs.yml``, the script invokes ``kbl.slug_registry._parse_yaml`` against
the rewritten file. The loader hard-fails on duplicate slug or alias; on
failure the script reverts the in-memory changes, writes ``regen_failed.log``
next to the script, and exits non-zero. (Same loader is what
``scripts/validate_eval_labels.py`` exercises before checking eval rows.)

Drift detection
---------------
If the existing ``hot.md`` differs from regen output (excluding ``generated_at``
+ ``last_regen_at`` lines), regen logs a warning and emits ``regen_diff.log``
beside the script. Used by Wave-2 5d cron to alert Director on manual edits.

CLI
---
::

    python3 scripts/regen_hot_md.py --vault /path/to/baker-vault
    python3 scripts/regen_hot_md.py --vault /path/to/baker-vault --check

``--check`` runs the regen in dry-run mode (no writes) and exits non-zero on
drift. Suitable for CI / scheduled drift-detection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

# Allow "python3 scripts/regen_hot_md.py" from repo root without install.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kbl import slug_registry  # noqa: E402  — late-import after sys.path setup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WHEN_ORDER = ("asap", "urgent", "4w", "not-urgent")
IMPORTANCE_ORDER = ("critical", "high", "medium", "low")
_IMPORTANCE_RANK = {v: i for i, v in enumerate(IMPORTANCE_ORDER)}

# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass
class Matter:
    slugs: list[str]            # always >= 1 entry; primary first
    when: str
    importance: str
    category: str
    triaga_ref: str
    description: str
    notes: list[dict] = field(default_factory=list)

    @property
    def slug_display(self) -> str:
        return " + ".join(self.slugs)

    @property
    def primary(self) -> str:
        return self.slugs[0]

    @property
    def sort_key(self) -> tuple[int, str]:
        # Importance rank ascending = critical first; secondary alpha by primary slug.
        return (_IMPORTANCE_RANK.get(self.importance, len(IMPORTANCE_ORDER)), self.primary)


@dataclass
class RegenResult:
    hot_md: str
    slugs_yml: str
    proposed_gold_appends: list[tuple[str, str]]   # (matter_slug, candidate_id)
    drift_detected: bool
    drift_diff: Optional[str]                      # unified diff if drift
    validation_passed: bool
    validation_error: Optional[str]
    summary: dict[str, Any]


# ---------------------------------------------------------------------------
# Parse _priorities.yml
# ---------------------------------------------------------------------------


def _parse_priorities(text: str) -> dict:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("_priorities.yml: top-level must be a mapping")
    if data.get("schema_version") != 1:
        raise ValueError(
            f"_priorities.yml: schema_version must be 1 (got {data.get('schema_version')!r})"
        )
    if "matters" not in data or not isinstance(data["matters"], list):
        raise ValueError("_priorities.yml: `matters` must be a list")
    return data


def _build_matters(raw_matters: list[dict]) -> list[Matter]:
    out: list[Matter] = []
    for i, raw in enumerate(raw_matters):
        if not isinstance(raw, dict):
            raise ValueError(f"matters[{i}] must be a mapping")
        if "slugs" in raw and "slug" in raw:
            raise ValueError(f"matters[{i}]: use `slug` OR `slugs`, not both")
        if "slugs" in raw:
            slugs = raw["slugs"]
            if not isinstance(slugs, list) or not slugs:
                raise ValueError(f"matters[{i}].slugs must be a non-empty list")
        else:
            slug = raw.get("slug")
            if not isinstance(slug, str) or not slug:
                raise ValueError(f"matters[{i}].slug must be a non-empty string")
            slugs = [slug]
        when = raw.get("when")
        if when not in WHEN_ORDER:
            raise ValueError(
                f"matters[{i}] ({slugs[0]}): when={when!r} not in {WHEN_ORDER}"
            )
        importance = raw.get("importance")
        if importance not in IMPORTANCE_ORDER:
            raise ValueError(
                f"matters[{i}] ({slugs[0]}): importance={importance!r} not in {IMPORTANCE_ORDER}"
            )
        out.append(
            Matter(
                slugs=list(slugs),
                when=when,
                importance=importance,
                category=str(raw.get("category", "")),
                triaga_ref=str(raw.get("triaga_ref", "")),
                description=str(raw.get("description", "")),
                notes=list(raw.get("notes", []) or []),
            )
        )
    return out


# ---------------------------------------------------------------------------
# hot.md rendering
# ---------------------------------------------------------------------------


def _cap(value: str) -> str:
    """Capitalize importance for display: critical → Critical."""
    return value[:1].upper() + value[1:] if value else value


def _bullet_asap(m: Matter) -> str:
    return f"- **{m.slug_display}**: {m.description} ({m.triaga_ref}, {_cap(m.importance)})."


def _bullet_urgent_critical(m: Matter) -> str:
    return f"- **{m.slug_display}**: {m.description} ({m.triaga_ref}, Critical, {m.category})."


def _bullet_urgent_other(m: Matter) -> str:
    return f"- **{m.slug_display}**: {m.description} ({m.triaga_ref}, {_cap(m.importance)}, {m.category})."


def _bullet_4w(m: Matter) -> str:
    return f"- **{m.slug_display}**: {m.description} ({m.triaga_ref}, {_cap(m.importance)}, {m.category})."


def _bullet_not_urgent(m: Matter) -> str:
    return f"- **{m.slug_display}**: {m.description} ({m.triaga_ref}, {_cap(m.importance)})."


def _bullet_dismissed(d: dict) -> str:
    if "slugs" in d:
        slug_disp = " + ".join(d["slugs"])
    else:
        slug_disp = str(d.get("slug", ""))
    triaga = d.get("triaga_ref", "")
    reason = d.get("reason", "")
    return f"- **{slug_disp}** ({triaga}): {reason}"


def render_hot_md(priorities: dict, generated_at: str) -> str:
    matters = _build_matters(priorities["matters"])
    dismissed = list(priorities.get("dismissed", []) or [])
    null_routine = list(priorities.get("null_routine", []) or [])
    not_null_elevate = list(priorities.get("not_null_elevate", []) or [])

    by_when: dict[str, list[Matter]] = {w: [] for w in WHEN_ORDER}
    for m in matters:
        by_when[m.when].append(m)
    for buckets in by_when.values():
        buckets.sort(key=lambda x: x.sort_key)

    asap = by_when["asap"]
    urgent = by_when["urgent"]
    urgent_critical = [m for m in urgent if m.importance == "critical"]
    urgent_other = [m for m in urgent if m.importance != "critical"]
    watch = by_when["4w"]
    not_urgent = by_when["not-urgent"]

    prov = priorities.get("provenance", {}) or {}
    ratified_at_raw = priorities.get("ratified_at", "")
    # yaml.safe_load decodes ISO timestamps to datetime; keep the ISO string form.
    if isinstance(ratified_at_raw, dt.datetime):
        ratified_at = ratified_at_raw.isoformat(timespec="seconds")
    else:
        ratified_at = str(ratified_at_raw)
    ratified_count = prov.get("ratified_count", "")
    active_count = prov.get("active_count", "")
    completed_count = prov.get("completed_count", "")
    dismissed_count = prov.get("dismissed_count", "")

    lines: list[str] = []
    lines.append("---")
    lines.append("title: Current Priorities")
    lines.append("voice: gold")
    lines.append("author: director (regen via scripts/regen_hot_md.py)")
    lines.append("generated_from: wiki/_priorities.yml")
    lines.append(f"ratified_at: {ratified_at}")
    lines.append(f"generated_at: {generated_at}")
    lines.append("---")
    lines.append("")
    lines.append("# Hot — Director-curated priorities cache")
    lines.append("")
    lines.append("<!-- DO NOT EDIT — generated by scripts/regen_hot_md.py from wiki/_priorities.yml. -->")
    lines.append("<!-- Edit _priorities.yml or run a Triaga round; regen rewrites this file. -->")
    lines.append("")
    lines.append(
        "Read by KBL Step 1 triage on every run. Author: Director (via Triaga ratification → _priorities.yml → regen)."
    )
    lines.append("")
    lines.append(
        "Tags in bold are canonical slugs from `slugs.yml`. Multi-tag bullets use `slug1 + slug2` (primary first)."
    )
    lines.append("")
    lines.append(
        f"Last ratified {ratified_at} from {ratified_count}-item Triaga "
        f"({active_count} Active · {completed_count} Completed · {dismissed_count} Dismissed)."
    )
    lines.append("")
    lines.append("## Actively pressing (elevate — ASAP / Urgent)")
    lines.append("")

    lines.extend(_render_bullet_section(f"ASAP ({len(asap)} items)", asap, _bullet_asap))
    lines.extend(
        _render_bullet_section(
            f"Urgent + Critical ({len(urgent_critical)} items)",
            urgent_critical,
            _bullet_urgent_critical,
        )
    )
    lines.extend(
        _render_bullet_section(
            f"Urgent + High ({len(urgent_other)} items)",
            urgent_other,
            _bullet_urgent_other,
        )
    )

    lines.append("## Watch list (elevate on any mention — 4-week horizon)")
    lines.append("")
    if watch:
        for m in watch:
            lines.append(_bullet_4w(m))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append(f"## Not urgent ({len(not_urgent)} items — log + monitor only, do NOT elevate)")
    lines.append("")
    if not_urgent:
        for m in not_urgent:
            lines.append(_bullet_not_urgent(m))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Actively frozen / dismissed (suppress signals on these matters)")
    lines.append("")
    if dismissed:
        for d in dismissed:
            lines.append(_bullet_dismissed(d))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Null / routine (always suppress)")
    lines.append("")
    if null_routine:
        for item in null_routine:
            lines.append(f"- {item}")
    else:
        # Spec calls for 3 baked defaults if yaml omits them.
        lines.append("- Marketing newsletters.")
        lines.append("- Auction invite blasts.")
        lines.append("- Generic event promos (conferences, summits, unrelated training).")
    lines.append("")
    lines.append("**NOT null — always elevate:**")
    lines.append("")
    if not_null_elevate:
        for item in not_null_elevate:
            lines.append(f"- {item}")
    else:
        lines.append("- MIO »OBSERVER« press digest — always read + communicate to Director.")
        lines.append("- Subscription renewal notices — Baker-critical (auto-renewal failure breaks Baker).")
    lines.append("")

    # Strip trailing whitespace per line; ensure '\n' line endings.
    rendered = "\n".join(line.rstrip() for line in lines)
    if not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def _render_bullet_section(title: str, matters: list[Matter], formatter) -> list[str]:
    out = [f"### {title}", ""]
    if matters:
        for m in matters:
            out.append(formatter(m))
    else:
        out.append("(none)")
    out.append("")
    return out


# ---------------------------------------------------------------------------
# slugs.yml mutation (textual surgery to preserve comments)
# ---------------------------------------------------------------------------


_VERSION_LINE_RE = re.compile(r"^version:\s*(\d+)\s*$", re.MULTILINE)
_UPDATED_AT_LINE_RE = re.compile(r"^updated_at:\s*\S+\s*$", re.MULTILINE)


def _slug_block_re(slug: str) -> re.Pattern:
    """Match the YAML block for a single matter entry, anchored on `  - slug: <slug>`.

    Captures the entry up to the next `  - slug:` line or end of `matters:` section
    (heuristic — caller verifies the captured block).
    """
    slug_q = re.escape(slug)
    return re.compile(
        rf"(^  - slug:\s*{slug_q}\s*$\n(?:(?!^  - slug:\s).*\n)*)",
        re.MULTILINE,
    )


def _flip_slug_to_retired(yml: str, slug: str, triaga_ref: str, today: str) -> tuple[str, bool]:
    """Find the matter entry for `slug`, flip status:active → status:retired,
    prepend a RETIRED note to its description. Returns (new_yml, changed).
    """
    block_re = _slug_block_re(slug)
    m = block_re.search(yml)
    if not m:
        return yml, False
    block = m.group(1)
    # Replace status: active → status: retired (only if currently active).
    new_block, n_status = re.subn(
        r"^(\s+status:\s*)active\s*$",
        r"\1retired",
        block,
        count=1,
        flags=re.MULTILINE,
    )
    if n_status == 0:
        # Already retired or different status — no-op.
        return yml, False
    # Prepend RETIRED note to description if not already present.
    retired_note = f"RETIRED {today} per Triaga ({triaga_ref}). "
    desc_re = re.compile(r'^(\s+description:\s*)"([^"]*)"\s*$', re.MULTILINE)
    desc_m = desc_re.search(new_block)
    if desc_m and not desc_m.group(2).startswith("RETIRED "):
        prefix = desc_m.group(1)
        existing = desc_m.group(2)
        new_desc_line = f'{prefix}"{retired_note}{existing}"'
        new_block = desc_re.sub(new_desc_line, new_block, count=1)
    new_yml = yml[: m.start()] + new_block + yml[m.end() :]
    return new_yml, True


def _slug_exists_in_yml(yml: str, slug: str) -> bool:
    return bool(re.search(rf"^  - slug:\s*{re.escape(slug)}\s*$", yml, re.MULTILINE))


def _append_new_slug(
    yml: str,
    slug: str,
    description: str,
    aliases: list[str],
    status: str,
    triaga_ref: str,
    new_version: int,
) -> str:
    """Append a new slug block at the end of the matters list under a
    `# version <N> additions` comment block. Idempotent: if the comment
    block exists, append within it; otherwise create it.
    """
    aliases_yml = ", ".join(f'"{a}"' for a in aliases)
    block_lines = [
        f"  - slug: {slug}",
        f"    status: {status}",
        f'    description: "{description}"',
        f"    aliases: [{aliases_yml}]",
        f"    triaga_ref: {triaga_ref}",
        "",
    ]
    block = "\n".join(block_lines)

    marker = f"# version {new_version} additions"
    if marker in yml:
        # Append the block at the end of the file (after the marker section).
        if yml.endswith("\n"):
            return yml + block
        return yml + "\n" + block
    # Append marker + block at the end of the file.
    sep = "" if yml.endswith("\n") else "\n"
    return yml + sep + f"\n{marker}\n" + block


def apply_slug_changes(
    yml_text: str,
    priorities: dict,
    today: str,
) -> tuple[str, list[dict]]:
    """Apply ``slug_changes`` and ``dismissed[].slug_action`` mutations to
    slugs.yml text. Returns (new_yml, summary_list).

    Bumps ``version:`` only when at least one ``add`` or new ``ensure-exists``
    is applied (retire alone does not bump version per Director convention,
    but updates ``updated_at:``).
    """
    summary: list[dict] = []
    out = yml_text

    # Determine current version + bump candidate.
    cur_version_match = _VERSION_LINE_RE.search(out)
    cur_version = int(cur_version_match.group(1)) if cur_version_match else 1
    new_version = cur_version  # bump only on real adds.

    # Process retires from dismissed[].slug_action.
    for d in priorities.get("dismissed", []) or []:
        if d.get("slug_action") == "retire":
            slug = d.get("slug")
            triaga_ref = d.get("triaga_ref", "")
            if slug:
                out, changed = _flip_slug_to_retired(out, slug, triaga_ref, today)
                summary.append(
                    {"action": "retire", "slug": slug, "from": "dismissed", "applied": changed}
                )

    # Process slug_changes[].
    for ch in priorities.get("slug_changes", []) or []:
        action = ch.get("action")
        slug = ch.get("slug")
        if not slug:
            continue
        if action == "retire":
            triaga_ref = ch.get("triaga_ref", "")
            out, changed = _flip_slug_to_retired(out, slug, triaga_ref, today)
            summary.append(
                {"action": "retire", "slug": slug, "from": "slug_changes", "applied": changed}
            )
        elif action == "add":
            if _slug_exists_in_yml(out, slug):
                summary.append({"action": "add", "slug": slug, "applied": False, "reason": "already exists"})
                continue
            new_version = max(new_version, cur_version + 1)
            out = _append_new_slug(
                out,
                slug=slug,
                description=ch.get("description", ""),
                aliases=list(ch.get("aliases", []) or []),
                status=ch.get("status", "active"),
                triaga_ref=ch.get("triaga_ref", ""),
                new_version=new_version,
            )
            summary.append({"action": "add", "slug": slug, "applied": True})
        elif action == "ensure-exists":
            if _slug_exists_in_yml(out, slug):
                summary.append({"action": "ensure-exists", "slug": slug, "applied": False})
                continue
            new_version = max(new_version, cur_version + 1)
            out = _append_new_slug(
                out,
                slug=slug,
                description=ch.get("description", ""),
                aliases=list(ch.get("aliases", []) or []),
                status=ch.get("status", "active"),
                triaga_ref=ch.get("triaga_ref", ""),
                new_version=new_version,
            )
            summary.append({"action": "ensure-exists", "slug": slug, "applied": True})
        # `rename` deferred — no use cases yet in spec; revisit when one lands.

    # Bump version + updated_at if any structural change.
    any_applied = any(s.get("applied") for s in summary)
    if any_applied:
        if new_version != cur_version:
            out = _VERSION_LINE_RE.sub(f"version: {new_version}", out, count=1)
        out = _UPDATED_AT_LINE_RE.sub(f"updated_at: {today}", out, count=1)

    return out, summary


# ---------------------------------------------------------------------------
# proposed-gold.md append
# ---------------------------------------------------------------------------


_FRONTMATTER_STATUS_RE = re.compile(r"^(status:\s*)\S+\s*$", re.MULTILINE)
_FRONTMATTER_AUDIT_RE = re.compile(r"^(last_audit:\s*)\S+\s*$", re.MULTILINE)


def _candidate_section(note: dict, ratified_at: str, source_inbox: str, triaga_ref: str) -> str:
    cid = note.get("proposed_gold_id", "Gx")
    kind = note.get("kind", "other")
    text = note.get("text", "")
    summary = text.split(".")[0][:80] if text else ""
    pattern_map = {
        "figure-correction": "Cycles referencing the old/incorrect figure",
        "framing": "Cycles using the old framing rather than Director's preferred frame",
        "escalation": "Director-flagged escalation pattern",
        "other": "Director correction (see text)",
    }
    pattern = pattern_map.get(kind, pattern_map["other"])
    expanded = text  # no LLM rewrite at this layer; verbatim Director correction.
    return (
        f"## Candidate {cid} — {kind}: {summary} ({triaga_ref})\n"
        f"\n"
        f"**Pattern:** {pattern}\n"
        f"**Director's correction ({ratified_at}):** \"{text}\"\n"
        f"**Proposed Gold:** {expanded}\n"
        f"**Anchor:** `_priorities.yml` ({triaga_ref}); source export: `{source_inbox}`.\n"
        f"\n"
    )


def _append_to_proposed_gold(
    target_path: Path,
    note: dict,
    ratified_at: str,
    source_inbox: str,
    triaga_ref: str,
    today: str,
) -> bool:
    """Append a candidate to a per-matter proposed-gold.md. Returns True if
    appended (False if candidate id already present, idempotent skip).

    Creates the file with skeleton frontmatter if absent. Flips ``status:
    empty`` → ``status: candidates`` on first append. Updates ``last_audit:``.
    """
    cid = note.get("proposed_gold_id", "Gx")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_path.exists():
        # Bootstrap a minimal proposed-gold.md.
        target_path.write_text(
            "---\n"
            f"title: \"Proposed Gold\"\n"
            f"matter: {target_path.parent.name}\n"
            "type: proposed-gold\n"
            "layer: 2\n"
            "live_state_refs: []\n"
            "owner: \"AI Head\"\n"
            f"last_audit: {today}\n"
            "status: empty\n"
            "---\n\n"
            "# Proposed Gold\n\n"
            "<!-- Candidate patterns awaiting AI Head review + Director sign-off. -->\n\n",
            encoding="utf-8",
        )
    text = target_path.read_text(encoding="utf-8")

    # Idempotence: skip if a section for this candidate id already exists.
    if re.search(rf"^## Candidate {re.escape(cid)} —", text, re.MULTILINE):
        return False

    # Flip status: empty → status: candidates if needed.
    if "status: empty" in text:
        text = _FRONTMATTER_STATUS_RE.sub(r"\1candidates", text, count=1)

    # Update last_audit:.
    text = _FRONTMATTER_AUDIT_RE.sub(rf"\g<1>{today}", text, count=1)

    # Strip the "(Empty — awaits first candidate.)" placeholder if present.
    text = re.sub(r"\n\(Empty — awaits first candidate\.\)\s*\n?", "\n", text)

    # Append candidate.
    if not text.endswith("\n"):
        text += "\n"
    text += "\n" + _candidate_section(note, ratified_at, source_inbox, triaga_ref)

    target_path.write_text(text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def regen_hot_md(
    priorities_path: Path,
    vault_path: Path,
    *,
    write: bool = True,
    generated_at: Optional[str] = None,
    today: Optional[str] = None,
) -> RegenResult:
    """Run the full regen pipeline.

    Parameters
    ----------
    priorities_path
        Path to ``_priorities.yml``.
    vault_path
        Vault root (parent of ``slugs.yml`` + ``wiki/``).
    write
        When False, no files are written; ``RegenResult`` reflects what *would*
        be produced. Used by ``--check`` and tests.
    generated_at
        Override frontmatter timestamp for deterministic tests.
    today
        Override date string for retired-note prefix + last_audit.

    Aborts (raises) on validation failure after slugs.yml mutation.
    """
    today = today or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if generated_at is None:
        generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    priorities_text = priorities_path.read_text(encoding="utf-8")
    priorities = _parse_priorities(priorities_text)

    # 1. Render hot.md.
    new_hot_md = render_hot_md(priorities, generated_at)

    # 2. Apply slugs.yml mutations.
    slugs_yml_path = vault_path / "slugs.yml"
    if not slugs_yml_path.exists():
        raise FileNotFoundError(f"slugs.yml not found at {slugs_yml_path}")
    original_slugs = slugs_yml_path.read_text(encoding="utf-8")
    new_slugs_yml, slug_summary = apply_slug_changes(original_slugs, priorities, today)

    # 3. Drift detection on hot.md.
    hot_md_path = vault_path / "wiki" / "hot.md"
    drift_detected = False
    drift_diff: Optional[str] = None
    if hot_md_path.exists():
        existing = hot_md_path.read_text(encoding="utf-8")
        # Exclude generated_at line from comparison so timestamp doesn't trigger drift.
        if _strip_volatile(existing) != _strip_volatile(new_hot_md):
            drift_detected = True
            drift_diff = _unified_diff_short(existing, new_hot_md)

    # 4. Validation: re-load slugs.yml via kbl.slug_registry loader.
    validation_passed = True
    validation_error: Optional[str] = None
    if write:
        # Write slugs.yml first so loader sees real file; revert on failure.
        slugs_yml_path.write_text(new_slugs_yml, encoding="utf-8")
        try:
            slug_registry._parse_yaml(slugs_yml_path)
        except slug_registry.SlugRegistryError as e:
            # Roll back, write failure log, abort.
            slugs_yml_path.write_text(original_slugs, encoding="utf-8")
            validation_passed = False
            validation_error = str(e)
            log_path = Path(__file__).parent / "regen_failed.log"
            log_path.write_text(
                f"{generated_at}\nslug registry validation failed:\n{e}\n",
                encoding="utf-8",
            )
            return RegenResult(
                hot_md=new_hot_md,
                slugs_yml=original_slugs,
                proposed_gold_appends=[],
                drift_detected=drift_detected,
                drift_diff=drift_diff,
                validation_passed=False,
                validation_error=validation_error,
                summary={"slugs": slug_summary, "aborted": True},
            )
    else:
        # Dry-run: validate against in-memory string by writing to a tmp file.
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False) as tmp:
            tmp.write(new_slugs_yml)
            tmp_path = Path(tmp.name)
        try:
            slug_registry._parse_yaml(tmp_path)
        except slug_registry.SlugRegistryError as e:
            validation_passed = False
            validation_error = str(e)
        finally:
            tmp_path.unlink(missing_ok=True)

    # 5. Apply proposed-gold.md appends.
    appended: list[tuple[str, str]] = []
    matters_dir = vault_path / "wiki" / "matters"
    ratified_at = priorities.get("ratified_at", "")
    source_inbox = (priorities.get("provenance") or {}).get("source_inbox", "")
    if write:
        for raw in priorities["matters"]:
            triaga_ref = raw.get("triaga_ref", "")
            for note in raw.get("notes", []) or []:
                target_rel = note.get("target")
                if not target_rel:
                    continue
                target_path = vault_path / target_rel
                # Sandbox check: never write outside vault/wiki/matters/.
                try:
                    target_path.resolve().relative_to(matters_dir.resolve())
                except ValueError:
                    logger.warning("skipping note: target %s outside matters/", target_rel)
                    continue
                if _append_to_proposed_gold(
                    target_path, note, ratified_at, source_inbox, triaga_ref, today
                ):
                    appended.append((target_path.parent.name, note.get("proposed_gold_id", "Gx")))

    # 6. Write hot.md last (after validation succeeded).
    if write and validation_passed:
        hot_md_path.write_text(new_hot_md, encoding="utf-8")

    # 7. Emit drift log if drift detected (write path only).
    if write and drift_detected and drift_diff:
        log_path = Path(__file__).parent / "regen_diff.log"
        log_path.write_text(
            f"{generated_at}\nhot.md drift detected — manual edit OR regen not run after Triaga round.\n\n{drift_diff}\n",
            encoding="utf-8",
        )

    return RegenResult(
        hot_md=new_hot_md,
        slugs_yml=new_slugs_yml,
        proposed_gold_appends=appended,
        drift_detected=drift_detected,
        drift_diff=drift_diff,
        validation_passed=validation_passed,
        validation_error=validation_error,
        summary={
            "slugs": slug_summary,
            "appended": len(appended),
            "matters_count": len(priorities["matters"]),
        },
    )


def _strip_volatile(text: str) -> str:
    """Drop frontmatter timestamp lines that change every regen."""
    out_lines = []
    for line in text.splitlines():
        if line.startswith("generated_at:") or line.startswith("last_regen_at:"):
            continue
        out_lines.append(line.rstrip())
    return "\n".join(out_lines)


def _unified_diff_short(a: str, b: str, max_lines: int = 60) -> str:
    import difflib
    diff = list(
        difflib.unified_diff(
            a.splitlines(keepends=False),
            b.splitlines(keepends=False),
            fromfile="existing",
            tofile="regen",
            lineterm="",
        )
    )
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... ({len(diff) - max_lines} more lines)"]
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--vault",
        required=True,
        help="Path to baker-vault checkout (parent of slugs.yml + wiki/)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: don't write; exit non-zero on drift or validation failure",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    vault = Path(args.vault).expanduser().resolve()
    priorities_path = vault / "wiki" / "_priorities.yml"
    if not priorities_path.exists():
        print(f"ERROR: _priorities.yml not found at {priorities_path}", file=sys.stderr)
        return 2

    result = regen_hot_md(priorities_path, vault, write=not args.check)

    if not result.validation_passed:
        print(f"ERROR: slug registry validation failed: {result.validation_error}", file=sys.stderr)
        return 3

    if args.check:
        if result.drift_detected:
            print("DRIFT: hot.md does not match regen output", file=sys.stderr)
            print(result.drift_diff or "", file=sys.stderr)
            return 4
        print("OK: no drift; slug registry validates")
        return 0

    print(
        f"OK: hot.md rewritten "
        f"({result.summary['matters_count']} matters); "
        f"slugs.yml mutations: {sum(1 for s in result.summary['slugs'] if s.get('applied'))}; "
        f"proposed-gold appends: {result.summary['appended']}"
    )
    if result.drift_detected:
        print("note: hot.md drift detected (logged to scripts/regen_diff.log)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
