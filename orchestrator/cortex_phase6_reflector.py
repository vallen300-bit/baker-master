"""Cortex Phase 6 Reflector — citation parsing, counter updates, vault write (V1).

Brief: CORTEX_PHASE6_REFLECTOR_1.

Reflector responsibilities (V1):
  1. Parse [directive: <id>] citations from Phase 4 proposal_text.
  2. Look up cited ids in cortex_directives; route by directive provenance,
     not write-target surface (per AI Head 1 ratification B 2026-04-30).
  3. After Director Triaga decision (or 14d TTL): increment helpful_count /
     harmful_count / stale_count on cited directives.
  4. Untraceable proposals (no citation, unknown id, malformed id) -> insert
     prompt_review_queue row.
  5. Write proposed actions to vault (V1 sole active target):
        wiki/matters/<slug>/proposed-config-deltas.md (append).
     ClickUp write code path is retained but DORMANT in V1 (env-gated
     REFLECTOR_CLICKUP_WRITE=false; remains false through V1 per Director
     2026-04-30 channels-last directive).

V1 explicit drops (see brief §0): no cycle-outcome inspector, no ClickUp
aux counter signal, no directive_signal_mismatch log table.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Citation regex - tolerant of whitespace, supports multi-id comma lists.
# Examples matched: [directive: foo-001], [directive:foo-001],
# [directive: foo-001, bar-002], [DIRECTIVE: _global-001].
# python-backend rule: re.IGNORECASE flag, not inline (?i).
CITATION_RE = re.compile(
    r"\[directive:\s*([a-z0-9_]+(?:-[a-z0-9]+)*"
    r"(?:\s*,\s*[a-z0-9_]+(?:-[a-z0-9]+)*)*)\s*\]",
    re.IGNORECASE,
)
# Single-id format. matter-scoped: kebab. global: '_global-<NNN>'.
DIRECTIVE_ID_RE = re.compile(r"^[a-z0-9_]+(?:-[a-z0-9]+)*$")
# Empty-list match: [directive:  ] still counts as has_any_match=True so
# the proposal lands in prompt_review_queue with malformed_citation reason.
EMPTY_CITATION_RE = re.compile(r"\[directive:\s*\]", re.IGNORECASE)

TRIAGA_TTL_DAYS = int(os.getenv("REFLECTOR_TRIAGA_TTL_DAYS", "14"))

# cortex_cycles.director_action values per migrations/20260428_cortex_cycles.sql.
TRIAGA_HELPFUL_VALUES = {"gold_approved", "gold_modified"}
TRIAGA_HARMFUL_VALUES = {"gold_rejected"}
TRIAGA_AMBIGUOUS_VALUES = {"refresh_requested"}

# Reflector-eligible cortex_cycles.status values — verified against
# migrations/20260429_cortex_cycles_add_transient_statuses.sql:28-49.
# Excluded: in_flight / awaiting_reason (pre-proposal, nothing to reflect on),
# transient *ing (will resolve to terminal), failed/superseded/abandoned/
# archive_failed (terminal-no-Reflector).
REFLECTOR_ELIGIBLE_STATUSES = (
    "proposed",         # pre-decision (sweep on TTL)
    "tier_b_pending",   # pre-decision (sweep on TTL)
    "approved",         # Triaga-decided
    "rejected",         # Triaga-decided
    "modified",         # Triaga-decided
)

# Idempotency anchor (Brief 4 §3.1 partial unique idx +
# migrations/20260430_cortex_directives.sql:89-91).
REFLECTOR_COMPLETE_ARTIFACT = "reflector_complete"

# Vault staging path (CHANDA #9 — live_mirror/v1 pattern shared with Brief 4
# scripts/migrate_directives_for_existing_matters.py + bootstrap_matter.py).
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGING_ROOT = REPO_ROOT / "vault_scaffolding" / "live_mirror" / "v1"


# --------------------------------------------------------------------------
# Citation parsing
# --------------------------------------------------------------------------


def parse_citations(proposal_text: str) -> tuple[list[str], list[str], bool]:
    """Extract directive ids from proposal_text.

    Returns (valid_ids, invalid_tokens, has_any_match).

    valid_ids: deduped, format-validated ids (preserves first-seen order).
    invalid_tokens: tokens that appeared inside [directive: ...] but failed
        DIRECTIVE_ID_RE.
    has_any_match: True if the proposal contained at least one
        [directive: ...] block (even an empty one). Drives untraceable
        classification: no match -> 'no_citation'; match with all invalid
        tokens -> 'malformed_citation'.
    """
    text = proposal_text or ""
    has_any = bool(CITATION_RE.search(text)) or bool(EMPTY_CITATION_RE.search(text))
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    for inner in CITATION_RE.findall(text):
        for token in inner.split(","):
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


# --------------------------------------------------------------------------
# DB access
# --------------------------------------------------------------------------


def _get_store():
    """Resolve canonical SentinelStoreBack singleton.

    NOTE: SentinelStoreBack uses a psycopg2 connection POOL with
    `_get_conn()` / `_put_conn()` borrow semantics — there is NO `.conn`
    attribute. Callers MUST borrow + return on every operation; rollback
    on exception (python-backend rule).
    """
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def increment_counters_on_cited_directives(
    *,
    cycle_id: str,
    matter_slug: str,
    cited_ids: list[str],
    counter_field: str,
) -> tuple[int, list[str]]:
    """UPDATE cortex_directives — increment counter on each cited id.

    Returns (rows_updated, unknown_ids). Unknown ids include:
      * directive_id absent from cortex_directives entirely
      * directive_id present but matter_slug-scoped to a DIFFERENT matter
        (cross-matter citation hardening — prevents an AO cycle from
        incrementing MOVIE directive counters via fabricated id)

    `_global-*` ids bypass the matter_slug check (they apply across matters,
    matched against matter_slug='_global').
    """
    if counter_field not in {"helpful_count", "harmful_count", "stale_count"}:
        raise ValueError(
            f"counter_field must be one of helpful_count/harmful_count/"
            f"stale_count, got {counter_field!r}"
        )
    if not cited_ids:
        return 0, []

    global_ids = [d for d in cited_ids if d.startswith("_global-")]
    matter_ids = [d for d in cited_ids if not d.startswith("_global-")]

    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        raise RuntimeError("increment_counters: no DB connection")
    rows_updated = 0
    unknown: list[str] = []
    try:
        with conn.cursor() as cur:
            present: set[str] = set()
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
                # counter_field whitelisted above — safe to f-string interpolate.
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
        try:
            conn.rollback()
        except Exception:
            pass
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

    flagged_reason ∈ {'no_citation', 'unknown_directive_id',
    'malformed_citation'} per Brief 4 schema CHECK constraint.
    """
    if flagged_reason not in {
        "no_citation",
        "unknown_directive_id",
        "malformed_citation",
    }:
        raise ValueError(f"invalid flagged_reason: {flagged_reason!r}")

    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        raise RuntimeError("log_untraceable: no DB connection")
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
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        store._put_conn(conn)


# --------------------------------------------------------------------------
# Outcome classification
# --------------------------------------------------------------------------


def classify_triaga_outcome(
    director_action: Optional[str],
    age: timedelta,
) -> str:
    """Classify cycle outcome for counter routing.

    Returns one of: 'helpful', 'harmful', 'stale', 'pending'.
    Unknown director_action values default to 'pending' (safe non-action;
    classify_triaga_outcome upgrades when a known terminal value lands).
    """
    if director_action in TRIAGA_HELPFUL_VALUES:
        return "helpful"
    if director_action in TRIAGA_HARMFUL_VALUES:
        return "harmful"
    if director_action in TRIAGA_AMBIGUOUS_VALUES:
        return "pending"  # refresh_requested = re-run, not a final outcome
    if director_action is None and age >= timedelta(days=TRIAGA_TTL_DAYS):
        return "stale"
    return "pending"


# --------------------------------------------------------------------------
# Vault write
# --------------------------------------------------------------------------


def write_proposed_actions_to_vault(
    *,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    cited_ids: list[str],
    triaga_outcome: str,
    today_iso: str,
    staging_root: Optional[Path] = None,
) -> Path:
    """Append proposed-actions block to vault staging path (CHANDA #9).

    Path: {staging_root}/matters/{matter_slug}/proposed-config-deltas.md

    First write creates file with frontmatter that conforms to
    kbl/ingest_endpoint.validate_frontmatter (REQUIRED_KEYS:
    type/slug/name/updated/author/tags/related; type='matter'; voice='silver').
    Subsequent writes append a new cycle block. Mac Mini's vault mirror picks
    up new files on next sync.
    """
    root = staging_root if staging_root is not None else DEFAULT_STAGING_ROOT
    target = root / "matters" / matter_slug / "proposed-config-deltas.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    cited_str = ", ".join(cited_ids) if cited_ids else "_none — flagged untraceable_"
    block = (
        f"\n## Cycle {cycle_id} — {today_iso} ({triaga_outcome})\n\n"
        f"**Cited directives:** {cited_str}\n\n"
        f"### Proposal\n\n{(proposal_text or '').strip()}\n\n"
        f"---\n"
    )

    if not target.exists():
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


# --------------------------------------------------------------------------
# ClickUp write — DORMANT in V1 (Brief 5 deferred per Director 2026-04-30)
# --------------------------------------------------------------------------


def _is_clickup_write_enabled() -> bool:
    """Env-gate. V1: REFLECTOR_CLICKUP_WRITE stays false throughout.

    Future Brief 5 V2+ flips to true; the rest of write_proposed_actions_to_clickup
    remains intact so activation is a 1-line env flip.
    """
    return os.environ.get("REFLECTOR_CLICKUP_WRITE", "false").strip().lower() == "true"


def _load_clickup_contract(contract_path: Path) -> dict:
    """Parse Brief 5 surface contract (YAML embedded in markdown).

    V1 expectation: contract_path does not exist (Brief 5 deferred).
    Caller checks _is_clickup_write_enabled() first; this fn is only
    reached when env is enabled, so missing-contract returns {} and
    caller logs+skips.
    """
    if not contract_path.is_file():
        return {}
    import yaml  # local import — only loaded when ClickUp path active
    text = contract_path.read_text(encoding="utf-8")
    # Brief 5 contract has YAML inside a fenced block; extract first ```yaml block.
    fenced = re.search(r"```yaml\s*\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    body = fenced.group(1) if fenced else text
    try:
        parsed = yaml.safe_load(body)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as e:
        logger.warning(f"Failed to parse Brief 5 contract at {contract_path}: {e}")
        return {}


def _format_clickup_description(
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    cited_ids: list[str],
    triaga_outcome: str,
) -> str:
    """Plain-text task body for ClickUp Drafts & Deliverables list."""
    cited_str = ", ".join(cited_ids) if cited_ids else "(none — flagged untraceable)"
    return (
        f"Cortex cycle {cycle_id}\n"
        f"Matter: {matter_slug}\n"
        f"Outcome: {triaga_outcome}\n"
        f"Cited directives: {cited_str}\n\n"
        f"--- Proposal ---\n{(proposal_text or '').strip()[:8000]}\n"
    )


def write_proposed_actions_to_clickup(
    *,
    cycle_id: str,
    matter_slug: str,
    proposal_text: str,
    cited_ids: list[str],
    triaga_outcome: str,
    contract_path: Optional[Path] = None,
) -> Optional[str]:
    """Create per-matter ClickUp task — DORMANT in V1.

    Returns ClickUp task URL on success, None when:
      * REFLECTOR_CLICKUP_WRITE != 'true' (V1 default — primary gate)
      * Brief 5 contract not present (V1 default — Brief 5 deferred)
      * matter_slug not in contract list_map
      * BAKER_CLICKUP_READONLY kill switch trips inside ClickUpClient

    Counter routing follows directive-id provenance, NOT write-target surface.
    """
    if not _is_clickup_write_enabled():
        logger.info(
            "ClickUp write disabled (REFLECTOR_CLICKUP_WRITE != true) — vault-only"
        )
        return None

    cp = contract_path or (
        REPO_ROOT / "_ops" / "processes" / "cortex-clickup-surface-contract.md"
    )
    contract = _load_clickup_contract(cp)
    if not contract:
        logger.warning(
            "Brief 5 contract not found / empty at %s — ClickUp write skipped", cp
        )
        return None

    list_map = contract.get("list_map") or {}
    tag_only_matters = set(contract.get("tag_only_matters") or [])
    tag_only_routing = contract.get("tag_only_routing") or {}

    if matter_slug in tag_only_matters:
        parent_slug = tag_only_routing.get(matter_slug)
        entry = list_map.get(parent_slug) if parent_slug else None
    else:
        entry = list_map.get(matter_slug)

    if not entry:
        logger.warning(
            "matter %s not in Brief 5 contract list_map — skipping ClickUp",
            matter_slug,
        )
        return None
    list_id = entry.get("drafts_deliverables")
    if not list_id:
        logger.warning(
            "matter %s contract entry missing drafts_deliverables list_id",
            matter_slug,
        )
        return None

    try:
        from clickup_client import ClickUpClient
        client = ClickUpClient()
        task = client.create_task(
            list_id=list_id,
            name=f"Cortex proposal — {cycle_id[:8]} ({triaga_outcome})",
            description=_format_clickup_description(
                cycle_id, matter_slug, proposal_text, cited_ids, triaga_outcome
            ),
            tags=[
                "cortex_proposal",
                f"matter:{matter_slug}",
                f"outcome:{triaga_outcome}",
            ],
        )
    except Exception as e:
        logger.error(f"ClickUp create_task failed for cycle {cycle_id}: {e}")
        return None

    if not isinstance(task, dict):
        return None
    return task.get("url") or (f"https://app.clickup.com/t/{task['id']}" if task.get("id") else None)


# --------------------------------------------------------------------------
# Cycle reflection — counter increment + idempotency mark in single txn
# --------------------------------------------------------------------------


def _load_proposal_text(conn, cycle_id: str) -> str:
    """Read proposal_text from cortex_phase_outputs payload.

    Preference order:
      1. artifact_type='synthesis'     (Phase 3c output, full text)
      2. artifact_type='proposal_card' (Phase 4 output, fallback)

    `proposal_card` is truncated to [:8000] in cortex_phase4_proposal.py for
    Slack rendering; Phase 3c synthesizer can emit ~12K-16K chars and the
    Phase 4 prompt directs the model to place [directive: <id>] at the end —
    exactly the position the truncation would chop. Reflector parses the
    untruncated synthesis row to keep the citation intact.

    Caller passes a borrowed connection; this fn does NOT commit/rollback.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT payload FROM cortex_phase_outputs
             WHERE cycle_id = %s
               AND artifact_type IN ('proposal_card', 'synthesis')
             ORDER BY CASE artifact_type
                          WHEN 'synthesis'     THEN 0
                          WHEN 'proposal_card' THEN 1
                      END,
                      created_at DESC
             LIMIT 1
            """,
            (cycle_id,),
        )
        row = cur.fetchone()
    if not row:
        return ""
    payload = row[0]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return ""
    if not isinstance(payload, dict):
        return ""
    return payload.get("proposal_text") or ""


def reflect_cycle(
    *,
    cycle_id: str,
    matter_slug: str,
    director_action: Optional[str],
    started_at: datetime,
    proposal_text: Optional[str] = None,
    today_iso: Optional[str] = None,
    staging_root: Optional[Path] = None,
) -> dict:
    """Increment counters + write surfaces + mark cycle reflector_complete.

    Counter increment + idempotency-marker INSERT run in a SINGLE transaction
    (per python-backend rule + brief §3.5). The partial unique idx
    idx_cortex_phase_outputs_reflector_complete (Brief 4 §3.1 / migration
    20260430_cortex_directives.sql:89-91) prevents double-mark when two
    sweep firings collide on the same cycle (e.g., Render redeploy + cron
    tick on same minute).

    Returns dict: {outcome, cited_ids, unknown_ids, queue_id, vault_path,
                   clickup_url, already_reflected}.

    Caller (sweep_pending_cycles or runner Trigger A) is responsible for
    enumerating eligible cycles. This fn is the per-cycle unit of work.
    """
    today = today_iso or datetime.now(timezone.utc).date().isoformat()
    age = datetime.now(timezone.utc) - (
        started_at.astimezone(timezone.utc) if started_at.tzinfo else
        started_at.replace(tzinfo=timezone.utc)
    )
    outcome = classify_triaga_outcome(director_action, age)

    result = {
        "outcome": outcome,
        "cited_ids": [],
        "unknown_ids": [],
        "queue_id": None,
        "vault_path": None,
        "clickup_url": None,
        "already_reflected": False,
    }
    if outcome == "pending":
        # Not yet eligible — caller skips. Sweep filter should already
        # have excluded this; defensive no-op here.
        return result

    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        raise RuntimeError("reflect_cycle: no DB connection")
    try:
        with conn.cursor() as cur:
            # Pre-check idempotency: skip if already reflected. Cheap
            # SELECT before doing any work; the partial unique idx is
            # the durable guarantee against races.
            cur.execute(
                """
                SELECT 1 FROM cortex_phase_outputs
                 WHERE cycle_id = %s
                   AND artifact_type = %s
                """,
                (cycle_id, REFLECTOR_COMPLETE_ARTIFACT),
            )
            if cur.fetchone() is not None:
                result["already_reflected"] = True
                conn.commit()
                return result

        # Resolve proposal_text (lazily — only when actually reflecting).
        if proposal_text is None:
            proposal_text = _load_proposal_text(conn, cycle_id)

        valid, invalid, has_match = parse_citations(proposal_text)
        result["cited_ids"] = valid

        # ---- Counter increment + idempotency marker (single txn) ----
        with conn.cursor() as cur:
            unknown_in_db: list[str] = []
            if outcome in {"helpful", "harmful", "stale"} and valid:
                # Inline counter UPDATE (mirrors increment_counters_on_cited_directives
                # logic) so it's part of the same transaction as the
                # idempotency mark. Cross-matter scope check preserved.
                global_ids = [d for d in valid if d.startswith("_global-")]
                matter_ids = [d for d in valid if not d.startswith("_global-")]
                present: set[str] = set()
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
                    present.update(r[0] for r in cur.fetchall())
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
                    present.update(r[0] for r in cur.fetchall())
                unknown_in_db = [d for d in valid if d not in present]
                if present:
                    counter_field = {
                        "helpful": "helpful_count",
                        "harmful": "harmful_count",
                        "stale":   "stale_count",
                    }[outcome]
                    cur.execute(
                        f"""
                        UPDATE cortex_directives
                           SET {counter_field} = {counter_field} + 1,
                               updated_at = NOW()
                         WHERE directive_id = ANY(%s)
                        """,
                        (list(present),),
                    )
            result["unknown_ids"] = unknown_in_db

            # Idempotency marker: INSERT ON CONFLICT DO NOTHING. Partial
            # unique idx scopes uniqueness to artifact_type='reflector_complete'.
            marker_payload = {
                "reflected_at": datetime.now(timezone.utc).isoformat(),
                "outcome": outcome,
                "cited_ids": valid,
                "unknown_ids": unknown_in_db,
                "had_invalid_tokens": bool(invalid),
                "had_any_citation_match": has_match,
            }
            cur.execute(
                """
                INSERT INTO cortex_phase_outputs
                    (cycle_id, phase, phase_order, artifact_type, payload)
                VALUES (%s, 'archive', 6, %s, %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    cycle_id,
                    REFLECTOR_COMPLETE_ARTIFACT,
                    json.dumps(marker_payload),
                ),
            )
            if cur.rowcount == 0:
                # Concurrent sweep beat us to the marker — abort our
                # increments by raising; the outer except rolls back.
                raise RuntimeError(
                    f"cycle {cycle_id} reflected by concurrent sweep — rolling back"
                )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        store._put_conn(conn)

    # ---- Untraceable logging (separate txn — independent of counter txn) ----
    flagged_reason = _decide_flagged_reason(
        valid_ids=result["cited_ids"],
        invalid_tokens=invalid,
        has_match=has_match,
        unknown_ids=result["unknown_ids"],
    )
    if flagged_reason is not None:
        try:
            result["queue_id"] = log_untraceable_proposal(
                cycle_id=cycle_id,
                matter_slug=matter_slug,
                proposal_text=proposal_text or "",
                flagged_reason=flagged_reason,
            )
        except Exception as e:
            logger.error(
                f"prompt_review_queue insert failed for cycle {cycle_id}: {e}"
            )

    # ---- Vault write (V1 active write target) ----
    try:
        vault_path = write_proposed_actions_to_vault(
            cycle_id=cycle_id,
            matter_slug=matter_slug,
            proposal_text=proposal_text or "",
            cited_ids=result["cited_ids"],
            triaga_outcome=outcome,
            today_iso=today,
            staging_root=staging_root,
        )
        result["vault_path"] = str(vault_path)
    except Exception as e:
        logger.error(f"vault write failed for cycle {cycle_id}: {e}")

    # ---- ClickUp write (DORMANT in V1 — env-gated off) ----
    try:
        result["clickup_url"] = write_proposed_actions_to_clickup(
            cycle_id=cycle_id,
            matter_slug=matter_slug,
            proposal_text=proposal_text or "",
            cited_ids=result["cited_ids"],
            triaga_outcome=outcome,
        )
    except Exception as e:
        logger.error(f"ClickUp write failed for cycle {cycle_id}: {e}")

    # ---- Audit (CLAUDE.md hard rule) ----
    try:
        store.log_baker_action(
            action_type="cortex_reflector_complete",
            target_task_id=str(cycle_id),
            payload={
                "matter_slug": matter_slug,
                "outcome": outcome,
                "cited_ids": result["cited_ids"],
                "unknown_ids": result["unknown_ids"],
                "queue_id": result["queue_id"],
                "vault_path": result["vault_path"],
                "clickup_url": result["clickup_url"],
            },
            trigger_source="cortex_phase6_reflector",
            success=True,
        )
    except Exception as e:
        logger.warning(f"baker_actions audit failed for cycle {cycle_id}: {e}")

    return result


def _decide_flagged_reason(
    *,
    valid_ids: list[str],
    invalid_tokens: list[str],
    has_match: bool,
    unknown_ids: list[str],
) -> Optional[str]:
    """Decide prompt_review_queue.flagged_reason; None = no logging needed.

    Precedence (matches Brief §3 problem-set ordering):
      1. no_citation         — no [directive: ...] block at all
      2. malformed_citation  — block present but tokens fail kebab regex
      3. unknown_directive_id — valid format but absent from cortex_directives
                                (or matter-scope mismatch)
    """
    if not has_match:
        return "no_citation"
    if invalid_tokens and not valid_ids:
        return "malformed_citation"
    if invalid_tokens:
        # Mixed: some valid + some malformed. Surface as malformed for review.
        return "malformed_citation"
    if unknown_ids:
        return "unknown_directive_id"
    return None


# --------------------------------------------------------------------------
# Sweep — APScheduler entry point (Trigger B from brief §3.5)
# --------------------------------------------------------------------------


async def sweep_pending_cycles(
    *,
    limit: int = 100,
    staging_root: Optional[Path] = None,
) -> dict:
    """Find Reflector-eligible cycles + reflect each. Idempotent.

    Eligibility (REFLECTOR_ELIGIBLE_STATUSES):
      * cycle.status ∈ {proposed, tier_b_pending, approved, rejected, modified}
        AND
      * (director_action IS NOT NULL  -- Triaga decided
         OR started_at < now - TRIAGA_TTL_DAYS)  -- aged past TTL
        AND
      * NOT already reflected (no cortex_phase_outputs row with
        artifact_type='reflector_complete' for this cycle).

    Returns counts: {checked, reflected, helpful, harmful, stale, errors,
                     skipped_already_reflected}.
    """
    store = _get_store()
    conn = store._get_conn()
    if conn is None:
        return {"checked": 0, "reflected": 0, "errors": 1, "error": "no_db_conn"}

    cutoff_age = datetime.now(timezone.utc) - timedelta(days=TRIAGA_TTL_DAYS)
    cycles: list[tuple] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT cycle_id, matter_slug, started_at, director_action
                  FROM cortex_cycles
                 WHERE status = ANY(%s)
                   AND (director_action IS NOT NULL OR started_at < %s)
                   AND cycle_id NOT IN (
                       SELECT cycle_id FROM cortex_phase_outputs
                        WHERE artifact_type = 'reflector_complete'
                   )
                 ORDER BY started_at ASC
                 LIMIT %s
                """,
                (list(REFLECTOR_ELIGIBLE_STATUSES), cutoff_age, int(limit)),
            )
            cycles = list(cur.fetchall())
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"sweep enumerate failed: {e}")
        return {"checked": 0, "reflected": 0, "errors": 1, "error": str(e)[:200]}
    finally:
        store._put_conn(conn)

    counts = {
        "checked": len(cycles),
        "reflected": 0,
        "helpful": 0,
        "harmful": 0,
        "stale": 0,
        "errors": 0,
        "skipped_already_reflected": 0,
    }
    for cycle_id, matter_slug, started_at, director_action in cycles:
        try:
            res = reflect_cycle(
                cycle_id=str(cycle_id),
                matter_slug=matter_slug,
                director_action=director_action,
                started_at=started_at,
                staging_root=staging_root,
            )
        except Exception as e:
            counts["errors"] += 1
            logger.error(
                f"reflect_cycle failed for {cycle_id} ({matter_slug}): {e}"
            )
            continue
        if res.get("already_reflected"):
            counts["skipped_already_reflected"] += 1
        elif res.get("outcome") in {"helpful", "harmful", "stale"}:
            counts["reflected"] += 1
            counts[res["outcome"]] += 1
    logger.info(f"phase6_reflector_sweep: {counts}")
    return counts


def sweep_pending_cycles_sync(
    *,
    limit: int = 100,
    staging_root: Optional[Path] = None,
) -> dict:
    """Sync wrapper for APScheduler (BackgroundScheduler runs sync callables).

    Mirrors the pattern used by other sentinel jobs registered in
    triggers/embedded_scheduler.py.
    """
    import asyncio
    return asyncio.run(sweep_pending_cycles(limit=limit, staging_root=staging_root))
