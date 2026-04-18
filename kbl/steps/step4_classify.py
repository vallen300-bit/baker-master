"""Step 4 — deterministic policy classifier.

Consumes Step 3 output (``signal_queue.status='awaiting_classify'``),
reads the four prior-step columns (``triage_score``, ``primary_matter``,
``related_matters``, ``resolved_thread_paths``), evaluates the §4.5
first-match-wins decision table, and writes ``step_5_decision`` plus a
``cross_link_hint`` flag for Step 6. Then advances state to
``awaiting_opus`` (or ``classify_failed`` on unexpected preconditions).

No Ollama call, no Anthropic call, no Voyage call, no cost ledger row —
Step 4 is pure Python policy. The only I/O beyond PostgreSQL is one
``load_hot_md()`` read per invocation so the ACTIVE-matter allowlist
tracks the Director's priorities live.

CHANDA compliance:
    - **Q1 Loop Test.** Step 4 reads ``hot.md`` on every ``classify()``
      call via ``_load_allowed_scope`` — this is **Leg 3** read surface,
      same invariant as Step 1. Fresh read per invocation, no module-
      level cache. Explicit test enforces.
    - **Q2 Wish Test.** The hot.md ACTIVE set gates which signals spend
      Opus tokens — deterministic policy serves the wish (Director's
      priorities decide cost).
    - **Inv 3 (fresh read per invocation).** No caching across calls.
    - **Inv 6 (pipeline never skips Step 6).** Every classify outcome
      advances state; ``SKIP_INBOX`` still writes ``step_5_decision``
      so Step 5 claims the row and writes its stub. The signal flows
      through Step 6 regardless.
    - **Inv 10.** No prompt, no model — enum + table are stable code.

State transitions:
    awaiting_classify  -->  classify_running  -->  awaiting_opus
                                              \\->  classify_failed
                                                      (ClassifyError only)
"""
from __future__ import annotations

import json
import logging
import os
import re
from enum import Enum
from typing import Any, Optional

from kbl.exceptions import ClassifyError
from kbl.loop import load_hot_md

logger = logging.getLogger(__name__)

# ---------------------------- constants ----------------------------

_TRIAGE_THRESHOLD_ENV = "KBL_PIPELINE_TRIAGE_THRESHOLD"
_DEFAULT_TRIAGE_THRESHOLD = 40

_NOISE_BAND_ENV = "KBL_STEP4_NOISE_BAND"
_DEFAULT_NOISE_BAND = 5

_SCOPE_OVERRIDE_ENV = "KBL_MATTER_SCOPE_ALLOWED"

_STATE_RUNNING = "classify_running"
_STATE_NEXT = "awaiting_opus"
_STATE_FAILED = "classify_failed"

# hot.md parse targets. Matches the `## Actively pressing` section then
# pulls slug tokens from each `**<slug>**:` line that follows, up to the
# next H2 heading. Tolerant of surrounding whitespace and Unicode dashes.
_ACTIVE_SECTION_RE = re.compile(
    r"^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_ACTIVE_SLUG_LINE_RE = re.compile(
    r"^\s*[-*]?\s*\*\*(?P<slug>[A-Za-z0-9_\-]+)\*\*\s*:",
    re.MULTILINE,
)


# ---------------------------- decision enum ----------------------------


class ClassifyDecision(str, Enum):
    """The four Step 5 routing decisions.

    Python 3.9-compatible ``str, Enum`` mixin — instances compare equal
    to their string value so a row round-tripped through PG TEXT still
    matches ``ClassifyDecision.FULL_SYNTHESIS == 'full_synthesis'``.

    Note: ``CROSS_LINK_ONLY`` is reserved for Phase 2 completeness.
    **No decision rule currently maps to this value.** The §4.5 decision
    table only produces the other three. A future policy iteration may
    surface it; until then the classifier asserts it's never emitted.
    """

    FULL_SYNTHESIS = "full_synthesis"
    STUB_ONLY = "stub_only"
    CROSS_LINK_ONLY = "cross_link_only"  # Phase 2 — unreachable today
    SKIP_INBOX = "skip_inbox"


# ---------------------------- env readers ----------------------------


def _get_triage_threshold() -> int:
    """Match Step 1's env-read pattern exactly — same env var, same
    fallback to 40. Step 4 must NOT drift."""
    raw = os.environ.get(_TRIAGE_THRESHOLD_ENV)
    if raw is None or raw == "":
        return _DEFAULT_TRIAGE_THRESHOLD
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_TRIAGE_THRESHOLD


def _get_noise_band() -> int:
    """``KBL_STEP4_NOISE_BAND``, default 5. Malformed int → fallback + WARN."""
    raw = os.environ.get(_NOISE_BAND_ENV)
    if raw is None or raw == "":
        return _DEFAULT_NOISE_BAND
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "invalid %s=%r — falling back to default %d",
            _NOISE_BAND_ENV,
            raw,
            _DEFAULT_NOISE_BAND,
        )
        return _DEFAULT_NOISE_BAND


def _get_scope_env_override() -> frozenset[str]:
    """Parse the optional comma-separated override. Empty / unset / all-
    whitespace → empty set (hot.md is then the sole scope source)."""
    raw = os.environ.get(_SCOPE_OVERRIDE_ENV, "")
    if not raw.strip():
        return frozenset()
    tokens = (t.strip() for t in raw.split(","))
    return frozenset(t for t in tokens if t)


# ---------------------------- allowed-scope loader ----------------------------


def _parse_hot_md_active(hot_md_content: Optional[str]) -> frozenset[str]:
    """Extract ``**<slug>**:`` tokens from the ``## Actively pressing``
    section of ``hot.md``. Returns empty set when the file / section is
    missing (valid zero-Gold state per Inv 1 — every signal then fails
    Rule 1 and routes to ``SKIP_INBOX``, which is the documented default
    when the Director hasn't declared priorities)."""
    if not hot_md_content:
        return frozenset()
    section = _ACTIVE_SECTION_RE.search(hot_md_content)
    if not section:
        return frozenset()
    return frozenset(
        m.group("slug").lower().strip()
        for m in _ACTIVE_SLUG_LINE_RE.finditer(section.group("body"))
    )


def _load_allowed_scope() -> frozenset[str]:
    """Compute the per-invocation allowlist.

    Union of ``KBL_MATTER_SCOPE_ALLOWED`` (if set) and the ACTIVE matters
    parsed from ``hot.md``. Called once per ``classify()`` invocation —
    **NOT cached module-level**. Inv 3: the Director's live priorities
    must propagate to the next signal without a process restart.

    Zero-Gold safe: missing hot.md / missing ``## Actively pressing``
    section / empty env override all collapse to ``frozenset()``. Under
    that state Rule 1 fires for every signal with a non-null primary
    matter and routes to ``SKIP_INBOX``.
    """
    hot_md = load_hot_md()
    return _parse_hot_md_active(hot_md) | _get_scope_env_override()


# ---------------------------- row access helpers ----------------------------


def _coerce_list(value: Any) -> list[Any]:
    """``related_matters`` is TEXT[] (driver → list[str]). Older rows may
    surface as JSON-encoded strings; normalize defensively."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _fetch_signal_row(
    conn: Any, signal_id: int
) -> tuple[int, Optional[str], list[str], list[str]]:
    """Return ``(triage_score, primary_matter, related_matters,
    resolved_thread_paths)``. Raises ``LookupError`` when absent.

    ``triage_score`` is NUMERIC in the schema; cast to int for the
    decision comparisons. A ``NULL`` score defaults to 0 to force the
    ``STUB_ONLY`` rule — safer than hitting the unreachable branch."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT triage_score, primary_matter, related_matters, "
            "       resolved_thread_paths "
            "FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"signal_queue row not found: id={signal_id}")
    score_raw, primary_matter, related_raw, resolved_raw = row
    score = int(score_raw) if score_raw is not None else 0
    related = [str(s) for s in _coerce_list(related_raw)]
    resolved = [str(s) for s in _coerce_list(resolved_raw)]
    return score, primary_matter, related, resolved


def _mark_running(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_RUNNING, signal_id),
        )


def _write_decision(
    conn: Any,
    signal_id: int,
    decision: ClassifyDecision,
    cross_link_hint: bool,
    next_state: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET "
            "  step_5_decision = %s, "
            "  cross_link_hint = %s, "
            "  status = %s "
            "WHERE id = %s",
            (decision.value, cross_link_hint, next_state, signal_id),
        )


def _mark_failed(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_FAILED, signal_id),
        )


# ---------------------------- decision table ----------------------------


def _evaluate_rules(
    triage_score: int,
    primary_matter: Optional[str],
    related_matters: list[str],
    resolved_thread_paths: list[str],
    allowed_scope: frozenset[str],
    threshold: int,
    noise_band: int,
) -> tuple[ClassifyDecision, bool]:
    """Pure §4.5 table evaluator. Returns ``(decision, cross_link_hint)``.

    First-match-wins. The edge-row 6 (``triage_score < THRESHOLD``) is
    unreachable by construction — Step 1 already routed low-score signals
    to ``routed_inbox`` so they never get ``awaiting_classify`` status.
    If Step 4 encounters it anyway, that's a pipeline-invariant failure:
    raise ``ClassifyError`` so the caller transitions the row to
    ``classify_failed`` and halts rather than guessing silently.
    """
    # Rule 0 (unreachable guard): below-threshold scores should never
    # reach Step 4. See §4.5 edge row.
    if triage_score < threshold:
        raise ClassifyError(
            f"triage_score={triage_score} < THRESHOLD={threshold} — "
            "Step 1 should have routed this to 'routed_inbox'; "
            "pipeline invariant violated"
        )

    # Rule 1 — Layer 2 scope gate.
    if primary_matter is None or primary_matter not in allowed_scope:
        return ClassifyDecision.SKIP_INBOX, False

    # Rule 2 — noise band (score just above threshold but not confident
    # enough to spend Opus tokens on).
    if triage_score < threshold + noise_band:
        return ClassifyDecision.STUB_ONLY, False

    # Rules 3, 4, 5 — all produce FULL_SYNTHESIS; cross_link_hint only
    # on Rule 4 (new arc with related matters but no prior thread).
    if not resolved_thread_paths:
        if related_matters:
            # Rule 4: new arc + cross-links.
            return ClassifyDecision.FULL_SYNTHESIS, True
        # Rule 3: pure new arc.
        return ClassifyDecision.FULL_SYNTHESIS, False
    # Rule 5: continuation (paths non-empty).
    return ClassifyDecision.FULL_SYNTHESIS, False


# ---------------------------- pipeline entry ----------------------------


def classify(signal_id: int, conn: Any) -> ClassifyDecision:
    """Run Step 4 for a single signal.

    Full side-effect path: fetch prior-step columns, mark running, load
    live allowed-scope (hot.md + env), evaluate the first-match-wins
    decision table, write the decision + cross-link hint, advance state.

    Raises:
        LookupError: signal_id absent from ``signal_queue``.
        ClassifyError: a pipeline-invariant precondition failed (e.g.
            below-threshold score reached Step 4). Signal status is
            set to ``classify_failed`` before the exception bubbles so
            the operator sees the halt surface.
    """
    score, primary_matter, related, resolved = _fetch_signal_row(conn, signal_id)
    _mark_running(conn, signal_id)

    # Inv 3: fresh read per invocation. Not module-level cached.
    allowed = _load_allowed_scope()
    threshold = _get_triage_threshold()
    noise_band = _get_noise_band()

    try:
        decision, cross_link_hint = _evaluate_rules(
            triage_score=score,
            primary_matter=primary_matter,
            related_matters=related,
            resolved_thread_paths=resolved,
            allowed_scope=allowed,
            threshold=threshold,
            noise_band=noise_band,
        )
    except ClassifyError:
        _mark_failed(conn, signal_id)
        raise

    # Phase 2 safety check — the enum carries an unreachable member
    # (CROSS_LINK_ONLY) for future expansion. Fail loud if the table
    # ever surfaces it before the Phase 2 policy lands.
    if decision is ClassifyDecision.CROSS_LINK_ONLY:
        _mark_failed(conn, signal_id)
        raise ClassifyError(
            "CROSS_LINK_ONLY is a Phase 2 reserved decision; no Phase 1 "
            "rule maps to it. Evaluator emitted it — check decision table."
        )

    # Rule 1 (Layer 2 gate) informational log — no other per-call log.
    if decision is ClassifyDecision.SKIP_INBOX:
        logger.info(
            "layer2_blocked: primary_matter=%r not in allowed=%s",
            primary_matter,
            sorted(allowed),
        )

    _write_decision(conn, signal_id, decision, cross_link_hint, _STATE_NEXT)
    return decision
