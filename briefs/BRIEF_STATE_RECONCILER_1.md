# BRIEF: STATE_RECONCILER_1 — Phase 1 cortex-config auto-regeneration from authoritative state

## Context

Three drift scars in two weeks (2026-05-10 stale tracker labels, 2026-05-15 Aukera deadline 25-day stale, 2026-05-15 CYCLE_REGISTER 5-day stale → b3 duplicate dispatch) trace to the same root cause: **derived snapshot files (cortex-config.md) drift from authoritative state (curated/06_decisions_log.md, gold.md) because they are hand-rewritten and forgotten.** AID's research note `wiki/_ai-it/aid-t/library/state-architecture-best-practice-2026-05-16.md` recommends a GitOps-style reconciler that auto-regenerates the snapshot layer; Director ratified the architecture on 2026-05-17 (6-Q mapping session). AH1 engineering audit `_ops/reviews/2026-05-17-ah1-engineering-audit-aid-state-architecture-note.md` corrected two BLOCKERS in AID's plan (regenerate-entire-file → agent-writable-region pattern; uniform layout assumption → Phase 1 scoped to 8 canonical-layout matters only).

**This brief = Phase 1.** Adds machine-readable delimiters to 8 canonical-layout cortex-config files, builds a Python reconciler that regenerates the auto-region from `06_decisions_log.md`, fires it via pre-commit hook (in-commit) + nightly cron (level-triggered backstop). Phases 2-4 (cycle register, OPERATING.md, PINNED.md) are separate briefs gated on Phase 1 ship + 2-week observation.

**Companion brief:** BRIEF_STATE_FILE_REFRESH_1 (Option B bridge audit) ships in parallel, covers the 3-4 week build window. Rescoped to a narrower audit role once this brief ships clean.

**Template-schema delegation withdrawn 2026-05-18.** Original Q3 ratification had AID drafting the template-schema in his library. Director ratified withdrawal (bus #389) per captured rule "AID library-doc edits are still AID engineering when edits are implementation specs". **AH1 now authors the template-schema directly as Amendment §0 below**, folding the engineering audit findings (`_ops/reviews/2026-05-17-ah1-engineering-audit-aid-state-architecture-note.md`) plus two further self-audit findings against real decision-log data (D-id format variance; date format variance). The §0 amendment supersedes the old "Step 0: AID template-schema draft (BLOCKING precondition)" gate.

## Estimated time: ~7-8 builder-days
## Complexity: Medium-High
## Prerequisites
- BRIEF_STATE_FILE_REFRESH_1 shipped (it did — PR #212 merged 11c0b18 on 2026-05-17; nightly first fire 2026-05-18 06:00 UTC).
- Director ratification of the agent-writable-region delimiter convention as a fleet-wide pattern (per Q6 mapping session 2026-05-17). The pattern decided once here is reused in Phases 2-4.
- Template-schema authored inline (Amendment §0 below). AH1 self-audited; no AID handoff required.

## API version / deprecation / fallback
- **No external API calls.** Internal filesystem + git operations only.
- Python 3.11+ (matches baker-master `runtime.txt` / `.python-version`).
- PyYAML (already a baker-master dependency; reused for frontmatter parsing).
- `git` CLI (already required by .githooks infrastructure).

---

## Problem statement

22 cortex-config files exist; 8 carry the canonical `curated/06_decisions_log.md` layout (mrci, aukera, lilienmatt, capital-call, annaberg, mo-vie-am, hagenauer-rg7, oskolkov). Director ratifies decisions via HTML Triaga + folds to 06_decisions_log via cascade-back-prop. Cortex-config carries hand-curated Director-tuned frame (game-theoretic horizon, severity_floor, coordination rules, individual-level intel) — none of which is derivable from Layer 1, all of which the reconciler MUST preserve. But cortex-config ALSO carries (or should carry) a "what was ratified recently" digest that today is hand-curated by AH1 during HTML Triaga folds and frequently goes stale (Aukera 25-day-stale incident).

**Solution: split cortex-config into two regions via machine-readable delimiters. Reconciler writes ONLY inside delimiters; hand-curated content outside is preserved verbatim.**

```markdown
---
type: matter
slug: aukera
updated: '2026-05-17'      ← reconciler updates this on every run
schema_version: v1          ← reconciler emits this; agents read it on schema-bump
...
---

# Cortex Per-Matter Brain — Aukera

<!-- AUTO-GENERATED-START: recent-ratifications schema=v1 -->
## Recent ratifications (auto-generated; do not edit)

- **D-211** (2026-05-02) — Skliar + Derkachova €500-588K loan in Aukera Subordination scope
- **D-209** (2026-05-01) — Balgerstrasse leg = oral-only Patrick Züchner; post-Annaberg sequencing
- **D-208** (2026-05-01) — Annaberg TS reserves locked + €30M frame inference corrected
- **D-207** (2026-05-01) — KPMG NOT commissioned; Plan B = Klaus Weipert under Director consideration
- **D-206** (2026-05-01) — Cross-vehicle siloed; ~€2-3M Aukera-consent route = Q12

(Source: curated/06_decisions_log.md. Reconciler last ran 2026-05-17 03:00 UTC.)
<!-- AUTO-GENERATED-END: recent-ratifications -->

## Project ↔ Owner GmbH structure   ← hand-curated; reconciler NEVER touches below this line

[... existing hand-curated content unchanged ...]
```

Reconciler triggers (per Q1 mapping ratified C — both):
1. **Pre-commit hook** in baker-vault `.githooks/state_reconciler.sh` — fires when `wiki/matters/<slug>/curated/06_decisions_log.md` is staged. Regenerates the AUTO-GENERATED region of the same matter's `cortex-config.md`, `git add`s the diff into the same commit. One commit, atomic.
2. **Nightly cron** at 02:30 UTC on Mac Mini — re-renders all 8 matter's auto-regions from current 06_decisions_log content. Self-heals if a commit-hook bypassed the regeneration (force-push, manual revert, etc.).

---

## Current state

- `baker-vault/wiki/matters/<slug>/cortex-config.md` — 22 files, hand-curated, with YAML frontmatter (`updated:`, `slug:`, `default_specialists:`, `severity_floor:`, etc.) + markdown body.
- `baker-vault/wiki/matters/<slug>/curated/06_decisions_log.md` — 8 of 22 matters; canonical format: H2 headings `## D-NNN — <title> (<YYYY-MM-DD>)`.
- `baker-vault/.githooks/cascade_backprop_check.sh` — existing commit-msg hook that blocks commits modifying `06_decisions_log.md` without corresponding Desk LONGTERM/OPERATING updates. **Reconciler must run BEFORE this hook in the git lifecycle (pre-commit, not commit-msg), so the regenerated cortex-config is part of the same atomic commit and the Desk back-prop verification sees the full diff.**
- `baker-vault/.githooks/commit-msg` (wrapper) and similar — existing hooks; reconciler adds a NEW `pre-commit` hook (or extends if one exists).
- Mac Mini long-running worker — currently runs vault-push pipeline + `ai_head_weekly_audit` APScheduler job. Reconciler nightly cron lives here (NOT on Render dynos — they have no baker-vault filesystem).

---

## Amendment §0 — Template-schema (AH1-authored 2026-05-18)

> **Authorship + audit chain:** AH1 authored 2026-05-18 after Director-ratified withdrawal of AID delegation (bus #389). Self-audited against actual decision-log data in 8 Phase 1 matters (mrci, aukera, lilienmatt, capital-call, annaberg, mo-vie-am, hagenauer-rg7, oskolkov). Self-audit surfaced two engineering findings (A1 + A2 below) that REVISE Step 3 implementation; the rest of Step 3 stands. Skepticism rule applied to AH1's own output: this amendment is dispatched to AH2 cross-lane and reviewed under the same standard AID would have faced.

### §0.1 — Region marker syntax (canonical, v1)

Single AUTO-GENERATED region per cortex-config file in Phase 1. Region name: `recent-ratifications`. Marker form (line-anchored):

```
<!-- AUTO-GENERATED-START: recent-ratifications schema=v1 -->
<inner body — see §0.3>
<!-- AUTO-GENERATED-END: recent-ratifications -->
```

Position in the matter cortex-config file: inserted immediately after the first `# <H1 title>` line (after one blank line). Migration in Step 2 places it there once; reconciler thereafter never moves it.

**HTML-comment markers chosen over alternatives** (YAML block, Markdown fences) because: (a) invisible in rendered Markdown for Obsidian / Director eyeball view, (b) survive copy-paste, (c) line-anchored regex finds them reliably without confusion with code fences in surrounding hand-curated content.

### §0.2 — Frontmatter contract (what reconciler may touch)

| Field | Reconciler action | On absence |
|---|---|---|
| `updated:` | OVERWRITE with today's UTC date (`'YYYY-MM-DD'`, single-quoted) | exit 1 (Phase 1 invariant — file must have `updated:`) |
| `schema_version:` | INSERT `v1` if absent; preserve if present | n/a (idempotent) |
| All others (`slug`, `severity_floor`, `default_specialists`, `cycle_timeout_seconds`, `specialist_cap_per_cycle`, `last_curated_at`, ad-hoc Director-tuned keys) | PRESERVE BYTE-FOR-BYTE | n/a — reconciler never reads, only writes the two fields above |

Implementation MUST use surgical line-replacement (anchored regex per field), NOT `yaml.safe_load` + `yaml.safe_dump` round-trip — round-trip reformats quoted strings, normalizes dates, drops comments, and produces cosmetic diffs on hand-tuned fields. The byte-for-byte preservation invariant is only deliverable via surgical edits. (Already correctly implemented in Step 3 `_update_frontmatter_updated_field`; this contract codifies the rule.)

### §0.3 — Region body grammar (v1)

```
## Recent ratifications (auto-generated; do not edit)

- **<id>** (<YYYY-MM-DD>) — <title>
- **<id>** (<YYYY-MM-DD>) — <title>
...

(Source: curated/06_decisions_log.md — see `.reconciler-state.json` for last-run timestamp.)
```

Empty-decisions case (rendered when zero decisions parsed):

```
## Recent ratifications (auto-generated; do not edit)

_No dated ratifications parsed from 06_decisions_log._

(Source: curated/06_decisions_log.md — see `.reconciler-state.json` for last-run timestamp.)
```

The render is a **pure function of `decisions: list[Decision]`** — no `datetime.now()`, no live-clock state, no inputs other than the parsed decision list. Last-run timestamp lives ONLY in `.reconciler-state.json` sidecar, not in the rendered body. Test `TestRender::test_render_is_pure` asserts identical bytes from two renders one hour apart.

### §0.4 — Sort + cap

- **Sort:** date DESC primary; on date tie, **numerically-extracted** D-id DESC tiebreak (parse the integer suffix; `D-12` < `D-211` because `12 < 211` — NOT lex sort which would say `D211 < D2` for un-padded data).
- **Cap:** 8 most recent decisions (`RECENT_RATIFICATIONS_CAP = 8`). Rationale: covers ~last 4-6 weeks of typical ratification cadence; long enough to surface drift, short enough not to dominate the file. Director-tunable post-ship via constant flip in `state_reconciler.py`.

### §0.5 — Decision parser (REVISES Step 3 `_parse_decisions`)

**Self-audit finding A1 (BLOCKER, folded here):** Step 3's `DECISION_HEADING_RE` regex `^##\s+(D-\d+)\s*—\s*(.+?)\s*\((\d{4}-\d{2}-\d{2})\)` requires (a) dashed-padded ID and (b) bare ISO date in parens. Real data violates both — `D-201` vs `D1`, `(2026-04-22)` vs `(Q4 ratified 2026-05-01)` vs `(2026-04-02/03)` vs no date in heading at all (~70% of inspected entries across the 8 matters).

**Revised parser contract (B-code to implement):**

1. **Two heading-ID forms accepted:**
   - Dashed: `^##\s+D-(\d+)\s*[—–-]\s*` (aukera/oskolkov style)
   - Undashed: `^##\s+D(\d+)\s*[—–-]\s*` (annaberg/mo-vie-am style)
   - Strikethrough prefix (e.g. `## ~~D3 — title~~ — SUPERSEDED`) NOT accepted — superseded decisions are excluded from the auto-region by design (they're historical, not "recent ratifications").

2. **Date extraction with three-tier fallback:**
   - **Tier 1 (preferred):** ISO date `\d{4}-\d{2}-\d{2}` anywhere inside the FIRST parenthetical group of the H2 heading line. Examples that MATCH: `(2026-04-22)`, `(Q4 ratified 2026-05-01)`, `(2026-05-02 Q3.5b)`. Examples that do NOT match: `(2026-04-02/03)` (range), no parens at all.
   - **Tier 2 (fallback):** Scan body of the decision (lines between this H2 and the next H2) for the first ISO date `\d{4}-\d{2}-\d{2}` — typically embedded in `**Decision (Director T1, 2026-04-28):**` patterns. Maximum scan: 20 body lines (cap to bound parse cost; decision bodies vary 5-40 lines).
   - **Tier 3 (no date found):** SKIP decision from rendering AND emit a structured log entry `parser_skip:{slug}:{id}:no_date_found`. Layer C audit (BRIEF_STATE_FILE_REFRESH_1) reads this log on next nightly fire and surfaces the count to drift-sentinel ClickUp task — Director sees "N decisions un-parseable" and can patch decision-log headings.

3. **Title extraction:** content between em-dash (`—`, `–`, or `-`) after the ID and the FIRST opening paren `(`, OR end of line if no paren. Strip trailing whitespace. Truncate at 100 chars with ellipsis for render safety.

**Why Tier 1+2 not just strict Tier 1:** strict Tier 1 would surface 0 decisions for 6 of the 8 Phase 1 matters and 2 of 10 for aukera/oskolkov — the auto-region would render empty placeholders almost everywhere. Tier 2 body-fallback recovers ~60-80% of real data (sampled from aukera + annaberg + mo-vie-am inspection). Remaining un-parseable entries (Tier 3 skips) become a *signal* the audit layer surfaces — exactly the drift-detection purpose of this whole brief.

**Test additions (added to Step 6 `TestDecisionParsing`):**
- `test_dashed_id_format` (aukera-shape input)
- `test_undashed_id_format` (annaberg-shape input)
- `test_date_in_first_paren_q_prefix` (`(Q4 ratified 2026-05-01)` → date extracted)
- `test_date_in_body_fallback` (no date in H2, ISO date on `**Decision (... 2026-04-28):**` line in body)
- `test_strikethrough_heading_excluded` (`## ~~D3 — title~~ — SUPERSEDED` → not in output)
- `test_date_range_in_heading_no_match` (`(2026-04-02/03)` → Tier 1 fails, body fallback tried)
- `test_unparseable_decision_skipped_and_logged` (no date anywhere → skipped + log entry emitted)

Test count revision: **22 → 28 tests** (six new cases in `TestDecisionParsing` + existing classes). Ship gate becomes literal `pytest` showing 28 passed.

### §0.6 — Schema-version upgrade rules

- Phase 1 ships `schema=v1`. Reconciler refuses to write to a region marked `schema=vN` where `N > MAX_SUPPORTED`. Currently `MAX_SUPPORTED = 1`. Out-of-range emits structured error `error_schema_too_new` per matter.
- Phase 2+ adds new schemas (`v2` for cycle register, etc.). When a v2 schema lands AND backward-compatible, the reconciler may re-render `v1` regions under `v2` markers automatically. NON-backward-compatible schema bumps require explicit migration step + Director ratification (same pattern as DB migrations).
- Files predating Phase 1 (no `schema_version` in frontmatter, no markers in body) are NOT touched by reconciler — migration step adds the markers + version BEFORE reconciler ever sees the file (Step 2).

### §0.7 — Hook identity / cron identity contract (folds engineering audit Finding 5)

| Surface | Git identity | Cascade-back-prop hook fires? |
|---|---|---|
| Pre-commit reconciler hook (in-commit regeneration) | **Inherits committer's identity** (Baker PL / AH / B-code / Director — whoever ran `git commit`) | YES — runs at commit-msg; reads full staged set including reconciler-added cortex-config |
| Nightly cron reconciler (Mac Mini, 02:30 UTC) | **Distinct fixed identity** `Baker State Reconciler <noreply@brisengroup.com>` (see Step 5 `nightly_cron.sh`) | NO — cron commit message includes `Cascade-backprop-exempt: nightly auto-reconciliation (not a Director ratification)` per cascade-back-prop bypass mechanism |

Rationale: pre-commit identity stays inherited so audit trail attributes the actual ratification author. Cron-side gets a distinct synthetic identity so `git log --author='Baker State Reconciler'` cleanly isolates cron activity from human activity for debugging + drift-sentinel filtering.

### §0.8 — Step 2 migration scope expansion (folds finding A2)

**Self-audit finding A2 (MEDIUM, folded here):** Step 2's migration script as written assumes decision-log headings are already in the canonical `D-NNN (YYYY-MM-DD)` form. Real data shows ~6 of 8 matters use undashed `D1`/`D2` IDs and ~70% of headings lack ISO dates in parens. Without addressing this, Phase 1 ships with most matters rendering near-empty auto-regions on first migration.

**Revised migration in Step 2 (per B-code):**

The migration script also performs a **READ-ONLY survey pass** (no writes) BEFORE running the reconciler on the 8 matters:

```python
def survey_decision_logs(vault_root: Path) -> dict:
    """For each of 8 Phase 1 matters, parse the decisions log with the §0.5
    revised parser and report: (a) total D-headings found, (b) Tier 1 date
    hits, (c) Tier 2 body-fallback hits, (d) Tier 3 skips.

    Output is a markdown table written to /tmp/state_reconciler_survey.md
    for Director review BEFORE the migration commit is staged. If Tier 3
    skips exceed 20% of any matter's total, B-code surfaces to AH1 via
    mailbox UPDATE pre-PR — fold heading canonicalization into migration
    or accept the skip-count.
    """
```

**Director decision gate inside migration (Step 2 ratification surface):**

B-code presents the survey + 8 generated diffs to Director (one paste-block via AH1) before committing the migration. Director ratifies one of two paths:

- **Path A (recommended default):** Accept Tier 3 skips as drift-detection signal. Migration commits the 8 cortex-config files as-is; un-parseable decisions render as a single "**See decisions log directly — N entries un-parseable**" line in the auto-region with the parseable subset above. Ships fast, surfaces gaps as signal.
- **Path B:** Pre-canonicalize 6 affected decision-log files (annaberg, mo-vie-am, mrci, lilienmatt, capital-call, hagenauer-rg7 — survey confirms which) to add ISO dates to headings before migration. Adds ~0.5-1 builder-day; cleaner end-state but the work is hand-curation by AH1 or a desk, not B-code (each decision's true date lives in body context / git history).

**Recommendation: Path A.** Drift-detection IS the point of this brief — leaving the un-parseable signal visible until manually canonicalized is more honest than synthesizing dates from git blame or guessing. Path B can run as a separate cleanup brief post-Phase-1 if Director wants.

### §0.9 — Cap on cap

If a matter has more than `RECENT_RATIFICATIONS_CAP` (=8) parseable decisions in the most recent 30 days, the top 8 by date+id render — older decisions silently drop. This is intentional: the auto-region is "recent ratifications", not the canonical archive (which remains the full 06_decisions_log.md, untouched). Auditors should always cross-read both files.

### §0.10 — Schema spec lock + dispatch gate

This amendment §0 is the **template-schema deliverable** that gated brief dispatch under the original AID-owned plan. With §0 inline + AH1 self-audited + cross-lane AH2 review pending, the brief is dispatch-ready once §0 + the revised Step 6 test plan are Director-ratified.

**Director's ratification surface:** approve §0 + any of §0.8's Path A/B before B-code claims this brief.

**Builder-day delta from amendment:**
- Step 3 parser revision (§0.5): +0.5d
- Step 6 test additions (§0.5): +0.5d
- Step 2 survey pass (§0.8): +0.25d
- **Revised total: ~8 builder-days** (was 7).

---

## Implementation

### Step 0: Template-schema (AH1-authored, see Amendment §0 below — was AID's lane, withdrawn 2026-05-18)

Template-schema is now defined inline as **Amendment §0** below. B-code reads §0 + Step 3 code together; the two are a matched pair (§0 is the contract; Step 3 is the implementation). If §0 and Step 3 disagree, §0 wins — flag the disagreement to AH1 via mailbox UPDATE pre-PR.

**Director ratification of §0 is the gate** that releases this brief for dispatch.

### Step 1: Delimiter convention + schema-version marker (B-code, ~0.5d)

Module: NEW `_ops/reconciler/delimiters.py` in baker-vault.

```python
"""Delimiter convention for agent-writable-region pattern.

Director-ratified 2026-05-17 (Q6 mapping session) as fleet-wide convention.
Reused in Phases 2-4 (cycle register, OPERATING.md, PINNED.md).
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# HTML-comment delimiters chosen because (a) invisible in rendered markdown,
# (b) survive copy-paste, (c) line-anchored regex finds them reliably.
START_PATTERN = re.compile(
    r"^<!--\s*AUTO-GENERATED-START:\s*(?P<region>[a-z0-9-]+)\s+schema=(?P<schema>v\d+)\s*-->\s*$",
    re.MULTILINE,
)
END_PATTERN = re.compile(
    r"^<!--\s*AUTO-GENERATED-END:\s*(?P<region>[a-z0-9-]+)\s*-->\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Region:
    name: str            # e.g., "recent-ratifications"
    schema_version: str  # e.g., "v1"
    start_line: int      # 0-indexed line of START marker
    end_line: int        # 0-indexed line of END marker
    inner_start_offset: int  # char offset of first char AFTER START line newline
    inner_end_offset: int    # char offset of START of END line


def find_regions(text: str) -> list[Region]:
    """Return all AUTO-GENERATED regions in text, sorted by start_line.

    Raises ValueError if a START has no matching END or vice versa, or if
    regions nest or overlap. Reconciler must fail loudly on malformed input.
    """
    starts = list(START_PATTERN.finditer(text))
    ends = list(END_PATTERN.finditer(text))
    if len(starts) != len(ends):
        raise ValueError(f"unbalanced delimiters: {len(starts)} START, {len(ends)} END")
    regions: list[Region] = []
    for s, e in zip(starts, ends):
        if s.group("region") != e.group("region"):
            raise ValueError(
                f"region mismatch: START={s.group('region')} END={e.group('region')}"
            )
        if s.start() >= e.start():
            raise ValueError(f"END before START for region {s.group('region')}")
        # Compute line numbers
        start_line = text[:s.start()].count("\n")
        end_line = text[:e.start()].count("\n")
        regions.append(Region(
            name=s.group("region"),
            schema_version=s.group("schema"),
            start_line=start_line,
            end_line=end_line,
            inner_start_offset=s.end() + 1,  # after START line's newline
            inner_end_offset=e.start(),
        ))
    return regions


def replace_region(text: str, region: Region, new_content: str) -> str:
    """Replace `region`'s inner content with `new_content`. Preserves START/END
    markers verbatim. `new_content` should not include trailing newline (function
    handles separator).

    Bounds-checks `inner_start_offset` and `inner_end_offset` — fail loud on
    out-of-range (e.g., START marker at EOF with no trailing newline).
    code-reviewer 2nd-pass M2.
    """
    if region.inner_start_offset > len(text):
        raise ValueError(
            f"region {region.name!r} START marker has no body (likely at EOF "
            f"with no trailing newline). Fix the source file."
        )
    if region.inner_end_offset > len(text):
        raise ValueError(
            f"region {region.name!r} END marker offset out of range — corrupt input"
        )
    head = text[:region.inner_start_offset]
    tail = text[region.inner_end_offset:]
    # Ensure single newline before END marker
    body = new_content if new_content.endswith("\n") else new_content + "\n"
    return head + body + tail
```

### Step 2: Migrate 8 cortex-config files (B-code, ~1.0d)

Add delimiters to each of:
- `wiki/matters/mrci/cortex-config.md`
- `wiki/matters/aukera/cortex-config.md`
- `wiki/matters/lilienmatt/cortex-config.md`
- `wiki/matters/capital-call/cortex-config.md`
- `wiki/matters/annaberg/cortex-config.md`
- `wiki/matters/mo-vie-am/cortex-config.md`
- `wiki/matters/hagenauer-rg7/cortex-config.md`
- `wiki/matters/oskolkov/cortex-config.md`

**Migration script (do not commit; one-shot operation):** NEW `scripts/migrate_cortex_config_phase1.py` in baker-master that:
1. For each of the 8 matters, opens the file
2. Inserts the AUTO-GENERATED region immediately after the first `# <heading>` line (matter title)
3. Renders the initial auto-content from current 06_decisions_log
4. Writes back atomically (temp + rename)
5. Adds `schema_version: v1` to frontmatter if absent
6. Emits a per-file diff for human review BEFORE writing

**Director ratification gate:** B-code presents the 8 generated diffs to Director (one paste-block) before B-code stages the migration commit. Director ratifies the migration shape; B-code commits.

**The migration commit is the cleanest example of Phase 1 output.** Director's ratification of this single migration commit ratifies the Phase 1 design.

### Step 3: Reconciler module (B-code, ~1.5d)

NEW `_ops/reconciler/state_reconciler.py` in baker-vault.

```python
"""STATE_RECONCILER_1 Phase 1 — cortex-config auto-region regenerator.

Reads curated/06_decisions_log.md per matter, renders the
`recent-ratifications` AUTO-GENERATED region, writes back atomically.

Idempotent: if the inputs haven't changed (computed via input_hash sentinel),
the file is not rewritten. Idempotency is verifiable via `.reconciler-state.json`
per matter.

Triggered by:
  - pre-commit hook (in-commit regeneration on 06_decisions_log change)
  - nightly cron at 02:30 UTC on Mac Mini (level-triggered backstop)

Director-tuned config knobs (top of file, easily editable):
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# Repo-root-relative paths. CLI takes --vault-root override.
DEFAULT_VAULT_ROOT = Path("~/baker-vault").expanduser()
# Phase 1 ratified target list — for `--all` mode safety only. The reconciler
# discovers actual targets dynamically via delimiter presence (see
# `_discover_reconciler_targets`). Hard-coded list is a guardrail against
# accidental Phase 1 over-reach (e.g., a non-canonical matter someone added
# delimiters to before Phase 2 ratification). architect 2nd-pass M1 ratified:
# discovery is the generalizing mechanism; the constant is a Phase-1 fence.
PHASE_1_RATIFIED_MATTERS: frozenset[str] = frozenset({
    "mrci", "aukera", "lilienmatt", "capital-call",
    "annaberg", "mo-vie-am", "hagenauer-rg7", "oskolkov",
})
RECENT_RATIFICATIONS_CAP = 8  # AID-template-schema-ratified
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"v1"})  # architect 2nd-pass M4 — TODO Phase 2 adds v2 upgrade path
# NOTE: Amendment §0.5 SUPERSEDES this single regex with a two-tier parser
# (dashed + undashed IDs, Tier-1 paren-date / Tier-2 body-fallback / Tier-3
# skip-and-log). The original-Step-3 single-regex below is retained for
# implementation-reference context only. B-code: implement per §0.5; the
# single regex below does NOT match ~70% of real decision-log entries and
# would render near-empty auto-regions for most matters.
DECISION_HEADING_RE = re.compile(
    r"^##\s+(D-\d+)\s*—\s*(.+?)\s*\((\d{4}-\d{2}-\d{2})\)"
)


@dataclass
class Decision:
    id: str           # "D-211"
    date: date
    title: str        # everything between em-dash and "(YYYY-MM-DD)"


@dataclass
class ReconcilerState:
    last_run_utc: str
    inputs_hash: str  # hash of (06_decisions_log content)
    schema_version: str = "v1"


def _parse_decisions(decisions_log_text: str) -> list[Decision]:
    """Extract decisions from `## D-NNN — title (YYYY-MM-DD)` headings."""
    out: list[Decision] = []
    for line in decisions_log_text.splitlines():
        m = DECISION_HEADING_RE.match(line)
        if m:
            try:
                d = date.fromisoformat(m.group(3))
            except ValueError:
                continue
            out.append(Decision(id=m.group(1), date=d, title=m.group(2).strip()))
    return out


def _render_recent_ratifications(decisions: list[Decision]) -> str:
    """Render the inner content of the AUTO-GENERATED region.

    Sort: date DESC, id DESC tiebreak. Cap: RECENT_RATIFICATIONS_CAP.

    CRITICAL — must NOT include datetime.now() or any live-clock state in the
    rendered output. The output is keyed by `inputs_hash` (sha256 of
    06_decisions_log) for idempotency; embedding a timestamp would defeat the
    short-circuit and cause spurious daily rewrites. Last-run timestamp lives
    ONLY in `.reconciler-state.json` sidecar (Layer C liveness check via
    BRIEF_STATE_FILE_REFRESH_1 reads the sidecar, not this region).

    Anchor: 2026-05-17 2nd-pass code-reviewer C2 + architect H4.
    """
    sorted_decisions = sorted(
        decisions, key=lambda d: (d.date, d.id), reverse=True
    )[:RECENT_RATIFICATIONS_CAP]

    lines = ["## Recent ratifications (auto-generated; do not edit)", ""]
    if not sorted_decisions:
        lines.append("_No dated ratifications parsed from 06_decisions_log._")
    else:
        for d in sorted_decisions:
            lines.append(f"- **{d.id}** ({d.date.isoformat()}) — {d.title}")
    lines.append("")
    lines.append("(Source: curated/06_decisions_log.md — see `.reconciler-state.json` for last-run timestamp.)")
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically: temp file + os.replace."""
    tmp = path.with_suffix(path.suffix + ".tmp." + os.urandom(4).hex())
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _state_file_path(vault_root: Path, slug: str) -> Path:
    return vault_root / "_ops" / "agents" / "_scanner-state" / f"reconciler-{slug}.json"


def _load_state(path: Path) -> Optional[ReconcilerState]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ReconcilerState(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _save_state(path: Path, state: ReconcilerState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(asdict(state), indent=2))


UPDATED_FIELD_RE = re.compile(
    r"^updated:\s*(?:'[^']*'|\"[^\"]*\"|[^\n]*)$",
    re.MULTILINE,
)
SCHEMA_VERSION_FIELD_RE = re.compile(r"^schema_version:\s*[^\n]+$", re.MULTILINE)


def _update_frontmatter_updated_field(text: str, today: date) -> str:
    """Surgically replace `updated:` line + ensure `schema_version: v1` in
    frontmatter — preserves hand-tuned YAML formatting byte-for-byte on every
    other field.

    Why surgical instead of yaml.safe_load + yaml.safe_dump round-trip:
    yaml.safe_dump reformats quoted strings to unquoted, normalizes dates,
    drops trailing whitespace conventions, and produces cosmetic diffs on
    hand-tuned fields. The Brief 2 Key Constraint "Reconciler does NOT touch
    any frontmatter field other than `updated:` and `schema_version:`" is
    only deliverable via surgical line-replacement.

    Raises ValueError on malformed frontmatter — fail loud, never silently
    produce wrong output.

    Anchor: 2026-05-17 2nd-pass code-reviewer H1.
    """
    if not text.startswith("---"):
        raise ValueError("frontmatter not found (must start with ---)")
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        raise ValueError("frontmatter terminator not found")

    fm_start = 4  # after "---\n"
    fm_end = end_idx  # before "\n---"
    fm_text = text[fm_start:fm_end]

    # Replace updated: line (must exist; raise if absent — matter cortex-config
    # always has an `updated:` field per existing convention).
    new_updated_line = f"updated: '{today.isoformat()}'"
    if UPDATED_FIELD_RE.search(fm_text):
        new_fm = UPDATED_FIELD_RE.sub(new_updated_line, fm_text, count=1)
    else:
        raise ValueError("frontmatter missing `updated:` field — Phase 1 invariant violated")

    # Ensure schema_version: v1 (idempotent — set if absent, leave if present)
    if not SCHEMA_VERSION_FIELD_RE.search(new_fm):
        # Insert immediately after updated: line for stable ordering
        new_fm = UPDATED_FIELD_RE.sub(
            new_updated_line + "\nschema_version: v1", new_fm, count=1
        )

    return text[:fm_start] + new_fm + text[fm_end:]


def reconcile_matter(vault_root: Path, slug: str, dry_run: bool = False) -> dict:
    """Reconcile one matter. Returns a result dict (used in CI dry-run + tests)."""
    from _ops.reconciler.delimiters import find_regions, replace_region

    matter_dir = vault_root / "wiki" / "matters" / slug
    cortex_config = matter_dir / "cortex-config.md"
    decisions_log = matter_dir / "curated" / "06_decisions_log.md"

    if not cortex_config.is_file():
        return {"slug": slug, "status": "skip_no_cortex_config"}
    if not decisions_log.is_file():
        return {"slug": slug, "status": "skip_no_decisions_log"}

    cc_text = cortex_config.read_text(encoding="utf-8")
    dl_text = decisions_log.read_text(encoding="utf-8")

    # Compute input hash for idempotency
    inputs_hash = hashlib.sha256(dl_text.encode("utf-8")).hexdigest()
    state_path = _state_file_path(vault_root, slug)
    state = _load_state(state_path)
    if state and state.inputs_hash == inputs_hash and not dry_run:
        return {"slug": slug, "status": "noop_idempotent"}

    # Find region
    try:
        regions = find_regions(cc_text)
    except ValueError as e:
        return {"slug": slug, "status": "error_malformed_delimiters", "error": str(e)}

    target = next((r for r in regions if r.name == "recent-ratifications"), None)
    if target is None:
        return {"slug": slug, "status": "error_missing_region"}

    # Render new content. Render is a pure function of `decisions` (no live clock).
    decisions = _parse_decisions(dl_text)
    today = datetime.now(timezone.utc).date()
    new_inner = _render_recent_ratifications(decisions)

    # Replace region + update frontmatter
    cc_text_new = replace_region(cc_text, target, new_inner)
    try:
        cc_text_new = _update_frontmatter_updated_field(cc_text_new, today)
    except ValueError as e:
        return {"slug": slug, "status": "error_frontmatter", "error": str(e)}

    if cc_text_new == cc_text:
        # Content identical post-render — bump state but no file write
        if not dry_run:
            _save_state(state_path, ReconcilerState(
                last_run_utc=datetime.now(timezone.utc).isoformat(),
                inputs_hash=inputs_hash,
            ))
        return {"slug": slug, "status": "noop_identical"}

    if dry_run:
        return {
            "slug": slug,
            "status": "would_write",
            "diff_summary": f"region={target.name}, decisions_count={len(decisions)}",
        }

    _atomic_write(cortex_config, cc_text_new)
    _save_state(state_path, ReconcilerState(
        last_run_utc=datetime.now(timezone.utc).isoformat(),
        inputs_hash=inputs_hash,
    ))
    return {"slug": slug, "status": "wrote"}


def _discover_reconciler_targets(vault_root: Path) -> list[str]:
    """Discover matters with AUTO-GENERATED delimiters present in cortex-config.md.

    Replaces a hard-coded matter list with discovery — generalizes to Phase 2-4
    (cycle register, OPERATING.md, PINNED.md) without code change. architect
    2nd-pass M1.

    Phase 1 fence: filtered down to PHASE_1_RATIFIED_MATTERS. If a matter
    outside the ratified set has delimiters (e.g., experimental), it is
    SKIPPED with a warning — guard against accidental Phase 1 over-reach.

    Phase 2 will lift PHASE_1_RATIFIED_MATTERS to a broader fence (e.g.,
    PHASE_2_RATIFIED_TARGETS for cycle_register / agent operating files);
    discovery mechanism remains identical.
    """
    matters_dir = vault_root / "wiki" / "matters"
    if not matters_dir.is_dir():
        return []
    out: list[str] = []
    for matter_dir in sorted(matters_dir.iterdir()):
        if not matter_dir.is_dir() or matter_dir.name.startswith((".", "_")):
            continue
        cortex_config = matter_dir / "cortex-config.md"
        if not cortex_config.is_file():
            continue
        try:
            text = cortex_config.read_text(encoding="utf-8")
        except OSError:
            continue
        if "AUTO-GENERATED-START:" not in text:
            continue
        if matter_dir.name not in PHASE_1_RATIFIED_MATTERS:
            logger.warning(
                "state_reconciler: matter %r has delimiters but is OUTSIDE "
                "Phase 1 ratified set — skipping (add to PHASE_1_RATIFIED_MATTERS "
                "or remove delimiters until Phase 2 lifts the fence)",
                matter_dir.name,
            )
            continue
        out.append(matter_dir.name)
    return out


def reconcile_all(vault_root: Path, dry_run: bool = False) -> list[dict]:
    targets = _discover_reconciler_targets(vault_root)
    return [reconcile_matter(vault_root, s, dry_run) for s in targets]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-root", type=Path, default=DEFAULT_VAULT_ROOT)
    parser.add_argument("--matter", type=str, help="Single matter (default: all 8 Phase 1)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-staged-files", action="store_true",
                        help="Pre-commit hook mode: only reconcile matters whose 06_decisions_log.md is in staged diff")
    args = parser.parse_args()

    if args.from_staged_files:
        # Resolve via `git diff --cached --name-only`
        import subprocess
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], cwd=args.vault_root
        ).decode("utf-8")
        slugs = []
        for line in out.splitlines():
            m = re.match(r"^wiki/matters/([^/]+)/curated/06_decisions_log\.md$", line)
            if m and m.group(1) in PHASE_1_RATIFIED_MATTERS:
                slugs.append(m.group(1))

        # Two-phase: collect all results first, THEN stage. code-reviewer H3 —
        # never leave partial git index state on error. If any reconcile errors,
        # exit 1 without staging anything (transactional semantics).
        results = [reconcile_matter(args.vault_root, s, args.dry_run) for s in slugs]
        any_error = any(r["status"].startswith("error_") for r in results)
        if any_error:
            print(json.dumps(results, indent=2))
            sys.exit(1)

        if not args.dry_run:
            for r in results:
                if r["status"] == "wrote":
                    subprocess.run(
                        ["git", "add", f"wiki/matters/{r['slug']}/cortex-config.md"],
                        cwd=args.vault_root, check=True,
                    )
    elif args.matter:
        results = [reconcile_matter(args.vault_root, args.matter, args.dry_run)]
    else:
        results = reconcile_all(args.vault_root, args.dry_run)

    print(json.dumps(results, indent=2))
    # Exit 0 on success or noop; exit 1 if ANY result has status starting "error_"
    if any(r["status"].startswith("error_") for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### Step 4: Pre-commit hook integration (B-code, ~0.5d)

NEW `.githooks/state_reconciler_pre_commit.sh` in baker-vault:

```bash
#!/usr/bin/env bash
# STATE_RECONCILER_1 — pre-commit reconciler invocation.
#
# Fires when any wiki/matters/<slug>/curated/06_decisions_log.md is staged.
# Regenerates the corresponding cortex-config.md AUTO-GENERATED region(s)
# and stages the diff into the same commit.
#
# Failure semantics: exit 0 on success or noop; exit 1 if reconciler raises
# (malformed delimiters, frontmatter parse error). exit 1 blocks the commit
# so the underlying issue surfaces — never silently produce wrong output.
#
# Skip mechanism: env-var `STATE_RECONCILER_SKIP=1 git commit ...`.
# Why env-var and NOT a commit-msg trailer: pre-commit stage runs BEFORE the
# commit message is finalized; the trailer is unreadable at this stage. This
# is the same scar that drove cascade-back-prop to commit-msg stage (see
# feedback_chanda_4_hook_stage_bug.md + cascade_backprop_check.sh:11). We
# keep the reconciler at pre-commit (so it can modify staged set in-commit)
# and use env-var bypass — same precedent as BAKER_MIGRATION_EDIT_AUTHORIZED.
#
# Anchor: 2026-05-17 2nd-pass code-reviewer H2 + architect H1.
set -euo pipefail

# Env-var bypass for emergencies (recovery commits, partial-state remediation).
# Director-ratifiable on per-incident basis; never on standing usage.
if [ "${STATE_RECONCILER_SKIP:-}" = "1" ]; then
    echo "WARN [state-reconciler]: STATE_RECONCILER_SKIP=1 set — skipping regeneration." >&2
    exit 0
fi

VAULT_ROOT="$(git rev-parse --show-toplevel)"

# Quick filter: any decisions_log in staged diff?
STAGED_DECISIONS=$(git diff --cached --name-only \
    | grep -E '^wiki/matters/[^/]+/curated/06_decisions_log\.md$' \
    || true)
[ -z "$STAGED_DECISIONS" ] && exit 0

# Invoke reconciler in staged-files mode. Use the same Python interpreter that
# has PyYAML — DO NOT rely on /usr/bin/python3 (system Python lacks deps).
# Resolution: prefer .venv if present in vault repo; fall back to whichever
# python3 is first on PATH (Homebrew or pyenv typically). The systemd / cron
# wrapper sets PATH explicitly; the pre-commit hook inherits the committer's
# shell PATH which has the venv activated.
PYTHON="${BAKER_RECONCILER_PYTHON:-python3}"
if ! "$PYTHON" -c "import yaml" 2>/dev/null; then
    echo "ERROR [state-reconciler]: $PYTHON does not have PyYAML installed." >&2
    echo "  Set BAKER_RECONCILER_PYTHON to a python with PyYAML, or activate the venv first." >&2
    exit 1
fi

if ! "$PYTHON" "$VAULT_ROOT/_ops/reconciler/state_reconciler.py" \
    --vault-root "$VAULT_ROOT" \
    --from-staged-files; then
    echo "ERROR [state-reconciler]: regeneration failed for staged decisions_log change." >&2
    echo "  Inspect output above; fix cortex-config or 06_decisions_log shape." >&2
    echo "  Emergency bypass: rerun with 'STATE_RECONCILER_SKIP=1 git commit ...'" >&2
    exit 1
fi

exit 0
```

**Composition with `cascade_backprop_check.sh` (architect 2nd-pass H2 — explicit clarification):**

This reconciler hook runs at **pre-commit** stage. `cascade_backprop_check.sh` runs at **commit-msg**. Order: pre-commit (reconciler regenerates + stages cortex-config) → commit-msg (cascade-back-prop reads full staged set, validates Desk back-prop).

**Critical:** the reconciler's auto-staged `cortex-config.md` change does NOT satisfy cascade-back-prop's Desk back-prop invariant. `cortex-config.md` is a **per-matter** file, not a **per-desk** runtime file. Per `_ops/agents/_desk-matter-map.yml`, the back-prop check requires `_ops/agents/<desk>/{LONGTERM,OPERATING}.md` updates — cortex-config does not count.

This is correct behavior — but the brief author asserts it as a property, not a hope:

**Test case (added to Step 6, `TestPreCommitMode`):**
```python
def test_decisions_log_only_commit_still_blocked_by_cascade_back_prop(
    synth_git_repo, monkeypatch
):
    """A commit editing ONLY 06_decisions_log.md should: (a) trigger reconciler
    auto-staging of cortex-config.md, (b) still be blocked by cascade-back-prop
    because no Desk runtime file is in the staged set.

    Verifies that the reconciler does NOT inadvertently satisfy cascade-back-prop.
    """
    # ... (test body: stage decisions_log, run pre-commit hook, run commit-msg hook,
    # assert commit-msg hook exits 1 with cascade-back-prop error mentioning the
    # missing Desk runtime file)
```

MODIFY `.githooks/pre-commit` (or create if it doesn't exist) — wire the script in. **B-code: grep `.githooks/` for existing pre-commit content first; preserve existing checks; add reconciler invocation at end.**

### Step 5: Nightly cron on Mac Mini (B-code, ~0.5d — wrapper + LaunchAgent spec)

Mac Mini LaunchAgent runs at 02:30 UTC daily. Wrapper script handles: skip-if-dirty,
heartbeat write, bus-post on failure. AH1 installs the LaunchAgent post-merge as Tier-B.

**NEW** `_ops/reconciler/nightly_cron.sh` (in baker-vault):

```bash
#!/usr/bin/env bash
# STATE_RECONCILER_1 — nightly Mac Mini cron wrapper.
#
# Invoked by LaunchAgent at 02:30 UTC daily. Refuses to run on dirty checkout
# (avoids interleaving cron writes with in-flight human commits). Writes
# heartbeat sidecar on every successful run (Layer B audits the heartbeat
# via BRIEF_STATE_FILE_REFRESH_1 — closes the Mac-Mini-SPOF hole architect 2nd-pass H3).
#
# Failure path: bus-posts to `lead` so AH1 sees the silent-cron-failure on
# next session-start drain. Anchor: architect 2nd-pass H3 + M3.
set -euo pipefail

VAULT_ROOT="/Users/dimitry/baker-vault"
LOG="/var/log/baker/state_reconciler.log"
HEARTBEAT="$VAULT_ROOT/_ops/agents/_scanner-state/reconciler-heartbeat.json"
PYTHON="${BAKER_RECONCILER_PYTHON:-/Users/dimitry/Desktop/baker-code/.venv/bin/python3}"
# Distinct identity so `git log --author` filters cleanly. NOT the Director's
# personal identity; NOT shared with B-code or AH commits.
export GIT_AUTHOR_NAME="Baker State Reconciler"
export GIT_AUTHOR_EMAIL="noreply@brisengroup.com"
export GIT_COMMITTER_NAME="Baker State Reconciler"
export GIT_COMMITTER_EMAIL="noreply@brisengroup.com"

mkdir -p "$(dirname "$LOG")"
mkdir -p "$(dirname "$HEARTBEAT")"

exec >>"$LOG" 2>&1
echo "[$(date -u +%FT%TZ)] state_reconciler nightly fire"

cd "$VAULT_ROOT"

# Skip-if-dirty (architect 2nd-pass H5). Cron must never race a human commit.
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "[skip] working tree dirty — abort cron run + emit warning bus-post."
    if [ -x "$HOME/Desktop/baker-code/scripts/bus_post.sh" ]; then
        BAKER_ROLE=cortex "$HOME/Desktop/baker-code/scripts/bus_post.sh" lead \
            "state_reconciler nightly cron SKIPPED: vault working tree dirty at $(date -u +%FT%TZ). Investigate; re-run via launchctl kickstart once clean." \
            "ops/state-reconciler-cron" || true
    fi
    exit 0
fi

# Pull latest before reconciling (avoid re-rendering against stale Layer 1)
git fetch origin main --quiet
git reset --hard origin/main --quiet

# Run reconciler in --all mode (no --from-staged-files for cron)
if ! "$PYTHON" _ops/reconciler/state_reconciler.py --vault-root . ; then
    echo "[error] reconciler exited non-zero"
    if [ -x "$HOME/Desktop/baker-code/scripts/bus_post.sh" ]; then
        BAKER_ROLE=cortex "$HOME/Desktop/baker-code/scripts/bus_post.sh" lead \
            "state_reconciler nightly cron FAILED at $(date -u +%FT%TZ). Check $LOG tail for details. Drift detection partially regressed until investigated." \
            "ops/state-reconciler-cron" || true
    fi
    exit 1
fi

# Commit + push if anything changed
if ! git diff --quiet; then
    git add -A wiki/matters/*/cortex-config.md _ops/agents/_scanner-state/
    git commit -m "auto(state-reconciler): nightly regenerate from 06_decisions_log

Identity: Baker State Reconciler (cron, $(date -u +%FT%TZ))
Cascade-backprop-exempt: nightly auto-reconciliation (not a Director ratification)
"
    git push origin main --quiet
    echo "[committed] auto-reconcile push complete"
else
    echo "[noop] no diff to commit"
fi

# Heartbeat write (atomic). Layer B (BRIEF_STATE_FILE_REFRESH_1) reads this.
TMP="$HEARTBEAT.tmp.$$"
cat > "$TMP" <<EOF
{
  "last_run_utc": "$(date -u +%FT%TZ)",
  "status": "ok"
}
EOF
mv -f "$TMP" "$HEARTBEAT"
echo "[$(date -u +%FT%TZ)] heartbeat written"
```

**LaunchAgent spec** (`~/Library/Application Support/baker/com.baker.state-reconciler.plist` per Lesson #52 — NOT under `~/Desktop/`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.baker.state-reconciler</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/Users/dimitry/baker-vault/_ops/reconciler/nightly_cron.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>2</integer>
    <key>Minute</key><integer>30</integer>
  </dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>/var/log/baker/state_reconciler.launchd.log</string>
  <key>StandardErrorPath</key><string>/var/log/baker/state_reconciler.launchd.err</string>
</dict>
</plist>
```

**B-code writes the wrapper + plist; AH1 installs as Tier-B action post-merge:**

```bash
launchctl load -w ~/Library/Application\ Support/baker/com.baker.state-reconciler.plist
# Smoke test:
launchctl kickstart -k gui/$(id -u)/com.baker.state-reconciler
tail -100 /var/log/baker/state_reconciler.log
```

**Note: cascade-back-prop bypass marker on cron commits.** The auto-commit
message includes `Cascade-backprop-exempt: nightly auto-reconciliation
(not a Director ratification)` so the existing cascade-back-prop hook does
not block the cron-driven commit (cron is not Director-ratifying anything,
just regenerating Layer 2). This uses cascade-back-prop's documented bypass
mechanism per `cascade_backprop_check.sh:14`.

### Step 6: Tests (B-code, ~1.0d)

NEW `tests/test_state_reconciler.py` (lives in baker-vault so tests run with the code they test). Test classes:

1. **`TestDelimiters`** — `find_regions` happy path, mismatched START/END, nested raises, no regions returns [], `replace_region` preserves markers, **bounds-check raises ValueError on START at EOF with no body** (code-rev M2).
2. **`TestDecisionParsing`** — happy path 5 decisions, malformed dates skipped, no decisions returns [], non-D-NNN headings ignored.
3. **`TestRender`** — sort newest first, cap at 8, empty list renders placeholder, **rendered output is a pure function of decisions (no live clock state — assert two renders 1 hour apart produce identical bytes)** (code-rev C2 + architect H4).
4. **`TestReconcileMatter`** — synthetic vault layout, happy path writes file, idempotent re-run is noop, missing decisions_log skips cleanly, malformed delimiters returns error status, **two consecutive runs with no input change produce zero file diff** (idempotency end-to-end).
5. **`TestPreCommitMode`** — synthetic git repo, staged decisions_log change triggers regen, NOT staged → no-op, reconciler `--from-staged-files` re-stages cortex-config, **error in one matter leaves zero files staged** (code-rev H3 transactional semantics), **decisions-log-only commit still blocked by cascade-back-prop despite reconciler regenerating cortex-config** (architect H2).
6. **`TestFrontmatterUpdate`** — updated field set, schema_version added if absent, **all other hand-tuned fields preserved byte-for-byte** (code-rev H1 surgical-replacement test: quoting style preserved, date strings stay quoted strings, severity_floor comment preserved), raises on missing frontmatter, raises on missing `updated:` field.
7. **`TestAtomicity`** — concurrent invocations on same matter don't corrupt file (uses `multiprocessing` 2x runner on same target; assert final state is one or the other, never partial).
8. **`TestMigrationRoundtrip`** (NEW — architect M2) — for each of 8 Phase 1 matters, parse pre-migration cortex-config, run migration script, parse post-migration cortex-config; assert: (a) frontmatter hand-fields preserved byte-for-byte except `updated:` + new `schema_version:`, (b) hand-curated body (outside delimiter region) byte-for-byte equal to pre-migration body. Catches Step 2 regressions deterministically.

**Ship gate: 28 tests pass on literal `pytest` output. Not "by inspection."** (Bumped from 18 → 22 in 2nd-pass review; further bumped to 28 in Amendment §0.5 for the six new `TestDecisionParsing` cases covering format variance.)

### Step 7: Dual-write check (B-code, ~0.5d) — pre-push hook (NOT GitHub Actions)

**Architect 2nd-pass M5 + code-rev M5:** baker-vault is the canonical markdown repo per
project CLAUDE.md ("No GitHub Actions; Render is single deploy path"). The CLAUDE.md
statement is about baker-master, but baker-vault doesn't have Actions wired either —
B-code MUST verify before committing this step:

```bash
# Pre-step verification — REQUIRED before Step 7 implementation
test -d /Users/dimitry/baker-vault/.github/workflows && echo "ACTIONS WIRED" || echo "NO ACTIONS — use pre-push hook"
```

If Actions are NOT wired (expected): implement as a **pre-push hook** in `.githooks/pre-push`:

```bash
#!/usr/bin/env bash
# STATE_RECONCILER_1 — pre-push dual-write drift check.
# Runs `state_reconciler --dry-run` before push; non-zero diff = WARNING (not block).
set -euo pipefail
VAULT_ROOT="$(git rev-parse --show-toplevel)"
PYTHON="${BAKER_RECONCILER_PYTHON:-python3}"
if [ -f "$VAULT_ROOT/_ops/reconciler/state_reconciler.py" ]; then
    DRY_OUT=$("$PYTHON" "$VAULT_ROOT/_ops/reconciler/state_reconciler.py" --vault-root "$VAULT_ROOT" --dry-run)
    if echo "$DRY_OUT" | grep -q '"status": "would_write"'; then
        echo "WARN [state-reconciler]: dry-run shows differences from current committed state:" >&2
        echo "$DRY_OUT" >&2
        echo "Push proceeds (warning, not block). Run reconciler locally OR let nightly cron rebase." >&2
    fi
fi
exit 0
```

If Actions ARE wired (unexpected): use the original GitHub Actions workflow at `.github/workflows/state-reconciler-drift.yml` — same semantics, different surface. B-code picks based on the pre-step probe.

### Step 8: Documentation (B-code, ~0.5d)

NEW `_ops/reconciler/README.md`:
- Delimiter convention (link to AID's template-schema doc)
- Hook invocation order (pre-commit, then commit-msg cascade-back-prop, then commit)
- Bypass trailer (`State-reconciler-exempt:`)
- Nightly cron config
- Troubleshooting (malformed frontmatter, missing region, etc.)

MODIFY baker-vault root `README.md` — add link to `_ops/reconciler/README.md` under existing Hooks section.

---

## Key constraints (what NOT to change)

- **Hand-curated content is sacred.** Reconciler writes ONLY inside AUTO-GENERATED delimiters. Any change to outside-delimiter content = catastrophic regression. Tests assert byte-for-byte preservation of pre/post-region content.
- **No frontmatter field added or removed beyond `updated:` and `schema_version:`.** Director-tuned fields (`severity_floor`, `specialist_cap_per_cycle`, etc.) are preserved verbatim. **Reconciler does NOT touch any frontmatter field other than `updated:` and `schema_version:`.** Hand-tuned values stay hand-tuned.
- **14 non-canonical matters untouched.** This brief covers Phase 1 = 8 canonical matters only. The other 14 stay manual.
- **No baker-master code changes.** This brief is baker-vault-only (reconciler + hook + tests). Baker-master may consume the reconciled cortex-config via existing read paths.
- **Pre-commit hook must NOT fire on non-decisions_log commits.** Filter at the top of the bash script; do not invoke Python if no relevant files staged.
- **Failure is loud.** Malformed delimiters / missing region / frontmatter parse error → exit 1 + block commit. Never silently produce wrong output (Mnilax rule: "fail loud").

---

## Verification

### Local pytest (ship-gate)

```bash
cd /Users/dimitry/baker-vault
pytest tests/test_state_reconciler.py -v
```

**Expected: 28 passed.** (8 test classes per Step 6; the 22 from 2nd-pass review + 6 added in Amendment §0.5 for decision-parser format variance. Ship-report MUST include actual pytest output, not "by inspection".)

### Dry-run on actual 8 matters

```bash
cd /Users/dimitry/baker-vault
python3 _ops/reconciler/state_reconciler.py --vault-root . --dry-run
```

Expected output: 8 JSON results. Each `status` ∈ {`would_write`, `noop_identical`, `noop_idempotent`}. Zero `error_*` statuses. AH1 reviews the implied diff (via `--dry-run` printing) BEFORE B-code runs without `--dry-run`.

### Migration commit verification (Director gate)

B-code generates the 8-matter migration diff, pastes to Director for ratification BEFORE committing. Director ratifies = commit goes in.

### Pre-commit hook verification (synthetic test)

```bash
cd /tmp && git clone ~/baker-vault test-vault && cd test-vault
# Make a synthetic decision in aukera
echo "## D-999 — synthetic test (2026-05-17)" >> wiki/matters/aukera/curated/06_decisions_log.md
git add wiki/matters/aukera/curated/06_decisions_log.md
git commit -m "test: trigger reconciler"
# Hook should auto-stage aukera/cortex-config.md with D-999 in the recent-ratifications region
git show --stat HEAD  # confirm both files committed
git show HEAD:wiki/matters/aukera/cortex-config.md | grep "D-999"  # confirm rendered
```

### First nightly cron fire verification

After AH1 installs the LaunchAgent on Mac Mini:

```bash
# Manual fire (don't wait for 02:30)
launchctl kickstart -k gui/$(id -u)/com.baker.state-reconciler
# Confirm log entry
tail -50 /var/log/baker/state_reconciler.log
# Confirm a baker-vault commit if anything changed (or "noop" message if not)
cd ~/baker-vault && git log --oneline -5
```

### Production verification — Aukera 25-day-stale failure mode

After Phase 1 ships, simulate the original failure mode:
1. Director ratifies a new aukera decision via HTML Triaga.
2. Fold to `aukera/curated/06_decisions_log.md` via existing cascade-back-prop flow.
3. Confirm in same commit that `aukera/cortex-config.md` updated:
   - `updated:` field == today.
   - Recent-ratifications region includes the new D-NNN.
4. AH1 reads `aukera/cortex-config.md`. Drift = zero. Failure mode = closed.

---

## Files Modified

baker-vault (this brief's scope):
- **NEW** `_ops/reconciler/delimiters.py` — delimiter convention + region finder/replacer
- **NEW** `_ops/reconciler/state_reconciler.py` — Phase 1 reconciler (cortex-config)
- **NEW** `_ops/reconciler/nightly_cron.sh` — Mac Mini wrapper (skip-if-dirty, heartbeat, bus-post on fail)
- **NEW** `_ops/reconciler/README.md` — operational docs + bypass + cron config
- **NEW** `.githooks/state_reconciler_pre_commit.sh` — pre-commit invocation (env-var bypass)
- **MODIFY** `.githooks/pre-commit` (or create) — wire reconciler in
- **NEW** `.githooks/pre-push` (or extend) — dry-run drift warning
- **NEW** `tests/test_state_reconciler.py` — 28 tests across 8 test classes
- **MODIFY** 8 cortex-config files (migration step — adds delimiters + schema_version; preserves all hand-curated content)
- **MODIFY** root `README.md` — link to reconciler README

Mac Mini host config (AH1 installs post-merge as Tier-B action; NOT in baker-vault commit):
- `~/Library/Application Support/baker/com.baker.state-reconciler.plist` — LaunchAgent (Lesson #52: NOT under `~/Desktop/`)

baker-master: **no changes.** Reconciler lives in baker-vault.

baker-master: **no changes.** Reconciler lives in baker-vault.

## Do NOT Touch

- 14 non-canonical-layout cortex-config files (movie, kitz, brisen-pr, claimsmax, brisen-funding, baker-internal, cap-ferrat, constantinos, franck-muller, kitzbuhel-six-senses, m365, mo-vie-exit, nvidia-corinthia, personal, uk-homes) — separate brief, separate scope.
- `.githooks/cascade_backprop_check.sh` — works as-is. Reconciler runs at pre-commit, cascade-back-prop at commit-msg. They compose; reconciler's regenerated cortex-config becomes part of the staged change set that cascade-back-prop sees.
- Frontmatter fields other than `updated:` and `schema_version:` — Director-tuned, hand-owned.
- Phase 2-4 file types (CYCLE_REGISTER.md, OPERATING.md, PINNED.md) — separate briefs, post-Phase-1 observation.
- AID's library files — AH1 reads AID's template-schema draft, audits, but does NOT edit AID's library directly (cross-agent dispatch rule).

## Quality Checkpoints

1. Pytest passes literal `28/28` — not "by inspection" (Lesson #8).
2. Hand-curated content byte-for-byte preserved across reconciliation (tests assert).
3. Pre-commit hook only fires on relevant staged files (no perf hit on unrelated commits).
4. Failure modes (malformed delimiters, missing region, frontmatter parse fail) exit 1, block commit, emit human-readable error pointing to the bypass trailer.
5. Idempotency: reconciler re-run with no input change is a no-op (state file confirms).
6. Atomicity: temp + os.replace pattern used for ALL file writes (cortex-config, state file).
7. Dual-write CI passes on the migration PR itself (`--dry-run` should report `noop_identical` for all 8 matters after migration).
8. AH1 engineering-audited AID's template-schema draft BEFORE B-code started Step 1 (skepticism rule).
9. Director ratified the 8-matter migration diff BEFORE B-code committed Step 2.
10. Mac Mini LaunchAgent installed under `~/Library/Application Support/baker/` per Lesson #52 (NOT `~/Desktop/`).

## Verification (Lesson #41 — external state)

Brief lives in baker-vault (external to baker-master). Pre-merge:

```bash
# Confirm baker-vault head clean (no uncommitted state)
cd /Users/dimitry/baker-vault && git status --short
# Expected: empty (or only files this brief is modifying)

# Confirm 8 target matters exist + have 06_decisions_log.md
for m in mrci aukera lilienmatt capital-call annaberg mo-vie-am hagenauer-rg7 oskolkov; do
    test -f wiki/matters/$m/cortex-config.md && \
    test -f wiki/matters/$m/curated/06_decisions_log.md && \
    echo "OK: $m" || echo "MISSING: $m"
done
# Expected: all 8 OK

# Confirm Mac Mini reachable (cron host)
ssh macmini "echo OK"

# Confirm AID's template-schema draft is in place + AH1-audited
test -f wiki/_ai-it/aid-t/library/state-reconciler-template-schema-cortex-config.md && echo OK
test -f _ops/reviews/2026-05-XX-ah1-engineering-audit-aid-state-reconciler-template-schema.md && echo OK
```

---

## Risk Register

### Risks I've designed against (with mitigations in code/brief)

1. **Reconciler bug propagates to all 8 cortex-config files** — Mitigations: extensive tests (18); dry-run CI on every PR; AH1 reviews dry-run output before any non-dry-run runs; Layer A read-time discipline; Layer B (Option B brief) detects post-fact.
2. **Hand-curated content destruction** — Mitigations: byte-for-byte preservation tests; delimiters required (no implicit region detection); reconciler exits 1 if region not found.
3. **Frontmatter field corruption** — Mitigation: reconciler only writes `updated:` + `schema_version:`; other fields round-tripped via `yaml.safe_load` + `yaml.safe_dump` with `sort_keys=False`.
4. **Atomicity / partial-write** — Mitigation: temp file + `os.replace` for all writes (POSIX atomic).
5. **Pre-commit hook performance** — Mitigation: bash-level filter (no Python invocation unless decisions_log staged); reconciler `--from-staged-files` only loads affected matters.
6. **Concurrent invocations (hook + cron near-collision)** — Mitigation: idempotency via `inputs_hash`. If hook ran first, cron is a no-op. If cron raced first, hook still works on its own staged content.
7. **Hook stage interaction with cascade-back-prop** — Mitigation: reconciler at pre-commit (modifies staged set); cascade-back-prop at commit-msg (reads staged set). They compose; reconciler's outputs land in the staged set before cascade-back-prop reads it.
8. **AID template-schema disagreement post-audit** — Mitigation: AH1 engineering-audits AID's draft FIRST (skepticism rule). Disagreements surfaced to Director before B-code begins. Block on Director re-ratification if needed.

### Open risks for Director to consider

9. **Director re-tunes the 8-decision cap** — If 8 decisions/matter is wrong (too many, too few), constant `RECENT_RATIFICATIONS_CAP` flips in module. Trivial change post-ship.
10. **Phase 2 scope (CYCLE_REGISTER) may obsolete itself via Postgres migration** — Q5 mapping session ratified DEFER on this; Phase 1 ships independent. No blocking risk for Phase 1.
11. **Render-side dynos cannot run this** — Confirmed: reconciler ONLY runs on Mac Mini (cron) + locally (pre-commit). Render dynos have no baker-vault filesystem. This is the right design; documented in README.

---

## Sunset / sequencing into Phase 2-4

When Phase 1 cortex-config reconciler observed clean for 2 weeks:
- BRIEF_STATE_FILE_REFRESH_1 (Option B bridge) rescopes from 2-day full refresh → 0.5-1 day audit-only (per AH1 engineering audit).
- Phase 2 brief (CYCLE_REGISTER.md) drafted — extends delimiter convention to cycle register file. AID's template-schema lane covers it.
- Phase 3 brief (OPERATING.md split) — fleet-wide pattern ratified per Q6, rollout begins with AID's own OPERATING.md (dogfood).
- Phase 4 (PINNED.md headers) — last phase, smallest scope.

Phase 1 establishes the delimiter convention, the reconciler skeleton, the hook/cron pattern. Phases 2-4 reuse 80%+ of Phase 1 infrastructure.

---

## Done when

- [ ] AID template-schema draft committed + AH1 engineering-audited.
- [ ] Migration commit ratified by Director + landed (8 cortex-config files have delimiters + schema_version, hand-curated content preserved byte-for-byte).
- [ ] Reconciler module committed, 28 tests green (literal pytest).
- [ ] Pre-commit hook live in `.githooks/`.
- [ ] Mac Mini LaunchAgent installed (AH1-A1 Tier-B action post-merge).
- [ ] First nightly fire produces clean run (no error statuses).
- [ ] Synthetic Aukera-class drift verification (D-999 fold → cortex-config auto-updates) passes.
- [ ] PINNED §M updated: Phase 1 live + 2-week observation window opens.
