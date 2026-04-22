"""Step 5 — Claude Opus synthesis (cloud Anthropic API).

Consumes Step 4 output (``signal_queue.status='awaiting_opus'`` rows),
reads the full prior-step column set + Leg 1 Gold context + Leg 3 hot.md
and feedback ledger, assembles the §1 prompt per B3's spec (authored at
``briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md``, slug-v9-folded at
``50167a1``), and writes the Silver draft to ``opus_draft_markdown``.

Three routing paths gated by ``signal_queue.step_5_decision`` (from Step 4):

    ``SKIP_INBOX``     -> deterministic skip stub, NO Opus call, NO ledger row
    ``STUB_ONLY``      -> deterministic stub body (``status: stub_auto``
                           frontmatter marker), NO Opus call, NO ledger row
    ``FULL_SYNTHESIS`` -> full Opus call path (cost gate → call → write)

``CROSS_LINK_ONLY`` is reserved for Phase 2; Step 4's guard raises
``ClassifyError`` before it ever reaches Step 5, so this module doesn't
handle it.

CHANDA compliance:
    - **Q1 Loop Test.** All three Legs are touched:
      * **Leg 1** — ``load_gold_context_by_matter`` called on every
        FULL_SYNTHESIS. Zero-Gold returns empty string per Inv 1;
        caller substitutes the "no prior Gold" sentinel and the prompt
        handles it (G2 rule).
      * **Leg 2** — No feedback_ledger WRITE from Step 5. Ledger
        writes are Director-action territory (KBL-C). Read-only here.
      * **Leg 3** — ``load_hot_md()`` + ``load_recent_feedback()``
        called on every synthesize() invocation. Fresh read, no
        cache. Explicit test enforces (Inv 3).
    - **Q2 Wish Test.** Opus is the Silver-writer whose output the
      Director reviews + promotes. Cost gate keeps spend honest;
      prompt-caching on the stable system block keeps input cost down.
    - **Inv 1 (zero-Gold safe).** An empty Gold corpus produces a valid
      Opus-callable prompt; G2 rule handles it in the model.
    - **Inv 6 (pipeline never skips Step 6).** Every routing path
      writes ``opus_draft_markdown`` and advances to
      ``awaiting_finalize``, so Step 6 claims the row. SKIP_INBOX +
      STUB_ONLY advance via the stub path, not the Opus path.
    - **Inv 8 (voice: silver + author: pipeline).** All deterministic
      stubs hard-code these frontmatter values. The Opus prompt enforces
      them via rules F1/F2. Never Gold, never Director.
    - **Inv 10 (template stability).** Prompt files are code, loaded
      once per process from ``kbl/prompts/step5_opus_{system,user}.txt``.
      Variation happens in data blocks only.

State transitions:
    awaiting_opus  -->  opus_running  -->  awaiting_finalize    (happy)
                                      \\->  opus_failed          (R3 exhausted)
                                      \\->  paused_cost_cap      (gate denied)

R3 retry ladder (§8 of KBL-B brief):
    Attempt 1 — identical prompt (transient failure recovery)
    Attempt 2 — pared prompt (drops feedback_ledger_recent block)
    Attempt 3 — minimal prompt (drops ledger + hot.md; keeps signal +
                entities + Gold context)
    After attempt 3 fail -> opus_failed terminal for this step (caller
    pipeline_tick routes to inbox per §7).

    ``AnthropicUnavailableError`` triggers the next retry. ``OpusRequestError``
    (4xx bad-request / auth / invalid model) bypasses R3 — retrying the
    same malformed prompt will not recover — and goes straight to
    opus_failed.

Transaction-boundary contract (Task K YELLOW remediation, 2026-04-19):

    This module follows the caller-owns-commit pattern. ``synthesize()``
    performs all its DB writes (state UPDATE, cost_ledger INSERT,
    column writes) but does NOT call ``conn.commit()``. The caller
    (``kbl.pipeline_tick._process_signal``) handles the BEGIN / COMMIT /
    ROLLBACK boundaries so state + draft + ledger land atomically.

    One exception: the ``opus_failed`` and ``paused_cost_cap`` status
    flips that precede an exception raise DO commit inside synthesize()
    — commit-before-raise makes the terminal state durable so the
    operator sees the halt surface. This mirrors Step 1 / Step 4's
    terminal-state-flip pattern and is documented in the relevant code
    path.
"""
from __future__ import annotations

import logging as _stdlib_logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import yaml

from kbl import slug_registry
from kbl.anthropic_client import OpusResponse, call_opus
from kbl.cost_gate import (
    CostDecision,
    can_fire_step5,
    record_opus_failure,
    record_opus_success,
)
from kbl.exceptions import (
    AnthropicUnavailableError,
    KblError,
    OpusRequestError,
)
from kbl.loop import (
    load_gold_context_by_matter,
    load_hot_md,
    load_recent_feedback,
    render_ledger,
)
from kbl.steps.step4_classify import ClassifyDecision

logger = _stdlib_logging.getLogger(__name__)

# ---------------------------- constants ----------------------------

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
_SYSTEM_TEMPLATE_PATH = _PROMPTS_DIR / "step5_opus_system.txt"
_USER_TEMPLATE_PATH = _PROMPTS_DIR / "step5_opus_user.txt"

_STATE_RUNNING = "opus_running"
_STATE_NEXT = "awaiting_finalize"
_STATE_FAILED = "opus_failed"
_STATE_PAUSED = "paused_cost_cap"

_MAX_SIGNAL_CHARS = 50_000
_SIGNAL_TRUNC_MARKER = (
    "\n\n[SIGNAL TRUNCATED @ 50000 chars — see source for full text]"
)

# R3 ladder — 3 attempts (index 0, 1, 2) per §8 brief.
_R3_IDENTICAL = 0
_R3_PARED = 1
_R3_MINIMAL = 2
_R3_MAX_ATTEMPTS = 3

_LEDGER_OMITTED_MARKER = "(feedback ledger omitted — R3 pared retry)"
_LEDGER_HOT_OMITTED_MARKER = (
    "(hot.md + feedback ledger omitted — R3 minimal retry)"
)
_HOT_MD_OMITTED_MARKER = "(hot.md omitted — R3 minimal retry)"

_MAX_TOKENS_DEFAULT = 4096

# Sentinel blocks per B3 §1.2 G2 rule. Stable shape helps prompt caching.
_GOLD_ZERO_MATTER_SENTINEL = "(no prior Gold entries for this matter)"
_GOLD_NULL_MATTER_SENTINEL = (
    "(primary_matter is null — no matter-scoped Gold to read)"
)
_HOT_MD_FALLBACK = "(no current-priorities cache available)"
_LEDGER_FALLBACK = "(no recent Director actions)"
_THREAD_PATHS_NONE = "(none — new thread)"

# Step 5 decision values (string form — Step 4 writes these to the DB).
_DECISION_FULL = ClassifyDecision.FULL_SYNTHESIS.value
_DECISION_STUB = ClassifyDecision.STUB_ONLY.value
_DECISION_SKIP = ClassifyDecision.SKIP_INBOX.value

# Schema conformance bounds for stub bodies (STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1).
# SilverDocument._body_length: 300 ≤ len(body) ≤ 8000.
# SilverDocument._stub_status_matches_shape: status set ⇒ body ≤ 600.
# Stub writers enforce the tighter 300-600 envelope structurally.
_STUB_BODY_MIN_CHARS = 300
_STUB_BODY_MAX_CHARS = 600

# Valid vedana values per SilverFrontmatter (kbl/schemas/silver.py Vedana).
# Step 4 is supposed to write one of these into signal_queue.vedana; if it
# drifts (e.g. "neutral" from an older step4 build, or NULL from a
# pre-classified row the stub path processed), stub writers coerce to
# "routine" rather than emit a pydantic-invalid stub that would trigger
# an unhelpful R3 retry ladder (R3 can't recover deterministic data drift).
_VALID_VEDANA = {"threat", "opportunity", "routine"}


# ---------------------------- result dataclass ----------------------------


@dataclass(frozen=True)
class SynthesisResult:
    """Caller-visible outcome of synthesize().

    ``decision`` is the step_5_decision value that routed this signal.
    ``terminal_state`` is the status the signal now sits in. On happy
    paths this is ``awaiting_finalize``; on R3-exhausted it's
    ``opus_failed``; on cost-gate denial it's ``paused_cost_cap``.

    ``opus_response`` is present only on FULL_SYNTHESIS paths that
    actually called Opus (including a failing path that hit R3 ladder
    at least once). Stub paths leave it None.

    ``cost_usd`` records what was ACTUALLY spent. Deterministic stubs
    are zero; R3-partial failures sum actual attempted costs.
    """

    decision: str
    terminal_state: str
    opus_response: Optional[OpusResponse]
    cost_usd: Decimal


# ---------------------------- template loading ----------------------------


_system_template_cache: Optional[str] = None
_user_template_cache: Optional[str] = None


def _load_system_template() -> str:
    """Inv 10 — template is code. Loaded once per process."""
    global _system_template_cache
    if _system_template_cache is None:
        _system_template_cache = _SYSTEM_TEMPLATE_PATH.read_text(encoding="utf-8")
    return _system_template_cache


def _load_user_template() -> str:
    global _user_template_cache
    if _user_template_cache is None:
        _user_template_cache = _USER_TEMPLATE_PATH.read_text(encoding="utf-8")
    return _user_template_cache


def _reset_template_cache_for_tests() -> None:
    """Test hook — drops both caches so fixtures can override."""
    global _system_template_cache, _user_template_cache
    _system_template_cache = None
    _user_template_cache = None


# ---------------------------- signal + prior-step loader ----------------------------


@dataclass(frozen=True)
class _SignalInputs:
    """Snapshot of the prior-step columns Step 5 needs for synthesis.

    Private to this module — callers receive ``SynthesisResult`` at the
    public boundary. Kept frozen so the R3 ladder can re-feed the same
    data into the builder across attempts without state drift.
    """

    signal_id: int
    raw_content: str
    source: str
    primary_matter: Optional[str]
    related_matters: list[str]
    vedana: Optional[str]
    triage_summary: str
    resolved_thread_paths: list[str]
    extracted_entities: dict
    step_5_decision: Optional[str]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return []


def _fetch_signal_inputs(conn: Any, signal_id: int) -> _SignalInputs:
    """One SELECT pulls every prior-step column. No partial loading.

    Raises ``LookupError`` on missing row — pipeline_tick catches and
    routes. Missing individual fields (nulls) stay as Python None and
    the prompt builder substitutes sentinels.

    STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 (2026-04-21): the bridge
    (``kbl/bridge/alerts_to_signal.py``) writes body text into
    ``payload->>'alert_body'`` — there is no ``raw_content`` column. The
    COALESCE ladder is a SAFETY NET, not a cover-up: a future producer
    writing to a new canonical column should surface as an alignment
    error, not silently fall back.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(payload->>'alert_body', summary, '') AS raw_content, "
            "       source, primary_matter, related_matters, "
            "       vedana, triage_summary, resolved_thread_paths, "
            "       extracted_entities, step_5_decision "
            "FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"signal_queue row not found: id={signal_id}")

    (
        raw_content,
        source,
        primary_matter,
        related_matters,
        vedana,
        triage_summary,
        resolved_thread_paths,
        extracted_entities,
        step_5_decision,
    ) = row

    return _SignalInputs(
        signal_id=signal_id,
        raw_content=raw_content or "",
        source=source or "",
        primary_matter=primary_matter,
        related_matters=[str(s) for s in _as_list(related_matters)],
        vedana=vedana,
        triage_summary=triage_summary or "",
        resolved_thread_paths=[str(s) for s in _as_list(resolved_thread_paths)],
        extracted_entities=extracted_entities if isinstance(extracted_entities, dict) else {},
        step_5_decision=step_5_decision,
    )


# ---------------------------- SQL writers ----------------------------


def _mark_running(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_RUNNING, signal_id),
        )


def _write_draft_and_advance(
    conn: Any, signal_id: int, draft_markdown: str, next_state: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET "
            "  opus_draft_markdown = %s, "
            "  status = %s "
            "WHERE id = %s",
            (draft_markdown, next_state, signal_id),
        )


def _mark_terminal(conn: Any, signal_id: int, state: str) -> None:
    """Flip to a terminal state (``opus_failed`` / ``paused_cost_cap``)
    WITHOUT writing a draft — used on R3 exhaustion + cost-gate denial.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (state, signal_id),
        )


def _write_cost_ledger(
    conn: Any,
    signal_id: int,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    cost_usd: Decimal,
    success: bool,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """One INSERT per Opus call (incl. failed attempts). Step 5's step
    label is ``opus_step5`` per the KBL-A schema convention."""
    metadata = {
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
    }
    import json

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO kbl_cost_ledger "
            "(signal_id, step, model, input_tokens, output_tokens, "
            " latency_ms, cost_usd, success, metadata) "
            "VALUES (%s, 'opus_step5', %s, %s, %s, %s, %s, %s, %s::jsonb)",
            (
                signal_id,
                model_id,
                input_tokens,
                output_tokens,
                latency_ms,
                cost_usd,
                success,
                json.dumps(metadata),
            ),
        )


# ---------------------------- deterministic stub writers ----------------------------


def _iso_utc_now() -> str:
    """Frontmatter-safe UTC timestamp. Matches B3 Example 1 shape."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _dump_stub_frontmatter(fm: dict[str, Any]) -> str:
    """Serialize a stub-frontmatter mapping to a ``---``-fenced YAML block.

    Uses ``yaml.safe_dump`` so scalars with YAML-special characters
    (``:``, ``#``, leading ``-``, leading ``!``, newlines, quotes, etc.)
    are auto-quoted. The raw f-string concat previously used here
    produced malformed YAML whenever any field contained a colon —
    e.g. ``title: Layer 2 gate: matter not in current scope`` was
    parsed as a mapping-inside-a-mapping and Step 6's
    ``_split_frontmatter`` raised ``FinalizationError`` with "mapping
    values are not allowed here" (STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1,
    2026-04-21).

    Field order is load-bearing and must match the f-string concat
    that shipped pre-fix — Step 6 / Director eye / snapshot tests all
    rely on the sequence (``title`` → ``voice`` → ``author`` →
    ``created`` → ``source_id`` → ``primary_matter`` →
    ``related_matters`` → ``vedana`` → ``status``). ``sort_keys=False``
    enforces it.
    """
    yaml_text = yaml.safe_dump(
        fm,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n"


def _normalize_stub_inputs(
    inputs: _SignalInputs,
) -> tuple[Optional[str], list[str], str]:
    """Coerce producer-side drift into schema-conformant values.

    STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1 (2026-04-22): stubs are the
    deterministic last line of defense before Step 6 Pydantic validation.
    They must emit frontmatter that ALWAYS validates, so every
    ``SilverFrontmatter`` cross-field invariant gets enforced here:

    * **Slug registry membership** — filter ``primary_matter`` and
      ``related_matters`` to the ACTIVE set. A slug retired between Step
      1 and Step 5 (or written in error by a prior-step drift) would
      fail ``MatterSlug`` validation; demoting to ``None`` / dropping
      from related is strictly better than stranding the row.
    * **Invariant §4.2** (null-primary ⇒ empty-related) — if primary
      drops to ``None`` (unset or retired), force ``related=[]``.
    * **Invariant no-primary-in-related** — dedupe + order-preserving.
    * **Vedana Literal** — coerce anything outside the canonical set
      to ``"routine"`` so the stub still emits.

    Returns ``(primary, related, vedana)``. Callers use these; no other
    producer-side normalization happens in the stub writers.
    """
    from kbl import slug_registry as _reg

    active = _reg.active_slugs()

    primary = inputs.primary_matter
    if primary is not None and primary not in active:
        primary = None

    related = [s for s in inputs.related_matters if s in active]
    # Invariant §4.2.
    if primary is None:
        related = []
    # no-primary-in-related + order-preserving dedupe.
    seen: set[str] = set()
    if primary is not None:
        seen.add(primary)
    deduped: list[str] = []
    for slug in related:
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(slug)
    related = deduped

    vedana = inputs.vedana if inputs.vedana in _VALID_VEDANA else "routine"

    return primary, related, vedana


def _normalize_stub_title(raw_title: str, *, fallback: str) -> str:
    """Coerce a candidate title into the SilverFrontmatter._title_shape envelope.

    Strip whitespace, trim trailing periods (the validator rejects
    period-terminal titles), cap at 160 chars (schema max), fall back
    to ``fallback`` when empty after normalization. Does NOT enforce
    YAML-safe escaping — ``yaml.safe_dump`` handles that at emit time.
    """
    trimmed = raw_title.strip().rstrip(". \t")
    if not trimmed:
        return fallback
    if len(trimmed) > 160:
        trimmed = trimmed[:160].rstrip(". \t")
        if not trimmed:
            return fallback
    return trimmed


def _pad_stub_body(body: str, filler: str) -> str:
    """Pad ``body`` so ``len(body) >= _STUB_BODY_MIN_CHARS``.

    The filler is appended verbatim (separated by ``\\n\\n``) until the
    300-char floor is met. Both stubs ship with filler prose that's
    Director-visible context (not lorem ipsum) — see the stub body
    constants. Returns the padded body; never truncates here (the cap
    is applied by ``_cap_stub_body``).
    """
    if len(body) >= _STUB_BODY_MIN_CHARS:
        return body
    needed = _STUB_BODY_MIN_CHARS - len(body)
    # Append filler once; if still short, repeat (belt-and-suspenders
    # against a zero-length filler edit).
    padded = body.rstrip() + "\n\n" + filler.strip()
    while len(padded) < _STUB_BODY_MIN_CHARS and filler.strip():
        padded += " " + filler.strip()
    del needed
    return padded


def _cap_stub_body(body: str) -> str:
    """Cap a stub body at ``_STUB_BODY_MAX_CHARS`` per SilverDocument
    ``_stub_status_matches_shape`` (status set ⇒ body ≤ 600).

    Trims on a word boundary when possible so the cut doesn't slice a
    token; ellipsis is appended only if the body was actually trimmed.
    """
    if len(body) <= _STUB_BODY_MAX_CHARS:
        return body
    # Reserve 3 chars for the trailing ellipsis marker so the final
    # string still fits under _STUB_BODY_MAX_CHARS.
    budget = _STUB_BODY_MAX_CHARS - 3
    cut = body[:budget]
    last_space = cut.rfind(" ")
    if last_space > budget - 80:  # don't cut on a word boundary more than 80 chars back
        cut = cut[:last_space]
    return cut.rstrip() + "..."


def _build_stub_frontmatter_dict(
    inputs: _SignalInputs,
    *,
    title: str,
    primary: Optional[str],
    related: list[str],
    vedana: str,
) -> dict[str, Any]:
    """Assemble the ordered dict shared by both deterministic stubs.

    ``primary``/``related``/``vedana`` come pre-normalized from
    :func:`_normalize_stub_inputs` — the stub writers do NOT pass raw
    ``inputs.*`` fields here. This centralizes the invariant-enforcement
    contract at a single point (test once, trust everywhere).

    ``source_id`` is cast to ``str`` to match
    ``SilverFrontmatter.source_id: str`` in ``kbl/schemas/silver.py``.
    Pydantic v2 default mode does not coerce ``int → str``; prior to
    STEP5_STUB_SOURCE_ID_TYPE_FIX_1 (2026-04-21 evening) the stub wrote
    ``inputs.signal_id`` as raw ``int`` which serialized as unquoted
    YAML ``17`` and parsed back as Python ``int``, triggering
    ``ValidationError: source_id: Input should be a valid string`` at
    Step 6 Pydantic validation. Defense-in-depth: Step 6's ``finalize()``
    also force-sets ``fm_dict['source_id'] = str(row.signal_id)`` before
    validation so any future producer that forgets the cast still
    advances.
    """
    return {
        "title": title,
        "voice": "silver",
        "author": "pipeline",
        "created": _iso_utc_now(),
        "source_id": str(inputs.signal_id),
        "primary_matter": primary,
        "related_matters": list(related),
        "vedana": vedana,
        "status": "stub_auto",
    }


# IMPORTANT: stub filler text must not contain the literal strings
# ``voice: gold`` or ``author: director`` — ``SilverDocument._no_gold_self_promotion``
# (R18 body validator) rejects any body that does, which would cascade
# the stub right back into the ``opus_failed`` route we're trying to
# avoid. Phrased with neutral descriptions of the promotion action instead.
_SKIP_INBOX_BODY_FILLER = (
    "No Opus synthesis was performed on this signal because the matter "
    "slug falls outside the Director's current working set. To route "
    "this into the pipeline proper, add the matter to `hot.md` ACTIVE "
    "or to the `KBL_MATTER_SCOPE_ALLOWED` env override and re-queue the "
    "signal. The raw signal text is preserved in `signal_queue.payload` "
    "for audit. This is a deterministic stub, not an LLM output — any "
    "promotion to canonical status requires an explicit Director edit "
    "to the frontmatter `voice`/`author` fields."
)

_STUB_ONLY_BODY_FILLER = (
    "This signal landed in the triage noise band — above the hard "
    "skip threshold but below the Opus-worthy bar. Rather than burn "
    "Anthropic spend on a low-signal synthesis, Step 5 emitted this "
    "deterministic stub for Director review. Promotion is an explicit "
    "frontmatter edit to the canonical `voice`/`author` fields; leave "
    "untouched to archive. No cross-link writes were queued. The raw "
    "signal text lives in `signal_queue.payload` for audit."
)


def _build_skip_inbox_stub(inputs: _SignalInputs) -> str:
    """Deterministic stub for Rule 1 (Layer 2 gate) rows. ``status:
    stub_auto`` frontmatter flag tells Director this is auto-generated,
    not Opus output.

    Frontmatter is emitted via ``yaml.safe_dump`` (see
    ``_dump_stub_frontmatter``) — the literal title contains a colon
    so raw f-string concat would have produced malformed YAML.

    STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1 (2026-04-22): inputs are
    normalized via :func:`_normalize_stub_inputs` so §4.2 + slug
    registry invariants are enforced structurally. Body is padded to
    the 300-char floor required by ``SilverDocument._body_length`` and
    capped at the 600-char ceiling required by
    ``_stub_status_matches_shape``.
    """
    primary, related, vedana = _normalize_stub_inputs(inputs)
    title = _normalize_stub_title(
        "Layer 2 gate: matter not in current scope",
        fallback="Layer 2 gate: matter not in current scope",
    )
    fm = _build_stub_frontmatter_dict(
        inputs,
        title=title,
        primary=primary,
        related=related,
        vedana=vedana,
    )
    shown_matter = inputs.primary_matter if inputs.primary_matter else "null"
    body = (
        f"Layer 2 scope gate blocked this signal — `primary_matter="
        f"{shown_matter!r}` is not in the current allowed scope "
        f"(Director's `hot.md` ACTIVE set + `KBL_MATTER_SCOPE_ALLOWED` "
        f"override). Pipeline routed to skip stub; no Opus synthesis."
    )
    body = _pad_stub_body(body, _SKIP_INBOX_BODY_FILLER)
    body = _cap_stub_body(body)
    return f"{_dump_stub_frontmatter(fm)}\n{body}\n"


def _build_stub_only_stub(inputs: _SignalInputs) -> str:
    """Deterministic stub for low-confidence / noise-band rows. Director-
    visible so the Director can promote for review or leave to archive.

    ``title_hint`` is derived from ``inputs.triage_summary[:60]`` — the
    triage writer is free-form and routinely contains colons,
    timestamps, email-like tokens. Always routes through
    :func:`_normalize_stub_title` so trailing periods / whitespace are
    stripped (the Pydantic ``_title_shape`` validator rejects titles
    ending in ``.``) and through ``yaml.safe_dump`` so any scalar is
    quoted as needed.

    STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1 (2026-04-22): inputs are
    normalized via :func:`_normalize_stub_inputs` so §4.2 + slug
    registry invariants are enforced. Body floor/ceiling enforced
    via pad + cap helpers.
    """
    primary, related, vedana = _normalize_stub_inputs(inputs)
    title = _normalize_stub_title(
        inputs.triage_summary[:60], fallback="triage noise-band signal"
    )
    fm = _build_stub_frontmatter_dict(
        inputs,
        title=title,
        primary=primary,
        related=related,
        vedana=vedana,
    )
    body = (
        f"# [stub — low-confidence triage, Director review for promote/ignore]\n\n"
        f"Triage summary: {inputs.triage_summary}"
    )
    body = _pad_stub_body(body, _STUB_ONLY_BODY_FILLER)
    body = _cap_stub_body(body)
    return f"{_dump_stub_frontmatter(fm)}\n{body}\n"


# ---------------------------- prompt builder ----------------------------


def _truncate_signal(signal_text: str) -> str:
    """50K-char cap per §1.2 constraint + the §3 Ex 7 shape."""
    if len(signal_text) <= _MAX_SIGNAL_CHARS:
        return signal_text
    return signal_text[:_MAX_SIGNAL_CHARS] + _SIGNAL_TRUNC_MARKER


def _render_entities_block(entities: dict) -> str:
    """Compact JSON dump — per B3 §5 OQ8 recommendation."""
    import json

    if not entities:
        return "(no entities extracted)"
    try:
        return json.dumps(entities, default=str, sort_keys=True, indent=2)
    except (TypeError, ValueError):
        return str(entities)


def _render_thread_paths_block(paths: list[str]) -> str:
    if not paths:
        return _THREAD_PATHS_NONE
    return "\n".join(f"- {p}" for p in paths)


def _render_related_matters_block(matters: list[str]) -> str:
    if not matters:
        return "(none)"
    return ", ".join(matters)


def _matter_description(slug: Optional[str]) -> str:
    if not slug:
        return "no matter"
    try:
        return slug_registry.describe(slug)
    except KeyError:
        return "(unknown slug — check slug registry)"


def _build_gold_block(primary_matter: Optional[str]) -> str:
    """Leg 1 read. ``load_gold_context_by_matter`` returns ``""`` on
    zero-Gold; we wrap with the sentinel so the prompt sees a stable
    shape (prompt-caching prefers non-absent blocks per B3 §1.1)."""
    if not primary_matter:
        return _GOLD_NULL_MATTER_SENTINEL
    gold = load_gold_context_by_matter(primary_matter)
    return gold if gold else _GOLD_ZERO_MATTER_SENTINEL


@dataclass(frozen=True)
class _PromptInputs:
    """Leg 1 + Leg 3 reads done once per synthesize() call. The R3 ladder
    reuses the already-fresh reads rather than re-reading — Inv 3 is
    satisfied per-invocation, not per-attempt."""

    gold_block: str
    hot_md_block: str
    ledger_block: str


def _read_prompt_inputs(conn: Any, primary_matter: Optional[str]) -> _PromptInputs:
    """Fresh per-invocation reads (Inv 3)."""
    gold_block = _build_gold_block(primary_matter)
    hot_md_content = load_hot_md()
    hot_md_block = hot_md_content if hot_md_content else _HOT_MD_FALLBACK
    ledger_rows = load_recent_feedback(conn)
    rendered = render_ledger(ledger_rows)
    ledger_block = rendered if rendered.strip() else _LEDGER_FALLBACK
    return _PromptInputs(
        gold_block=gold_block,
        hot_md_block=hot_md_block,
        ledger_block=ledger_block,
    )


def _build_user_prompt(
    inputs: _SignalInputs,
    prompt_inputs: _PromptInputs,
    *,
    attempt: int,
) -> str:
    """Render the user block. R3 ladder drops blocks per attempt:

        attempt 0 — identical (all blocks present)
        attempt 1 — pared    (ledger → marker)
        attempt 2 — minimal  (ledger + hot.md → markers)
    """
    template = _load_user_template()

    if attempt == _R3_IDENTICAL:
        hot_md = prompt_inputs.hot_md_block
        ledger = prompt_inputs.ledger_block
    elif attempt == _R3_PARED:
        hot_md = prompt_inputs.hot_md_block
        ledger = _LEDGER_OMITTED_MARKER
    else:
        hot_md = _HOT_MD_OMITTED_MARKER
        ledger = _LEDGER_HOT_OMITTED_MARKER

    return template.format(
        signal_id=inputs.signal_id,
        primary_matter=inputs.primary_matter or "null",
        primary_matter_desc=_matter_description(inputs.primary_matter),
        related_matters=_render_related_matters_block(inputs.related_matters),
        vedana=inputs.vedana or "routine",
        triage_summary=inputs.triage_summary or "(no triage summary)",
        resolved_thread_paths=_render_thread_paths_block(inputs.resolved_thread_paths),
        extracted_entities=_render_entities_block(inputs.extracted_entities),
        gold_context_block=prompt_inputs.gold_block,
        hot_md_block=hot_md,
        feedback_ledger_block=ledger,
        signal_raw_text=_truncate_signal(inputs.raw_content),
        iso_now=_iso_utc_now(),
    )


def _build_system_prompt() -> str:
    """Return the stable §1.2 template. Inv 10 — no per-signal variation."""
    return _load_system_template()


# ---------------------------- Opus call path ----------------------------


def _system_template_overhead_chars() -> int:
    """Rough accounting of system-template size for the pre-call estimate.
    Counted separately from user-block chars since prompt caching means
    these get cheap reads on hit."""
    return len(_load_system_template())


def _fire_opus_with_r3(
    conn: Any,
    inputs: _SignalInputs,
    prompt_inputs: _PromptInputs,
    max_tokens: int,
) -> tuple[Optional[OpusResponse], Decimal, Optional[BaseException]]:
    """Run the R3 ladder. Returns ``(response, total_cost, last_error)``.

    ``response`` is the first successful OpusResponse; None if all three
    attempts failed (R3 exhausted).

    Every attempt — successful or failed — writes a ``kbl_cost_ledger``
    row so the Director can audit retry cost. A failed attempt records
    the tokens/latency the SDK returned (or 0s on transport failures
    where the SDK raised before usage could be extracted).

    ``OpusRequestError`` (4xx) breaks the loop early — retrying the
    same prompt won't recover a 400-class error — and propagates as
    ``last_error``.
    """
    system = _build_system_prompt()
    total_cost = Decimal("0")
    last_error: Optional[BaseException] = None

    for attempt in range(_R3_MAX_ATTEMPTS):
        user = _build_user_prompt(inputs, prompt_inputs, attempt=attempt)
        try:
            response = call_opus(system=system, user=user, max_tokens=max_tokens)
        except OpusRequestError as e:
            # 4xx — won't recover on retry. Record zero-token ledger row
            # (we don't have a usage object) and break.
            last_error = e
            _write_cost_ledger(
                conn,
                signal_id=inputs.signal_id,
                model_id=os.environ.get("KBL_STEP5_MODEL", "claude-opus-4-7"),
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                cost_usd=Decimal("0"),
                success=False,
            )
            break
        except AnthropicUnavailableError as e:
            last_error = e
            _write_cost_ledger(
                conn,
                signal_id=inputs.signal_id,
                model_id=os.environ.get("KBL_STEP5_MODEL", "claude-opus-4-7"),
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                cost_usd=Decimal("0"),
                success=False,
            )
            continue
        total_cost += response.cost_usd
        _write_cost_ledger(
            conn,
            signal_id=inputs.signal_id,
            model_id=response.model_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            latency_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            success=True,
            cache_read_tokens=response.cache_read_tokens,
            cache_write_tokens=response.cache_write_tokens,
        )
        return response, total_cost, None

    return None, total_cost, last_error


# ---------------------------- pipeline entry ----------------------------


def synthesize(signal_id: int, conn: Any) -> SynthesisResult:
    """Run Step 5 for a single signal.

    Full side-effect path:
        1. Load prior-step columns via one SELECT.
        2. Flip status to ``opus_running``.
        3. Route on ``step_5_decision``:
           * SKIP_INBOX / STUB_ONLY → deterministic stub, advance to
             ``awaiting_finalize``, NO Opus call, NO cost ledger row.
           * FULL_SYNTHESIS → cost gate → R3 ladder → write draft,
             advance to ``awaiting_finalize`` on success, flip to
             ``opus_failed`` on R3 exhaust, flip to ``paused_cost_cap``
             on gate denial.
        4. Return ``SynthesisResult`` describing what happened.

    Transaction-boundary contract:
        Caller owns commit/rollback. We don't call ``conn.commit()``
        on the happy path. The two exceptions are the terminal-state
        flips before an exception bubble — those commit-before-raise so
        the operator sees the halt state even if the caller's rollback
        fires. Documented on the branches below.

    Raises:
        LookupError: signal_id absent from ``signal_queue``.
        AnthropicUnavailableError / OpusRequestError: passed through
            when R3 ladder exhausts. Caller catches + routes to inbox.
        KblError: parent class for other pipeline-level failures.
    """
    inputs = _fetch_signal_inputs(conn, signal_id)
    _mark_running(conn, signal_id)

    decision_str = inputs.step_5_decision
    if decision_str in (_DECISION_SKIP, _DECISION_STUB):
        stub = (
            _build_skip_inbox_stub(inputs)
            if decision_str == _DECISION_SKIP
            else _build_stub_only_stub(inputs)
        )
        _write_draft_and_advance(conn, signal_id, stub, _STATE_NEXT)
        return SynthesisResult(
            decision=decision_str,
            terminal_state=_STATE_NEXT,
            opus_response=None,
            cost_usd=Decimal("0"),
        )

    if decision_str != _DECISION_FULL:
        # Null / unknown decision. This is a pipeline-invariant violation
        # — Step 4 should have written one of the four enum values.
        # Commit-before-raise so the operator sees the halt.
        _mark_terminal(conn, signal_id, _STATE_FAILED)
        try:
            conn.commit()
        except Exception:
            pass
        raise KblError(
            f"signal_queue.step_5_decision={decision_str!r} — Step 4 "
            "must write a valid decision enum value before Step 5 claims"
        )

    # ------------------ FULL_SYNTHESIS path ------------------
    prompt_inputs = _read_prompt_inputs(conn, inputs.primary_matter)

    # Cost gate. Pre-call estimate accounts for signal + Gold + hot.md +
    # ledger + system template.
    estimate_signal = {
        "signal_text": inputs.raw_content,
        "prompt_overhead_chars": (
            _system_template_overhead_chars()
            + len(prompt_inputs.gold_block)
            + len(prompt_inputs.hot_md_block)
            + len(prompt_inputs.ledger_block)
        ),
    }
    gate_decision = can_fire_step5(conn, estimate_signal)
    if gate_decision is not CostDecision.FIRE:
        # Park the signal at ``paused_cost_cap``. pipeline_tick idles
        # the queue until UTC midnight (daily cap) or the circuit probe
        # clears the breaker. Commit-before-return so the park state
        # survives a rollback in the caller.
        _mark_terminal(conn, signal_id, _STATE_PAUSED)
        try:
            conn.commit()
        except Exception:
            pass
        logger.warning(
            "cost_gate_denied: signal_id=%d decision=%s",
            signal_id,
            gate_decision.value,
        )
        return SynthesisResult(
            decision=_DECISION_FULL,
            terminal_state=_STATE_PAUSED,
            opus_response=None,
            cost_usd=Decimal("0"),
        )

    response, total_cost, last_error = _fire_opus_with_r3(
        conn,
        inputs,
        prompt_inputs,
        max_tokens=_MAX_TOKENS_DEFAULT,
    )

    if response is None:
        # R3 exhausted. Record the across-signal failure (feeds the
        # circuit breaker), flip to opus_failed, commit-before-raise so
        # the operator sees the halt, then propagate the last error.
        record_opus_failure(conn)
        _mark_terminal(conn, signal_id, _STATE_FAILED)
        try:
            conn.commit()
        except Exception:
            pass
        if last_error is not None:
            raise last_error
        raise AnthropicUnavailableError("Step 5 R3 ladder exhausted")

    # Happy path: record success (resets circuit), write draft, advance.
    record_opus_success(conn)
    _write_draft_and_advance(conn, signal_id, response.text, _STATE_NEXT)
    return SynthesisResult(
        decision=_DECISION_FULL,
        terminal_state=_STATE_NEXT,
        opus_response=response,
        cost_usd=total_cost,
    )
