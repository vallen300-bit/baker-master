---
brief: CORTEX_PHASE6_REFLECTOR_1
status: DRAFT — candidate for AI Head 1 sequencing
revision: v1 (author-time draft, simplification preamble §0)
authored_by: AI Head A (CLI)
authored_at: 2026-04-30
estimated_time: ~5-7h (incl. tests + dry-run on real cycle)
complexity: Medium-High (touches Phase 4 prompt + new Phase 6 module + vault write; ClickUp infrastructure ships dormant per Brief 5 deferral)
trigger_class: TIER A — modifies Phase 4 propose-phase prompt + adds new phase + new external write surface (ClickUp via Brief 5 contract). Pre-merge: AI Head B cross-lane review per `_ops/processes/b-code-dispatch-coordination.md` §HIGH-class.
prerequisites: |
  HARD: Brief 4 (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1) shipped — cortex_directives
        + prompt_review_queue tables must exist for counter increments and
        untraceable-proposal logging.
  Brief 5 (PER_MATTER_CLICKUP_LINKAGE_1) — DEFERRED per Director 2026-04-30
        directive: "matters knowledge + obsidian + LEARNING LOOP + reasoning
        are PRIORITY. Channels are last-stage." Brief 3 V1 ships with
        ClickUp write code path env-gated OFF (REFLECTOR_CLICKUP_WRITE=false
        default; remains false in V1). NO Brief 5 dependency at runtime.
        Vault write to proposed-config-deltas.md is the SOLE active write
        target in V1 — exactly the channels-last shape Director ratified.
        ClickUp infrastructure stays dormant in code; activation pending
        any future Brief 5 V2+ ship.
  NOT a prereq: Brief 1 (vault_write MCP tool) — Reflector writes via the
        same staging-path-then-Mac-Mini-mirror pattern Brief 4 uses (CHANDA #9
        current form). If Brief 1 lands first, can re-point to baker_vault_write
        as follow-up — out of this brief's scope.
sequencing: |
  Per AI Head 1 ratification 2026-04-30 (Q1 flip): this brief ships AFTER
  Brief 4. ETA ~2026-05-13 per V4 roadmap (early week of May 11).
---

# BRIEF: CORTEX_PHASE6_REFLECTOR_1 — Phase 6 Reflector with citation counters + vault write (V1)

## §0. Simplification preamble (DROPS + V2 triggers)

Per Director directives 2026-04-30:
1. "build simple, refine from practice" — V1 ships the smallest Reflector that observes whether Triaga-only counter signal works at all. Production data drives V2 selection.
2. **PRIORITY PIVOT 2026-04-30 (channels-last):** "matters knowledge + obsidian + LEARNING LOOP + reasoning are PRIORITY. Channels are last-stage." Brief 5 (PER_MATTER_CLICKUP_LINKAGE_1) DEFERRED — moved to held-back queue in V4 YAML. Brief 3 + 4 (this and CORTEX_CONFIG_DIRECTIVES_SCHEMA_1) ELEVATED to critical-path: they ARE the learning loop.

V1 effects:
- ClickUp write infrastructure ships in Brief 3 V1 BUT stays dormant (env-gated `REFLECTOR_CLICKUP_WRITE=false`, remains false in V1). Code retained so future Brief 5 V2+ activation is a 1-line env flip rather than re-spec/re-implement.
- Vault write to `proposed-config-deltas.md` is the SOLE active write target in V1 — channels-last shape Director ratified.

| Dropped from V1 | Reason | V2 trigger criterion |
|---|---|---|
| **Cycle-outcome inspector** (implicit-pass detection: "did Director ship what proposal recommended within TTL?") | Heaviest engineering line: requires LLM-comparison call after every TTL, "shipped what" definition, contradicting-proposal detection | Add to V2 if **stale-rate > 30%** of cycles in first calendar month |
| **ClickUp aux signal as auxiliary counter feed** (closed=helpful++ / dismissed=harmful++ when Triaga silent) | Adds 4-row conflict matrix + `directive_signal_mismatch` table; only useful if Triaga signal is sparse | Add to V2 if **Triaga ratification coverage < 50%** of cycles in first calendar month |
| **`directive_signal_mismatch` log table** | Falls out with ClickUp aux drop — no aux source to mismatch against | Re-introduce when ClickUp aux re-introduced |
| **Drift detector for Brief 5 ClickUp surface contract** | Already deferred by AI Head 1 ratification (C-followup) to a separate CHANDA candidate | Separate CHANDA item, not this brief |
| **Periodic spot-audit (1% sampling) of citations** via second-pass LLM | Director-rejected as over-engineering | N/A |

V1 = Triaga-only counter signal. ClickUp write is **target only** (proposed actions land there for Director visibility), not yet a counter signal source.

---

## §1. Context

**Cortex Stage 2 V1** runs a 6-phase cycle: sense → load → reason → propose → act → archive. Phases 1–5 land in `orchestrator/`. Phase 6 (Reflector) is the **observation + counter-update** phase that closes the learning loop.

**Reflector's V1 job:**
1. Parse `[directive: <id>]` citations from Phase 4 propose-phase output.
2. After Director Triaga decision (or 14d silence), increment counters on each cited directive in `cortex_directives` (Brief 4 schema).
3. Flag untraceable proposals (no/unknown/malformed citation) into `prompt_review_queue` (Brief 4 schema) for weekly eyeball review.
4. Write proposed actions to **vault** (V1 sole active target per channels-last directive):
   - **Vault**: `wiki/matters/<slug>/proposed-config-deltas.md` (append per cycle; Markdown-readable) — V1 ACTIVE
   - **ClickUp**: per-matter "Drafts & Deliverables" list (per Brief 5 surface contract) — V1 DORMANT, code retained but env-gated `REFLECTOR_CLICKUP_WRITE=false` per Brief 5 deferral

**Counter math** (AI Head 1 Q2 ratification 2026-04-30):
- helpful++ on Director Triaga ratify
- harmful++ on Director Triaga decline
- stale++ on 14-day silence after proposal cited the directive (no Triaga signal)
- pending tracked in-flight (cited but TTL not yet expired) — decremented when state resolves
- score = `helpful / (helpful + harmful)`, ignoring stale and pending

**Citation format** (Director caveat 2 ratification 2026-04-30):
- Phase 4 propose-phase prompt instructs the model: *"If you drew on a directive from the playbook, cite it by id at the end of your proposal: `[directive: <id>]`. Multi-citation OK: `[directive: D-101, D-204]`."*
- Reflector parses citations with regex; counter routing follows directive-id provenance, not write-target surface.

**Counter-signal hierarchy** (AI Head 1 ratification A 2026-04-30 — V1 simplified by dropping aux signal):
- **PRIMARY**: Director Triaga ratification (sole signal source in V1).
- **AUX**: NONE in V1. ClickUp closed/dismissed defer to V2.
- Cycle-outcome inspector also deferred to V2.

**Architectural alignment:**
- `orchestrator/cortex_runner.py` is the cycle entry point. Phase 6 wiring lands as `_run_phase6_archive_and_reflect()` block called after Phase 5 (act) completes (or after Triaga TTL expires for already-archived cycles — see §3.5 deferred-trigger pattern).
- Per-matter directives surface lives at `wiki/matters/<slug>/curated/directives.md` (Brief 4 provisions empty; Reflector promotes new directives here when surfacing patterns).

**Foundation references:**
- `_ops/ideas/2026-04-27-cortex-architecture-final-locked.md` — RA-23 ratified 6-phase architecture
- `briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md` — schema this brief consumes
- `_ops/processes/cortex-clickup-surface-contract.md` — Brief 5's published contract (path TBD; Brief 5 ships in Thu-Fri week of May 4 per V4 roadmap)
- `orchestrator/cortex_phase4_proposal.py` — Phase 4 module this brief modifies
- `migrations/20260428_cortex_cycles.sql` — `director_action` column ('gold_approved' / 'gold_modified' / 'gold_rejected' / 'refresh_requested') = signal source for Triaga decision

---

## §2. Problem

### 2.1 Today (without Reflector)

Phase 4 emits proposals; Director Triaga ratifies / declines; cycle is archived. **No mechanism exists to learn from outcomes.** Directives that consistently lead to good proposals are indistinguishable from directives that consistently fail. Untraceable proposals (where the model doesn't cite a playbook directive) cannot be flagged. Director and AI Head A have no rolled-up surface to see proposed actions across the 31 active matters — they're scattered across vault markdown.

### 2.2 Concrete blockers

| Blocked use case | Why blocked |
|---|---|
| "Which directives are load-bearing for this matter?" — query | No counter increments → all counters are 0 |
| "Which proposals weren't traceable to any directive?" — Director eyeball pass | No prompt_review_queue rows |
| "What's pending across all matters?" — single-pane query | Proposed actions only in vault markdown, not in queryable ClickUp surface |
| Phase 6 wiring missing — cycle archives without reflection | `cortex_runner.py` has no Phase 6 block beyond cycle-row finalize |

### 2.3 What this brief delivers

1. **Phase 4 prompt amendment**: prepend the citation directive to the propose-phase prompt. Models cite or are flagged.
2. **New module `orchestrator/cortex_phase6_reflector.py`**: parse citations, increment counters, log untraceable, write proposed-actions to vault (`proposed-config-deltas.md`). ClickUp write code path included BUT dormant in V1 (env-gated off per Brief 5 deferral).
3. **Phase 6 wiring** in `cortex_runner.py`: hook in after Phase 5 (act) completes — or after Triaga TTL for cycles archived without immediate Director action (see §3.5 deferred-trigger pattern).
4. **ClickUp client extension** (read Brief 5 contract): write proposed actions to per-matter Drafts & Deliverables list per surface contract.
5. **Vault write**: append proposed-actions block to `wiki/matters/<slug>/proposed-config-deltas.md` via existing CHANDA-#9 staging path.

---

## §3. Solution

### 3.1 Phase 4 prompt amendment (citation directive)

**File:** `orchestrator/cortex_phase3_synthesizer.py` (Phase 3c → Phase 4 transition synthesizes the proposal_text consumed by Phase 4). Locate the propose-phase prompt block; prepend:

```
DIRECTIVE CITATION REQUIREMENT
==============================
You have been provided with the matter's directives playbook (curated/
directives.md, loaded in Phase 2). If you draw on any directive in
formulating this proposal, cite it by id at the end of your proposal:

  [directive: <id>]

Multiple directives OK: [directive: <id1>, <id2>, ...]

If your proposal does not draw on the playbook (novel reasoning), omit
the citation. Untraceable proposals are flagged to a review queue, not
penalized — but consistent omission suggests the playbook needs new
directives. Be honest, not performative: cite only directives you
actually relied on.
```

**Why this exact wording** (Director caveat 2 ratification + V1-simplification):
- "Be honest, not performative" — combats false-positive citation (model citing a directive it didn't actually use). V2 spot-audit would catch this; V1 relies on the prompt + Director eyeball at review.
- "Untraceable proposals are flagged, not penalized" — communicates the path: no citation goes to queue (eyeball-review), no harmful counter penalty. Removes the model's incentive to fabricate citations.
- Multi-citation explicit: `[directive: id1, id2]` parsed as separate increments per directive (per AI Head 1 lower-priority default-acceptance: each gets full counter increment, not fractional).

### 3.2 Reflector module: parse + increment + log + write

**New file `orchestrator/cortex_phase6_reflector.py`:**

```python
"""Cortex Phase 6 Reflector — citation parsing, counter updates, vault write (V1).

Brief: CORTEX_PHASE6_REFLECTOR_1.

Reflector responsibilities (V1):
  1. Parse [directive: <id>] citations from Phase 4 proposal_text.
  2. Look up cited ids in cortex_directives; route by directive provenance,
     not write-target surface (per AI Head 1 ratification B 2026-04-30).
  3. After Director Triaga decision (or 14d TTL): increment helpful_count /
     harmful_count / stale_count on cited directives.
  4. Untraceable proposals (no citation, unknown id, malformed id) → insert
     prompt_review_queue row.
  5. Write proposed actions to two surfaces:
     a. Vault: wiki/matters/<slug>/proposed-config-deltas.md (append)
     b. ClickUp: per-matter Drafts & Deliverables list (per Brief 5 contract)

V1 explicit drops (see brief §0): no cycle-outcome inspector, no ClickUp
aux counter signal, no directive_signal_mismatch log.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Citation regex — anchored to whole match; tolerant of whitespace.
# Supports: [directive: foo-001], [directive: foo-001, bar-002], [directive:foo-001]
CITATION_RE = re.compile(
    r"\[directive:\s*([a-z0-9_]+(?:-[a-z0-9]+)*(?:\s*,\s*[a-z0-9_]+(?:-[a-z0-9]+)*)*)\s*\]",
    re.IGNORECASE,  # per python-backend rule: re.IGNORECASE flag, not (?i)
)
DIRECTIVE_ID_RE = re.compile(r"^[a-z0-9_]+(?:-[a-z0-9]+)*$")

TRIAGA_TTL_DAYS = int(os.getenv("REFLECTOR_TRIAGA_TTL_DAYS", "14"))

# Director Triaga signal: cycle.director_action values from cortex_cycles.
TRIAGA_HELPFUL_VALUES = {"gold_approved", "gold_modified"}
TRIAGA_HARMFUL_VALUES = {"gold_rejected"}
TRIAGA_AMBIGUOUS_VALUES = {"refresh_requested"}  # treat as pending, not stale


@dataclass
class CitationParse:
    cycle_id: str
    matter_slug: str
    cited_ids: list[str]              # validated id format, deduped
    invalid_tokens: list[str]         # malformed id strings encountered
    raw_proposal_text: str
    has_any_citation_match: bool      # at least one [directive: …] block found


def parse_citations(proposal_text: str) -> tuple[list[str], list[str], bool]:
    """Extract directive ids from proposal_text.

    Returns (valid_ids, invalid_tokens, has_any_match).

    valid_ids: deduped, format-validated ids.
    invalid_tokens: matched [directive: <id>] entries that fail DIRECTIVE_ID_RE.
    has_any_match: True if the regex matched any [directive: …] block at all.
    """
    matches = CITATION_RE.findall(proposal_text or "")
    has_any = bool(matches)
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for m in matches:
        # m is the inner content (between : and ]); split on comma
        for token in m.split(","):
            t = token.strip()
            if not t:
                continue
            if DIRECTIVE_ID_RE.match(t):
                if t not in seen:
                    valid.append(t)
                    seen.add(t)
            else:
                invalid.append(t)
    return valid, invalid, has_any


def _get_store():
    """Resolve canonical SentinelStoreBack singleton.

    NOTE: SentinelStoreBack uses a psycopg2 connection POOL (SimpleConnectionPool)
    with `_get_conn()` / `_put_conn()` borrow semantics — there is NO `.conn`
    attribute. All callers MUST borrow + return on every operation:

        conn = store._get_conn()
        try:
            ...
            conn.commit()
        except Exception:
            conn.rollback()  # python-backend rule
            raise
        finally:
            store._put_conn(conn)

    Verified against memory/store_back.py:39-715 (every persistence method
    follows this pattern).
    """
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def increment_counters_on_cited_directives(
    *,
    cycle_id: str,
    matter_slug: str,
    cited_ids: list[str],
    counter_field: str,  # 'helpful_count' | 'harmful_count' | 'stale_count'
) -> tuple[int, list[str]]:
    """UPDATE cortex_directives — increment counter on each cited id.

    Returns (rows_updated, unknown_ids). Unknown ids include both:
      * directive_id absent from cortex_directives entirely
      * directive_id present but matter_slug-scoped to a DIFFERENT matter
        (cross-matter citation hardening — prevents AO cycle from
        incrementing MOVIE directive counters via fabricated id)

    `_global-*` ids bypass the matter_slug check (they apply across matters).

    Caller logs unknown_ids to prompt_review_queue with reason
    'unknown_directive_id'.

    Connection borrowed + returned via pool. UPDATE in single transaction
    with rollback on exception (python-backend rule).
    """
    if counter_field not in {"helpful_count", "harmful_count", "stale_count"}:
        raise ValueError(f"counter_field must be one of helpful/harmful/stale, got {counter_field!r}")
    if not cited_ids:
        return 0, []

    # Split into matter-scoped vs global ids; existence-check has different
    # WHERE clauses for each.
    global_ids = [d for d in cited_ids if d.startswith("_global-")]
    matter_ids = [d for d in cited_ids if not d.startswith("_global-")]

    store = _get_store()
    conn = store._get_conn()
    rows_updated = 0
    unknown: list[str] = []
    try:
        with conn.cursor() as cur:
            present: set[str] = set()
            # Matter-scoped ids must belong to THIS matter:
            if matter_ids:
                cur.execute(
                    """
                    SELECT directive_id FROM cortex_directives
                     WHERE directive_id = ANY(%s)
                       AND matter_slug = %s
                       AND status = 'active'
                    """,
                    (matter_ids, matter_slug),
                )
                present.update(row[0] for row in cur.fetchall())
            # Global ids are universal:
            if global_ids:
                cur.execute(
                    """
                    SELECT directive_id FROM cortex_directives
                     WHERE directive_id = ANY(%s)
                       AND matter_slug = '_global'
                       AND status = 'active'
                    """,
                    (global_ids,),
                )
                present.update(row[0] for row in cur.fetchall())
            unknown = [d for d in cited_ids if d not in present]
            if present:
                # Parameterized UPDATE; field name interpolated only after
                # whitelist check above — never user-controlled.
                cur.execute(
                    f"""
                    UPDATE cortex_directives
                       SET {counter_field} = {counter_field} + 1,
                           updated_at = NOW()
                     WHERE directive_id = ANY(%s)
                    """,
                    (list(present),),
                )
                rows_updated = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()  # python-backend rule
        raise
    finally:
        store._put_conn(conn)
    return rows_updated, unknown


def log_untraceable_proposal(
    *,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    flagged_reason: str,
) -> int:
    """INSERT prompt_review_queue row. Returns queue_id.

    flagged_reason ∈ {'no_citation', 'unknown_directive_id', 'malformed_citation'}
    per Brief 4 schema CHECK constraint.

    Connection borrowed + returned via pool.
    """
    if flagged_reason not in {"no_citation", "unknown_directive_id", "malformed_citation"}:
        raise ValueError(f"invalid flagged_reason: {flagged_reason!r}")

    store = _get_store()
    conn = store._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prompt_review_queue
                    (cycle_id, matter_slug, proposal_text, flagged_reason)
                VALUES (%s, %s, %s, %s)
                RETURNING queue_id
                """,
                (cycle_id, matter_slug, proposal_text, flagged_reason),
            )
            queue_id = cur.fetchone()[0]
        conn.commit()
        return int(queue_id)
    except Exception:
        conn.rollback()
        raise
    finally:
        store._put_conn(conn)


def classify_triaga_outcome(director_action: Optional[str], age: timedelta) -> str:
    """Classify cycle outcome for counter routing.

    Returns one of:
      'helpful'  → increment helpful_count on cited directives
      'harmful'  → increment harmful_count on cited directives
      'stale'    → increment stale_count (TTL expired without signal)
      'pending'  → still in-flight (TTL not expired, no clear signal)

    Maps cortex_cycles.director_action values per architecture.
    """
    if director_action in TRIAGA_HELPFUL_VALUES:
        return "helpful"
    if director_action in TRIAGA_HARMFUL_VALUES:
        return "harmful"
    if director_action in TRIAGA_AMBIGUOUS_VALUES:
        return "pending"  # refresh_requested = re-run; not a final outcome yet
    if director_action is None and age >= timedelta(days=TRIAGA_TTL_DAYS):
        return "stale"
    return "pending"


# Vault + ClickUp write functions follow in §3.3 / §3.4 — see brief.
```

(Vault + ClickUp write helpers continue in §3.3 / §3.4.)

### 3.3 Vault write: proposed-config-deltas.md

**Append-only**, frontmatter on first write, one block per cycle:

```python
def write_proposed_actions_to_vault(
    *,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    cited_ids: list[str],
    triaga_outcome: str,
    today_iso: str,
    staging_root: Path,
) -> Path:
    """Append proposed-actions block to vault staging path.

    Path: {staging_root}/matters/{matter_slug}/proposed-config-deltas.md

    First write creates file with frontmatter; subsequent writes append.
    Mac Mini's vault mirror picks up on next sync (CHANDA #9 current form).
    """
    target = staging_root / "matters" / matter_slug / "proposed-config-deltas.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    block = (
        f"\n## Cycle {cycle_id} — {today_iso} ({triaga_outcome})\n\n"
        f"**Cited directives:** {', '.join(cited_ids) if cited_ids else '_none — flagged untraceable_'}\n\n"
        f"### Proposal\n\n{proposal_text.strip()}\n\n"
        f"---\n"
    )

    if not target.exists():
        # Frontmatter MUST conform to kbl/ingest_endpoint.validate_frontmatter
        # (REQUIRED_KEYS: type/slug/name/updated/author/tags/related;
        # VALID_TYPES: matter/person/entity; VALID_VOICES: silver/gold).
        # type='matter' because this file IS the matter's proposed-deltas
        # surface. voice='silver' = agent-authored (per kbl voice enum).
        # source/provenance are NOT validator-required keys; carried as
        # documentation-only fields below the required block.
        frontmatter = (
            f"---\n"
            f"type: matter\n"
            f"slug: {matter_slug}\n"
            f"name: {matter_slug} — Proposed Config Deltas (Reflector)\n"
            f"updated: {today_iso}\n"
            f"author: agent\n"
            f"tags: [cortex-reflector, proposed-deltas]\n"
            f"related: []\n"
            f"voice: silver\n"
            f"source: cortex_phase6_reflector\n"
            f"provenance: cortex_cycles.cycle_id\n"
            f"---\n"
            f"# {matter_slug} — Proposed Config Deltas\n\n"
            f"Reflector-emitted proposed actions per Cortex cycle. Append-only.\n"
        )
        target.write_text(frontmatter + block, encoding="utf-8")
    else:
        with target.open("a", encoding="utf-8") as f:
            f.write(block)

    return target
```

**Frontmatter notes:** the 7 required keys (`type/slug/name/updated/author/tags/related`) plus `voice` are emitted per `kbl/ingest_endpoint.py:30-33` validator. Type is `matter` (this file IS the matter's proposed-deltas surface). `source`/`provenance` are non-required fields included for Reflector audit trace.

### 3.4 ClickUp write: Drafts & Deliverables list — DORMANT in V1 (Brief 5 deferred)

**V1 status:** Brief 5 (PER_MATTER_CLICKUP_LINKAGE_1) DEFERRED per Director 2026-04-30 channels-last directive. This section's code ships in Brief 3 V1 but stays DORMANT — env-gated `REFLECTOR_CLICKUP_WRITE=false` default, **remains false throughout V1**.

The dormant code is retained (rather than removed) so future Brief 5 V2+ activation is a 1-line env flip rather than re-spec/re-implement. **Vault write to `proposed-config-deltas.md` (§3.3) is the SOLE active write target in V1.**

**Behavior gate:** `REFLECTOR_CLICKUP_WRITE` env var (default `false`; stays false in V1). When `true` (post-Brief-5 V2+), Reflector reads the contract and writes:

```python
def write_proposed_actions_to_clickup(
    *,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    cited_ids: list[str],
    triaga_outcome: str,
) -> Optional[str]:
    """Create per-matter ClickUp task on Drafts & Deliverables list.

    Returns ClickUp task URL on success, None if disabled by env.

    Reads list_id from Brief 5 surface contract:
      _ops/processes/cortex-clickup-surface-contract.md → list_map[matter_slug]['drafts_deliverables']

    Tag-only matters (constantinos, brisen-funding, brisen-pr): no ClickUp
    write — proposals route to AO/parent surface per Brief 5 (Reflector
    consults contract.tag_only_matters list).

    Counter routing follows directive-id provenance (per AI Head 1
    ratification B 2026-04-30), not write-target surface — so a
    constantinos directive cited in a constantinos cycle still hits
    constantinos counters even if proposal physically lands on AO surface.
    """
    if os.environ.get("REFLECTOR_CLICKUP_WRITE", "false").strip().lower() != "true":
        logger.info("ClickUp write disabled (REFLECTOR_CLICKUP_WRITE != true)")
        return None

    contract_path = Path(__file__).resolve().parents[1] / "_ops" / "processes" / "cortex-clickup-surface-contract.md"
    if not contract_path.is_file():
        logger.warning("Brief 5 contract not found at %s — ClickUp write skipped", contract_path)
        return None

    # Brief 5 publishes contract format (YAML embedded in md). Reflector
    # parses contract once at module load; cache.
    contract = _load_clickup_contract(contract_path)
    if matter_slug in contract["tag_only_matters"]:
        # Route to parent surface per contract; counters still hit matter_slug.
        parent_slug = contract["tag_only_routing"][matter_slug]
        list_id = contract["list_map"][parent_slug]["drafts_deliverables"]
    else:
        entry = contract["list_map"].get(matter_slug)
        if not entry:
            logger.warning("matter %s not in Brief 5 contract list_map — skipping ClickUp", matter_slug)
            return None
        list_id = entry["drafts_deliverables"]

    # Existing ClickUp client at top-level clickup_client.py (class
    # ClickUpClient, method create_task at line ~272). All writes per
    # CLAUDE.md: BAKER space only (kill switch via BAKER_CLICKUP_READONLY
    # env var, max-write quota enforced by ClickUpClient._check_write_allowed
    # before each create_task call). Brief 5 surface contract MUST place
    # all matter folders within BAKER space (901510186446). If contract
    # violates: ClickUpClient raises, Reflector logs + skips that matter.
    from clickup_client import ClickUpClient
    client = ClickUpClient()
    task = client.create_task(
        list_id=list_id,
        name=f"Cortex proposal — {cycle_id[:8]} ({triaga_outcome})",
        description=_format_clickup_description(
            cycle_id, matter_slug, proposal_text, cited_ids, triaga_outcome
        ),
        tags=["cortex_proposal", f"matter:{matter_slug}", f"outcome:{triaga_outcome}"],
    )
    return task.get("url") or f"https://app.clickup.com/t/{task['id']}"
```

**Brief 5 contract structure assumption** (Reflector reads, Brief 5 authors):

```yaml
# _ops/processes/cortex-clickup-surface-contract.md (Brief 5)
contract_version: 1
list_map:
  oskolkov:
    drafts_deliverables: "<clickup_list_id>"
    folder_id: "<clickup_folder_id>"
  movie:
    drafts_deliverables: "<clickup_list_id>"
    folder_id: "<clickup_folder_id>"
  # ... 15 substantive matters
operational_matters:
  claimsmax: "<single_list_id>"
  m365: "<single_list_id>"
  baker-internal: "<single_list_id>"
  personal: "<single_list_id>"
tag_only_matters:
  - constantinos
  - brisen-funding
  - brisen-pr
tag_only_routing:
  constantinos: oskolkov  # routes to AO surface
  brisen-funding: oskolkov
  brisen-pr: oskolkov
```

If Brief 5's actual structure differs at ship time: Reflector parser is small (~30 LOC), trivial to update. **Worst case**: Brief 5 ships first with stable contract → Reflector reads cleanly. **Else**: Reflector ships with `REFLECTOR_CLICKUP_WRITE=false` and only vault write is active until contract lands.

### 3.5 Phase 6 wiring in cortex_runner.py

Two trigger points (deferred-trigger pattern):

**Trigger A — immediate (Phase 5 act completes with Triaga decision in same cycle):**

Standard 6-phase flow runs Phase 6 after Phase 5. If `cortex_cycles.director_action` is non-NULL by the time the runner reaches Phase 6 (Director Triaga ratified during the cycle), Reflector can route immediately to helpful/harmful counters.

**Trigger B — deferred (Triaga TTL):**

Most cycles archive with `director_action = NULL` because Director hasn't acted yet, OR Director acts later (cycle lands at `status='approved' | 'rejected' | 'modified'` post-Triaga). These need a deferred sweep. Schedule via the existing **APScheduler** infrastructure in `triggers/embedded_scheduler.py` (matches `clickup_poll`, `gmail_poll`, etc. patterns) — NOT a separate Render cron service. New job: `phase6_reflector_sweep`, hourly cadence, env override `REFLECTOR_SWEEP_CRON_HOUR` / `REFLECTOR_SWEEP_CRON_MINUTE`.

**Status filter** must include all relevant Triaga-outcome states. The actual `cortex_cycles.status` enum (per `migrations/20260428_cortex_cycles.sql:25` + transient-amendment `20260429_cortex_cycles_add_transient_statuses.sql`) is:
`'in_flight','awaiting_reason','proposed','tier_b_pending','approving','approved','rejecting','rejected','editing','modified','refreshing','failed','superseded','abandoned'`.
Reflector-eligible = pre-decision (`proposed`, `tier_b_pending`) OR Triaga-decided (`approved`, `rejected`, `modified`). Excluded = transient *ing variants (will resolve), `in_flight` / `awaiting_reason` (pre-proposal), `failed`/`superseded`/`abandoned` (terminal-no-Reflector).

```python
# orchestrator/cortex_phase6_reflector.py — deferred sweep entry point

REFLECTOR_ELIGIBLE_STATUSES = (
    'proposed', 'tier_b_pending',  # pre-decision (sweep on TTL)
    'approved', 'rejected', 'modified',  # Triaga-decided (sweep immediately)
)


async def sweep_pending_cycles() -> dict:
    """Run hourly via APScheduler. Find Reflector-eligible cycles that
    either (a) have a Triaga decision since last sweep, or (b) have
    aged past TRIAGA_TTL_DAYS without a decision.

    For each: invoke reflect_cycle() to update counters + write surfaces.
    Marks done by writing one cortex_phase_outputs row with
    phase='archive', artifact_type='reflector_complete'. Idempotent
    (skips already-marked cycles via NOT IN subquery).

    Returns dict with counts: {checked, reflected, stale_count, errors}.
    """
    store = _get_store()
    conn = store._get_conn()
    cutoff_age = datetime.now(timezone.utc) - timedelta(days=TRIAGA_TTL_DAYS)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cycle_id, matter_slug, started_at, director_action
                  FROM cortex_cycles
                 WHERE status = ANY(%s)
                   AND (director_action IS NOT NULL
                        OR started_at < %s)
                   AND cycle_id NOT IN (
                       SELECT cycle_id FROM cortex_phase_outputs
                        WHERE phase = 'archive'
                          AND artifact_type = 'reflector_complete'
                   )
                 ORDER BY started_at ASC
                 LIMIT 100
                """,
                (list(REFLECTOR_ELIGIBLE_STATUSES), cutoff_age),
            )
            cycles = cur.fetchall()
    finally:
        store._put_conn(conn)
    # Process outside the SELECT transaction (each cycle has its own
    # increment+idempotency-mark transaction in reflect_cycle, see below).
    # Counter increment + idempotency-row INSERT MUST run in one
    # transaction to avoid double-counting if sweep collides with
    # itself (e.g., Render redeploy + cron firing on the same minute).
    # reflect_cycle() does this; sweep_pending_cycles only enumerates.
        # (Note: cortex_phase_outputs.phase CHECK constraint allows only
        # sense/load/reason/propose/act/archive — Phase 6 Reflector is part
        # of the archive phase per RA-23 architecture.)
    except Exception:
        conn.rollback()
        raise
```

**Cron schedule:** hourly via existing APScheduler in `triggers/embedded_scheduler.py` (NOT a separate Render cron service — matches `clickup_poll`, `gmail_poll`, etc. patterns). Cost: a single SELECT + N small UPDATEs + ≤ 100 vault writes per hour. Negligible.

**Idempotency (transactional):** `reflect_cycle(cycle_id)` MUST wrap the counter UPDATE + idempotency-marker INSERT in a single transaction:

```python
def reflect_cycle(cycle_id: str, matter_slug: str, ...):
    """Increment counters + mark cycle reflector_complete in one txn."""
    store = _get_store()
    conn = store._get_conn()
    try:
        with conn.cursor() as cur:
            # 1. Increment counters on cited directives (in same txn)
            #    ... see increment_counters_on_cited_directives logic ...
            # 2. Insert idempotency marker — ON CONFLICT prevents
            #    double-mark if two sweeps collide
            cur.execute(
                """
                INSERT INTO cortex_phase_outputs
                    (cycle_id, phase, phase_order, artifact_type, payload)
                VALUES (%s, 'archive', 6, 'reflector_complete', %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (cycle_id, json.dumps({"reflected_at": "...", "outcome": "..."})),
            )
            if cur.rowcount == 0:
                # Another sweep marked it first — abort our increments
                # (transaction will roll back below)
                raise RuntimeError("cycle already reflected by concurrent sweep")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        store._put_conn(conn)
```

**Schema prerequisite for ON CONFLICT** (Brief 4 §3.1 follow-up): add a UNIQUE constraint on `cortex_phase_outputs (cycle_id, artifact_type) WHERE artifact_type = 'reflector_complete'` to make `ON CONFLICT DO NOTHING` work. Brief 4 implementer adds this index alongside the directives migration. **Action: Brief 4 §3.1 SQL must include:**

```sql
-- Idempotency support for Phase 6 Reflector (Brief 3 dependency)
CREATE UNIQUE INDEX IF NOT EXISTS idx_cortex_phase_outputs_reflector_complete
    ON cortex_phase_outputs (cycle_id)
    WHERE artifact_type = 'reflector_complete';
```

Re-running sweep is safe: idempotency marker prevents double-counter.

**Audit emission (CLAUDE.md hard rule):** every `reflect_cycle()` invocation appends one row to `baker_actions` with action_type='cortex_reflector_complete', action_target=cycle_id, status='success'|'failed'. Mirrors existing patterns in capability_runner / cortex_phase4_proposal.

### 3.6 What this brief does NOT touch

- `cortex_directives` table schema — Brief 4 owns. Reflector only INSERTs counter increments (UPDATE rows) + reads.
- `prompt_review_queue` schema — Brief 4 owns. Reflector only INSERTs.
- Brief 5 surface contract content — Reflector reads (when post-V1 reactivated), doesn't write the contract. **V1: Brief 5 deferred per channels-last directive 2026-04-30 — ClickUp code path dormant, no contract read in V1 ship.**
- ClickUp write outside BAKER space — CLAUDE.md hard rule. If contract specifies any non-BAKER list (when reactivated), Reflector refuses + logs.
- Cycle-outcome inspector — V2 (preamble §0).
- ClickUp aux signal — V2 (preamble §0).
- `directive_signal_mismatch` log table — does not exist in V1.
- Director-manual directive seeding — separate workflow.

---

## §4. Implementation order

1. **Verify Brief 4 schema applied** — `\d cortex_directives` shows table; `\d prompt_review_queue` shows table.
2. **Phase 4 prompt amendment** in `orchestrator/cortex_phase3_synthesizer.py`. Run existing Phase 4 pytest to confirm no regression.
3. **Implement `orchestrator/cortex_phase6_reflector.py`** — citation parser + counter increments + untraceable logging + classify_triaga_outcome + sweep_pending_cycles.
4. **Implement vault write helper** (`write_proposed_actions_to_vault`) — staging-path write, frontmatter, append.
5. **Implement ClickUp write helper** (`write_proposed_actions_to_clickup`) — env-gated, contract-loaded, BAKER-space-only.
6. **Wire Phase 6 into `cortex_runner.py`** — Trigger A (post-Phase-5) + Trigger B (cron sweep).
7. **Tests** (see §5).
8. **Dry-run on a real cycle** in staging — observe directives.md, vault path, prompt_review_queue rows, counter increments.
9. **Commit + PR** (TIER A — request AI Head B cross-lane review, follow `/security-review` skill if any external API surface deemed novel).

---

## §5. Verification

### 5.1 Citation parser unit tests — `tests/test_phase6_reflector_parse.py`

Required cases (≥ 12):

| # | Input | Expected |
|---|---|---|
| 1 | `"some text [directive: foo-001]"` | valid=['foo-001'], invalid=[], has=True |
| 2 | `"prefix [directive: foo-001, bar-002] suffix"` | valid=['foo-001','bar-002'] |
| 3 | `"two blocks [directive: a-1] middle [directive: b-2]"` | valid=['a-1','b-2'] |
| 4 | `"dedup [directive: x-1, x-1]"` | valid=['x-1'] (deduped) |
| 5 | `"case [DIRECTIVE: foo-001]"` | valid=['foo-001'] (case-insensitive) |
| 6 | `"whitespace [directive:foo-001]"` | valid=['foo-001'] |
| 7 | `"malformed [directive: NotKebab]"` | invalid=['NotKebab'], has=True |
| 8 | `"empty list [directive: ]"` | valid=[], invalid=[], has=True |
| 9 | `"no citation block"` | valid=[], invalid=[], has=False |
| 10 | `""` | valid=[], invalid=[], has=False |
| 11 | global ID `[directive: _global-001]` | valid=['_global-001'] |
| 12 | mixed valid+invalid `[directive: foo-001, NotKebab]` | valid=['foo-001'], invalid=['NotKebab'] |

### 5.2 Counter increment tests — `tests/test_phase6_reflector_counters.py` (live-PG)

Auto-skips without `TEST_DATABASE_URL`. Required (≥ 6):

1. Seed 3 directives, increment helpful_count on 2 of them → SELECT shows +1 each.
2. Increment with unknown id → returns it in unknown list, no UPDATE.
3. Multi-id batch: 5 cited, 3 known + 2 unknown → 3 incremented, 2 returned unknown.
4. Empty cited_ids → returns (0, []).
5. Invalid counter_field → raises ValueError.
6. Concurrent increments (simulate via two cursors) → both succeed, count is correct (+2).

### 5.3 Untraceable logging tests — `tests/test_phase6_reflector_queue.py`

Required (≥ 4):
1. Log no_citation → SELECT prompt_review_queue shows row, reviewed=false.
2. Log unknown_directive_id → row inserted.
3. Invalid flagged_reason → raises ValueError.
4. SELECT idx_prompt_review_queue_unreviewed returns inserted rows.

### 5.4 Classify triaga outcome tests — `tests/test_phase6_reflector_classify.py`

Required (≥ 6):
1. director_action='gold_approved', age=1d → 'helpful'
2. director_action='gold_modified', age=1d → 'helpful'
3. director_action='gold_rejected', age=1d → 'harmful'
4. director_action='refresh_requested', age=1d → 'pending'
5. director_action=None, age=15d → 'stale'
6. director_action=None, age=1d → 'pending'

### 5.5 Vault write tests — `tests/test_phase6_reflector_vault.py`

Required (≥ 3):
1. First write creates file with frontmatter.
2. Second write appends — file has both blocks, frontmatter once.
3. Path follows staging convention.

### 5.6 ClickUp write tests — `tests/test_phase6_reflector_clickup.py`

Required (≥ 4):
1. `REFLECTOR_CLICKUP_WRITE=false` → returns None, no API call (mock asserts).
2. `REFLECTOR_CLICKUP_WRITE=true`, contract present → mock client called with correct list_id.
3. Tag-only matter routes to parent — assert list_id is parent's.
4. Matter not in contract list_map → returns None + warning logged.

### 5.7 Sweep tests — `tests/test_phase6_reflector_sweep.py`

Required (≥ 3):
1. Cycles aged < TTL with no director_action → not picked up.
2. Cycles aged > TTL → picked up, classified 'stale'.
3. Cycles already reflected (cortex_phase_outputs row with phase='archive' AND artifact_type='reflector_complete') → skipped.

### 5.8 Phase 4 prompt regression check

Existing `tests/test_cortex_phase4_proposal.py` must still pass after prompt amendment. The amendment is prepended text — should not break existing assertions.

### 5.9 End-to-end dry-run

After Phase 6 wired:
1. Trigger a cycle in staging on a low-stakes matter (`baker-internal` or sandbox).
2. Verify Phase 4 output contains the citation directive in its prompt input.
3. Manually compose proposal with `[directive: baker-internal-001]` (assuming such directive exists or is seeded).
4. Triaga ratify the proposal.
5. Verify cortex_directives.helpful_count for that id incremented by 1.
6. Verify proposed-config-deltas.md appended in staging.
7. Verify ClickUp task created (if env enabled + contract live).
8. Verify cortex_phase_outputs has row with phase='archive' AND artifact_type='reflector_complete'.

### 5.10 Sweep dry-run

1. Find a cycle aged > 14 days with director_action=NULL in staging.
2. Run `python -c "import asyncio; from orchestrator.cortex_phase6_reflector import sweep_pending_cycles; print(asyncio.run(sweep_pending_cycles()))"`.
3. Verify stale_count incremented on directives cited by that cycle.

---

## §6. Acceptance criteria

| # | Criterion | How to verify |
|---|---|---|
| AC1 | Phase 4 prompt includes citation directive | grep `orchestrator/cortex_phase3_synthesizer.py` for "DIRECTIVE CITATION" |
| AC2 | `orchestrator/cortex_phase6_reflector.py` imports clean | `python3 -c "from orchestrator.cortex_phase6_reflector import sweep_pending_cycles, parse_citations; print('OK')"` |
| AC3 | Citation parser passes all ≥ 12 unit tests | `pytest tests/test_phase6_reflector_parse.py -v` |
| AC4 | Counter increments work end-to-end with live PG | `pytest tests/test_phase6_reflector_counters.py -v` (live-PG) |
| AC5 | Untraceable proposal logs to prompt_review_queue | `pytest tests/test_phase6_reflector_queue.py -v` (live-PG) |
| AC6 | classify_triaga_outcome covers all branches | `pytest tests/test_phase6_reflector_classify.py -v` |
| AC7 | Vault write produces frontmatter + appendable file | `pytest tests/test_phase6_reflector_vault.py -v` |
| AC8 | ClickUp write env-gated, contract-aware, BAKER-only | `pytest tests/test_phase6_reflector_clickup.py -v` |
| AC9 | Sweep finds aged cycles, skips reflected ones | `pytest tests/test_phase6_reflector_sweep.py -v` (live-PG) |
| AC10 | Cron / scheduled sweep wired in `cortex_runner.py` or scheduler | grep for `sweep_pending_cycles` call site |
| AC11 | `bash scripts/check_singletons.sh` passes | CI guard |
| AC12 | No mention of cycle-outcome inspector / ClickUp aux / mismatch table in shipped code | grep audit |
| AC13 | End-to-end dry-run on real cycle (§5.9) succeeds | manual log + DB read |

---

## §7. Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| LLM doesn't follow citation directive (false-negative omission) | Medium | Prompt explicit + Director eyeball at review. V2 spot-audit if pattern persists |
| LLM fabricates citations (false-positive) | Medium | Prompt's "be honest, not performative" clause; manual review at Director Triaga |
| Brief 5 contract format drifts between Reflector author-time and ship-time | Low | `_load_clickup_contract` is small + isolated; trivial to update if format changes |
| Brief 5 ships AFTER Brief 3 — Reflector ClickUp write disabled day-1 | Low | `REFLECTOR_CLICKUP_WRITE=false` default makes vault-only operation safe; flip env to true once contract lands |
| Sweep job doesn't run (cron misconfigured) | Medium | AC10 covers; hourly is gentle enough that 1-day miss = 24 stale signals max — recoverable |
| Counter increment race condition (two concurrent reflections of same cycle) | Low | Idempotency check via `cortex_phase_outputs.output_kind='reflector_complete'` row before counter UPDATE — see §5.7.3 test |
| `director_action` semantics drift (e.g., new value added like 'gold_approved_with_changes') | Low | `classify_triaga_outcome` returns 'pending' for unknown values (default branch) — safe non-action |
| Prompt amendment breaks existing Phase 4 tests | Low | AC for Phase 4 regression run before merge (§5.8) |
| Untraceable proposal floods prompt_review_queue if model never cites | Medium | Reviewable via partial index + weekly Director eyeball; if rate > X/day, prompt itself needs revision (V2) |

---

## §8. Out of scope (defer to later briefs)

| Item | Where |
|---|---|
| Cycle-outcome inspector (implicit-pass detection) | V2 if stale-rate > 30% |
| ClickUp aux signal as auxiliary counter feed | V2 if Triaga coverage < 50% |
| `directive_signal_mismatch` log table | V2 alongside ClickUp aux re-introduction |
| Periodic spot-audit of citations (1% sampling) | Director-rejected as over-engineering |
| Drift detector for Brief 5 surface contract | Separate CHANDA candidate |
| Director-manual directive seeding tool | Optional, post-deploy |
| Reflector promotion of new directives to vault directives.md | V2 — V1 only updates counters on existing directives. Director + AI Head A seed playbook manually for first ~month |
| Counter decay over time (old directives age out) | V3 — production data first |
| Cross-matter directive aggregation queries | V2 if `_global-*` directives accumulate |

---

## §9. PR notes

**Suggested PR title:** `feat(cortex): Phase 6 Reflector with citation counters + vault write V1 (CORTEX_PHASE6_REFLECTOR_1)`

**Suggested PR body:**

> **Trigger class: TIER A** — modifies Phase 4 prompt + adds new phase + new external write surface (ClickUp via Brief 5 contract).
> Per `_ops/processes/b-code-dispatch-coordination.md` §HIGH-class, requires AI Head B cross-lane review pre-merge.
>
> **Depends on Brief 4** (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 — schema). **Brief 5 (PER_MATTER_CLICKUP_LINKAGE_1) DEFERRED** per Director 2026-04-30 channels-last directive — moved to held-back queue. Brief 3 ClickUp write infrastructure ships dormant in V1 (env `REFLECTOR_CLICKUP_WRITE=false`, stays false). Vault write is the sole active target in V1.
>
> **Simplification preamble** ([§0 in brief](briefs/BRIEF_CORTEX_PHASE6_REFLECTOR_1.md#0-simplification-preamble-drops--v2-triggers)) — V1 = Triaga-only counter signal. Cycle-outcome inspector + ClickUp aux signal explicitly deferred to V2 with documented trigger criteria (stale-rate > 30%, Triaga coverage < 50%). Per Director directive 2026-04-30 "build simple, refine from practice."
>
> **Sequencing:** ships AFTER Brief 4 per AI Head 1 Q1 flip ratification 2026-04-30. ETA ~2026-05-13 per V4 roadmap.

**Branch suggestion:** `feature/cortex-phase6-reflector-1`

---

## §10. Authoring provenance

- Author: AI Head A (CLI)
- Authored: 2026-04-30
- Review status: V1 draft, no review pass yet (will request 3-pass once paired with Brief 4)
- Director ratifications folded:
  - 2026-04-30 caveat 1 (CHANDA #9 amendment language) — companion patch on PR #95, not this brief
  - 2026-04-30 caveat 2 (per-directive citation `[directive: <id>]`)
  - 2026-04-30 caveat 3 (22-matter scope, superseded by live count: 31 active per slugs.yml v15)
  - 2026-04-30 simplification directive ("build simple, refine from practice") — preamble §0
- AI Head 1 ratifications folded:
  - Q1 (Reflector ships AFTER schema)
  - Q2 (counter math, 14d TTL)
  - Q2-NEW (cycle-outcome inspector elevated to PRIMARY) — DROPPED V1 per Director simplification, deferred V2
  - Q3 (slugs.yml at run-time, status != retired) — applies to Brief 4 only; Reflector reads cycles, not matters list
  - A (counter-signal hierarchy) — V1 simplified to Triaga-only (drops aux), still primary-signal-overrides discipline
  - B (counter routing follows directive-id provenance, not write-target surface) — central to ClickUp tag-only routing
  - C (Brief 5 surface contract import) — Brief 5 DEFERRED per Director 2026-04-30 channels-last directive ("matters knowledge + obsidian + LEARNING LOOP + reasoning are PRIORITY. Channels are last-stage."). ClickUp write infrastructure ships dormant in V1, env-gated off; reactivation pending any future Brief 5 V2+ ship. C ratification preserved as code path.
- Pen-lift: granted by AI Head 1 2026-04-30, deviation-flag-in-preamble path
