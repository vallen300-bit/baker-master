"""Step 6 — deterministic Silver finalization (no LLM call).

Consumes ``signal_queue`` rows at ``status='awaiting_finalize'`` (written
by Step 5), validates the Opus draft against the Pydantic schema in
:mod:`kbl.schemas.silver`, builds the canonical ``final_markdown`` +
``target_vault_path``, UPSERTs one cross-link row per related matter
into ``kbl_cross_link_queue``, and advances to ``awaiting_commit``.

Option C cross-link flow (Director-ratified 2026-04-19):
    Render's Step 6 performs **zero vault filesystem writes** — Inv 9
    (Mac Mini is the sole vault writer) is honored structurally. The
    cross-link stub is serialized once into ``stub_row TEXT`` via
    ``CrossLinkStub.render_stub_row`` and UPSERTed into
    ``kbl_cross_link_queue``. Step 7 on Mac Mini polls unrealized rows,
    appends ``stub_row`` verbatim to ``wiki/<target>/_links.md`` under
    flock, and marks ``realized_at = NOW()``.

State transitions:
    awaiting_finalize → finalize_running → awaiting_commit  (happy)
                                       \\→ opus_failed       (validation fail; Step 5 R3 retry)
                                       \\→ finalize_failed   (3 Opus retries exhausted; terminal)

Error routing (per B3 spec §5):
    ``FinalizationError`` on malformed Opus draft → state flips to
    ``opus_failed``. pipeline_tick re-queues into Step 5 for the R3
    retry ladder (which counts Opus-side failures in
    ``kbl_circuit_breaker``). After 3 Opus rewrites we promote to
    ``finalize_failed`` terminal — see the ``_promote_to_finalize_failed``
    helper below.

CHANDA compliance:
    - **Q1 Loop Test.** No Leg touched. Step 6 reads DB columns and
      writes DB columns + a staging table. Leg 1/2/3 are all upstream
      concerns.
    - **Inv 4** + **Inv 8**. Structurally enforced via Pydantic Literal
      types — a draft with ``author: director`` or ``voice: gold`` fails
      at the type layer before any finalize work runs.
    - **Inv 6**. This IS Step 6; its existence satisfies the invariant.
    - **Inv 9** (Mac Mini single writer). Step 6 performs zero
      filesystem writes. Explicit test
      ``test_finalize_performs_zero_fs_writes`` pins this.

Transaction-boundary contract (Task K YELLOW remediation, 2026-04-19):
    Caller-owns-commit. ``finalize()`` writes to ``signal_queue`` +
    ``kbl_cross_link_queue`` but does NOT commit — ``pipeline_tick.
    _process_signal`` owns BEGIN/COMMIT/ROLLBACK. The
    ``finalize_failed`` / ``opus_failed`` terminal-state flips DO
    commit internally before raise, mirroring Step 1 / Step 4 / Step 5.
"""
from __future__ import annotations

import logging as _stdlib_logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml
from pydantic import ValidationError

from kbl.exceptions import FinalizationError, KblError
from kbl.logging import emit_log
from kbl.schemas.silver import (
    CrossLinkStub,
    MoneyMention,
    SilverDocument,
    SilverFrontmatter,
)

logger = _stdlib_logging.getLogger(__name__)


# ---------------------------- constants ----------------------------


_STATE_CLAIM = "awaiting_finalize"
_STATE_RUNNING = "finalize_running"
_STATE_NEXT = "awaiting_commit"
_STATE_OPUS_FAILED = "opus_failed"
_STATE_FINALIZE_FAILED = "finalize_failed"

# Full canonical target_vault_path regex — R20. New writes must pass.
_TARGET_PATH_REGEX = re.compile(r"^wiki/[a-z0-9-]+/\d{4}-\d{2}-\d{2}_[\w-]+\.md$")

_TITLE_SLUG_MAX = 60

# Retry budget for ``opus_failed → Step 5 R3 → back to Step 6``. After 3
# cumulative Opus-retry rounds we give up and terminal at
# ``finalize_failed``. Column on signal_queue: ``finalize_retry_count``
# (auto-created below via defensive ADD COLUMN on first mark).
_MAX_OPUS_REFLIPS = 3


# ---------------------------- dataclasses ----------------------------


@dataclass(frozen=True)
class _SignalRow:
    """Minimum column set from signal_queue needed to finalize."""

    signal_id: int
    opus_draft_markdown: str
    step_5_decision: Optional[str]
    triage_score: Optional[int]
    triage_confidence: Optional[float]
    finalize_retry_count: int


@dataclass(frozen=True)
class FinalizeResult:
    """Returned from ``finalize()`` on success.

    ``terminal_state`` is the state the row was advanced to. On every
    failure path we raise ``FinalizationError`` and do NOT return.
    """

    signal_id: int
    terminal_state: str
    target_vault_path: str
    final_markdown: str
    cross_link_count: int


# ---------------------------- money parser ----------------------------


_MONEY_PATTERNS = [
    # 'EUR 1200000', 'USD 3000', 'CHF 800000'
    re.compile(r"^\s*(?P<ccy>[A-Z]{3})\s+(?P<amt>[0-9][0-9_,.]*)\s*$"),
    # '£3000', '€1200000', '$500000', '¥8000000' — currency symbol prefix
    re.compile(r"^\s*(?P<sym>[€£$¥])\s*(?P<amt>[0-9][0-9_,.]*)\s*$"),
    # '1200000 EUR', '3000 GBP'
    re.compile(r"^\s*(?P<amt>[0-9][0-9_,.]*)\s+(?P<ccy>[A-Z]{3})\s*$"),
]

# '1.2M', '800K', '2.5B' shorthand.
_SHORTHAND_MULTIPLIERS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
_SHORTHAND_PATTERN = re.compile(
    r"^\s*(?P<ccy>[A-Z]{3})?\s*(?P<sym>[€£$¥])?\s*"
    r"(?P<num>[0-9]+(?:\.[0-9]+)?)(?P<mult>[KkMmBb])\s*(?P<ccy2>[A-Z]{3})?\s*$"
)

_SYMBOL_TO_CCY = {
    "€": "EUR",
    "£": "GBP",
    "$": "USD",
    "¥": "JPY",  # JPY not in Literal yet — returns None downstream
}

_KNOWN_CURRENCIES = {"EUR", "USD", "CHF", "GBP", "RUB"}


def _normalize_amount_digits(raw: str) -> Optional[int]:
    """Strip separators (``1_200_000`` / ``1,200,000`` / ``1.200.000``).
    Returns the integer unit count or None on malformed input.

    Heuristic: commas + underscores + spaces are always separators. A
    lone ``.`` followed by exactly 3 digits is a European thousands
    separator; any other ``.`` is a decimal point and we reject (we
    only store integer units — fractional EUR is out of scope).
    """
    s = raw.strip().replace("_", "").replace(",", "").replace(" ", "")
    if s.count(".") == 1:
        whole, frac = s.split(".")
        if len(frac) == 3 and whole.isdigit():
            s = whole + frac
        else:
            return None
    if not s.isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _parse_money_string(raw: str) -> Optional[MoneyMention]:
    """Parse one Opus-emitted money string into a :class:`MoneyMention`.

    Accepts:
        ``'EUR 1200000'``, ``'1200000 EUR'``, ``'€1200000'``, ``'£3000'``,
        ``'CHF 800K'``, ``'€1.2M'``, ``'USD 2.5M'``, ``'RUB 500000000'``.

    Returns None on malformed input or on currencies outside the
    canonical set ``{EUR, USD, CHF, GBP, RUB}`` — Step 6 drops them
    silently; the raw string still lives in ``opus_draft_markdown`` for
    audit.
    """
    if not raw or not isinstance(raw, str):
        return None

    text = raw.strip()
    if not text:
        return None

    # Shorthand first — '€1.2M', 'CHF 800K', 'USD 2.5M'
    sh = _SHORTHAND_PATTERN.match(text)
    if sh:
        num = float(sh.group("num"))
        mult = _SHORTHAND_MULTIPLIERS[sh.group("mult").lower()]
        ccy = sh.group("ccy") or sh.group("ccy2") or _SYMBOL_TO_CCY.get(sh.group("sym") or "")
        if not ccy or ccy not in _KNOWN_CURRENCIES:
            return None
        amount = int(round(num * mult))
        if amount <= 0:
            return None
        return MoneyMention(amount=amount, currency=ccy)

    # Long-form patterns.
    for pat in _MONEY_PATTERNS:
        m = pat.match(text)
        if not m:
            continue
        groups = m.groupdict()
        ccy = groups.get("ccy") or _SYMBOL_TO_CCY.get(groups.get("sym") or "")
        if not ccy or ccy not in _KNOWN_CURRENCIES:
            return None
        amt = _normalize_amount_digits(groups["amt"])
        if amt is None or amt <= 0:
            return None
        return MoneyMention(amount=amt, currency=ccy)

    return None


# ---------------------------- path builder ----------------------------


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _title_to_slug(title: str) -> str:
    """Lowercase, dash-separated, alphanumeric only, trimmed to 60 chars.

    Empty titles → ``'untitled'``. Collisions are resolved at the caller
    by appending ``_<source_id_short>`` per B3 spec §3.6.
    """
    lowered = title.strip().lower()
    collapsed = _SLUG_STRIP_RE.sub("-", lowered).strip("-")
    if not collapsed:
        return "untitled"
    if len(collapsed) > _TITLE_SLUG_MAX:
        # Trim to last clean dash boundary if possible.
        trimmed = collapsed[:_TITLE_SLUG_MAX].rstrip("-")
        if not trimmed:
            trimmed = collapsed[:_TITLE_SLUG_MAX]
        return trimmed
    return collapsed


def build_target_vault_path(
    fm: SilverFrontmatter, source_id_short: Optional[str] = None
) -> str:
    """Build ``wiki/<primary_matter>/<yyyy-mm-dd>_<slug>.md`` path.

    ``primary_matter=None`` routes to ``wiki/_inbox/`` per B3 §3.6 — but
    Step 6 blocks this case earlier via R7 (null-primary ⇒ empty-related
    + status=stub_inbox). Callers should only hit the null branch on
    stub_inbox frontmatter.

    ``source_id_short``: optional collision suffix (`_<short>` before
    ``.md``). Step 7 surfaces real collisions; Step 6 only applies the
    suffix if the caller passes it.
    """
    matter = fm.primary_matter or "_inbox"
    date_stamp = fm.created.strftime("%Y-%m-%d")
    slug = _title_to_slug(fm.title)
    if source_id_short:
        slug = f"{slug}_{source_id_short}"[:_TITLE_SLUG_MAX]
    path = f"wiki/{matter}/{date_stamp}_{slug}.md"

    # R20 (new-write regex). Inbox paths bypass the strict regex because
    # "_inbox" starts with an underscore — allow it explicitly.
    if matter == "_inbox":
        return path
    if not _TARGET_PATH_REGEX.match(path):
        raise FinalizationError(
            f"target_vault_path failed R20 regex: '{path}' (matter={matter}, "
            f"date={date_stamp}, slug={slug})"
        )
    return path


# ---------------------------- YAML parse ----------------------------


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)


def _split_frontmatter(markdown: str) -> Tuple[Dict[str, Any], str]:
    """Split a ``---``-fenced frontmatter + body Markdown document.

    Raises :class:`FinalizationError` on missing fence or malformed YAML.
    """
    if not markdown or not markdown.strip():
        raise FinalizationError("opus_draft_markdown is empty")
    m = _FRONTMATTER_RE.match(markdown)
    if not m:
        raise FinalizationError(
            "opus_draft_markdown missing YAML frontmatter fence "
            "(expected '---\\n...\\n---\\n<body>')"
        )
    raw_yaml = m.group(1)
    body = m.group(2)
    try:
        fm_dict = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as e:
        raise FinalizationError(f"frontmatter YAML parse failed: {e}") from e
    if not isinstance(fm_dict, dict):
        raise FinalizationError(
            f"frontmatter did not deserialize to a mapping (got {type(fm_dict).__name__})"
        )
    return fm_dict, body


def _normalize_money_list(fm_dict: Dict[str, Any]) -> None:
    """Mutate ``fm_dict['money_mentioned']`` from ``list[str]`` → ``list[MoneyMention]``.

    Opus emits raw strings for prompt-cache stability (OQ4). Step 6
    parses each string via :func:`_parse_money_string`. Unparseable
    strings are dropped with a WARN log — the Director sees the raw
    value in ``opus_draft_markdown`` if audit is needed.
    """
    raw = fm_dict.get("money_mentioned")
    if raw is None:
        fm_dict["money_mentioned"] = []
        return
    if not isinstance(raw, list):
        raise FinalizationError(
            f"money_mentioned must be a list (got {type(raw).__name__})"
        )
    parsed: List[Dict[str, Any]] = []
    for entry in raw:
        if isinstance(entry, dict):
            # Already structured — let Pydantic validate it.
            parsed.append(entry)
            continue
        if not isinstance(entry, str):
            continue
        mm = _parse_money_string(entry)
        if mm is not None:
            parsed.append({"amount": mm.amount, "currency": mm.currency})
    fm_dict["money_mentioned"] = parsed


# ---------------------------- signal load ----------------------------


def _fetch_signal_row(conn: Any, signal_id: int) -> _SignalRow:
    """One SELECT pulls every column Step 6 needs. Raises ``LookupError``
    on missing row — pipeline_tick catches and routes to inbox."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT opus_draft_markdown, step_5_decision, "
            "       triage_score, triage_confidence, "
            "       COALESCE(finalize_retry_count, 0) "
            "FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"signal_queue row not found: id={signal_id}")
    (draft, decision, triage_score, triage_confidence, retry_count) = row
    if not draft:
        raise FinalizationError(
            f"signal_queue.opus_draft_markdown is NULL for id={signal_id} "
            f"(Step 5 should have written it on every path per Inv 6)"
        )
    return _SignalRow(
        signal_id=signal_id,
        opus_draft_markdown=draft,
        step_5_decision=decision,
        triage_score=int(triage_score) if triage_score is not None else None,
        triage_confidence=(
            float(triage_confidence) if triage_confidence is not None else None
        ),
        finalize_retry_count=int(retry_count or 0),
    )


# ---------------------------- state writers ----------------------------


def _mark_running(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_RUNNING, signal_id),
        )


def _write_final_and_advance(
    conn: Any,
    signal_id: int,
    final_markdown: str,
    target_vault_path: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET "
            "  final_markdown = %s, "
            "  target_vault_path = %s, "
            "  status = %s "
            "WHERE id = %s",
            (final_markdown, target_vault_path, _STATE_NEXT, signal_id),
        )


def _mark_terminal(conn: Any, signal_id: int, state: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (state, signal_id),
        )


def _increment_retry_count(conn: Any, signal_id: int) -> int:
    """Bump ``finalize_retry_count`` and return the new value. Defensive
    ADD COLUMN IF NOT EXISTS keeps this idempotent across environments
    where the migration hasn't been applied yet — the retry counter is
    not part of the Step 6 migration on purpose (R3 coordination with
    Step 5 is the reason, see module docstring)."""
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE signal_queue "
            "ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0"
        )
        cur.execute(
            "UPDATE signal_queue "
            "SET finalize_retry_count = COALESCE(finalize_retry_count, 0) + 1 "
            "WHERE id = %s "
            "RETURNING finalize_retry_count",
            (signal_id,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


# ---------------------------- cross-link UPSERT ----------------------------


def _upsert_cross_link(
    conn: Any,
    source_signal_id: int,
    target_slug: str,
    stub_row: str,
    vedana: Optional[str],
    source_path: str,
) -> None:
    """One cross-link row per related matter. Option C UPSERT keys on
    ``(source_signal_id, target_slug)`` so re-runs stay idempotent.

    ``realized_at = NULL`` on every UPDATE so Step 7 re-picks the row
    if the stub_row content changed (rare: late Silver re-write from
    an opus_failed → R3 recovery). Step 7 replaces in place.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO kbl_cross_link_queue "
            "  (source_signal_id, target_slug, stub_row, vedana, source_path) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (source_signal_id, target_slug) DO UPDATE SET "
            "  stub_row    = EXCLUDED.stub_row, "
            "  vedana      = EXCLUDED.vedana, "
            "  source_path = EXCLUDED.source_path, "
            "  created_at  = NOW(), "
            "  realized_at = NULL",
            (source_signal_id, target_slug, stub_row, vedana, source_path),
        )


# ---------------------------- frontmatter builder ----------------------------


def _serialize_final_markdown(doc: SilverDocument) -> str:
    """Render the Pydantic-round-tripped canonical ``final_markdown``.

    Field order matches :class:`SilverFrontmatter` declaration order
    (load-bearing — Step 7's readers + Director's eye both rely on
    stable ordering). Uses ``yaml.safe_dump`` with ``sort_keys=False``
    on an ordered dict we build manually.
    """
    fm = doc.frontmatter
    # Build ordered dict in canonical declaration order.
    ordered: List[Tuple[str, Any]] = [
        ("title", fm.title),
        ("voice", fm.voice),
        ("author", fm.author),
        ("created", fm.created.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("source_id", fm.source_id),
        ("primary_matter", fm.primary_matter),
        ("related_matters", list(fm.related_matters)),
        ("vedana", fm.vedana),
        ("triage_score", fm.triage_score),
        ("triage_confidence", fm.triage_confidence),
    ]
    # Optional keys: only emit when set (keeps frontmatter tight).
    if fm.thread_continues:
        ordered.append(("thread_continues", list(fm.thread_continues)))
    if fm.deadline:
        ordered.append(("deadline", fm.deadline))
    if fm.money_mentioned:
        ordered.append(
            (
                "money_mentioned",
                [{"amount": m.amount, "currency": m.currency} for m in fm.money_mentioned],
            )
        )
    if fm.status is not None:
        ordered.append(("status", fm.status))

    yaml_text = yaml.safe_dump(
        dict(ordered),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).strip()
    return f"---\n{yaml_text}\n---\n\n{doc.body.rstrip()}\n"


# ---------------------------- status provenance gate ----------------------------


_FULL_SYNTHESIS = "full_synthesis"
_STUB_DECISIONS = {"stub_only", "skip_inbox", "cross_link_only"}


def _assert_status_provenance(
    step_5_decision: Optional[str], status: Optional[str], signal_id: int
) -> None:
    """B3 spec §3.7: ``status`` is reserved for deterministic stub
    writers. Opus on FULL_SYNTHESIS must not emit it; stub decisions
    must have set it."""
    if step_5_decision == _FULL_SYNTHESIS and status is not None:
        raise FinalizationError(
            f"signal_id={signal_id}: Opus emitted status='{status}' on "
            f"full_synthesis decision; that field is reserved for stub writers"
        )
    if step_5_decision in _STUB_DECISIONS and status is None:
        raise FinalizationError(
            f"signal_id={signal_id}: deterministic stub writer should have set "
            f"status for decision='{step_5_decision}' but status is None"
        )


# ---------------------------- logging ----------------------------


def _emit_validation_failures(
    conn: Any, signal_id: int, err: ValidationError
) -> None:
    """One WARN row per failed field per B3 spec §6. ``validation_error_idx``
    gives 0-N ordering for joinability with the retry ladder."""
    for idx, e in enumerate(err.errors()):
        loc = ".".join(str(p) for p in e.get("loc") or ())
        msg = e.get("msg") or "validation error"
        emit_log(
            "WARN",
            "finalize",
            signal_id,
            f"{loc}: {msg}",
        )


# ---------------------------- finalize ----------------------------


def finalize(signal_id: int, conn: Any) -> FinalizeResult:
    """Finalize one signal from ``awaiting_finalize`` → ``awaiting_commit``.

    Contract:
        * Reads ``opus_draft_markdown`` + telemetry from ``signal_queue``.
        * Validates via :class:`SilverDocument` (Pydantic).
        * Writes ``final_markdown`` + ``target_vault_path`` on
          ``signal_queue``.
        * UPSERTs one row per related matter into ``kbl_cross_link_queue``.
        * Advances to ``awaiting_commit``.

    On validation failure:
        * Emits one WARN log per failed field.
        * Increments ``finalize_retry_count``.
        * If retries < :data:`_MAX_OPUS_REFLIPS` — flips to
          ``opus_failed`` (Step 5 R3 picks up); commits, raises.
        * Otherwise flips to ``finalize_failed`` terminal; commits, raises.

    Never writes to the filesystem. Option C: cross-link FS writes are
    owned by Step 7 on Mac Mini.
    """
    row = _fetch_signal_row(conn, signal_id)
    _mark_running(conn, signal_id)

    # Parse + validate.
    try:
        fm_dict, body = _split_frontmatter(row.opus_draft_markdown)
    except FinalizationError:
        _route_validation_failure(conn, row, error_count=1)
        raise

    # Inject pipeline telemetry + parse money strings BEFORE Pydantic
    # validation (schema requires triage_score + triage_confidence).
    if row.triage_score is not None:
        fm_dict.setdefault("triage_score", row.triage_score)
    if row.triage_confidence is not None:
        fm_dict.setdefault("triage_confidence", row.triage_confidence)

    try:
        _normalize_money_list(fm_dict)
    except FinalizationError:
        _route_validation_failure(conn, row, error_count=1)
        raise

    try:
        fm = SilverFrontmatter(**fm_dict)
    except ValidationError as e:
        _emit_validation_failures(conn, signal_id, e)
        _route_validation_failure(conn, row, error_count=len(e.errors()))
        raise FinalizationError(
            f"signal_id={signal_id}: frontmatter validation failed "
            f"({len(e.errors())} errors)"
        ) from e

    # Status provenance gate (§3.7).
    try:
        _assert_status_provenance(row.step_5_decision, fm.status, signal_id)
    except FinalizationError as e:
        emit_log("ERROR", "finalize", signal_id, str(e))
        # Status-provenance mismatch is a pipeline bug, not a draft
        # issue — skip R3, go straight to finalize_failed terminal.
        _mark_terminal(conn, signal_id, _STATE_FINALIZE_FAILED)
        conn.commit()
        raise

    try:
        doc = SilverDocument(frontmatter=fm, body=body)
    except ValidationError as e:
        _emit_validation_failures(conn, signal_id, e)
        _route_validation_failure(conn, row, error_count=len(e.errors()))
        raise FinalizationError(
            f"signal_id={signal_id}: body validation failed "
            f"({len(e.errors())} errors)"
        ) from e

    # Build target path.
    target_vault_path = build_target_vault_path(fm)

    # Write final_markdown + advance. Cross-link UPSERT happens after
    # the state write so the row's source_path reference is resolvable.
    final_markdown = _serialize_final_markdown(doc)
    _write_final_and_advance(conn, signal_id, final_markdown, target_vault_path)

    cross_link_count = 0
    for slug in fm.related_matters:
        stub = CrossLinkStub(
            source_signal_id=str(signal_id),
            source_path=target_vault_path,
            created=fm.created,
            vedana=fm.vedana,
            excerpt=_build_excerpt(fm.title, body),
        )
        _upsert_cross_link(
            conn,
            source_signal_id=signal_id,
            target_slug=slug,
            stub_row=stub.render_stub_row(),
            vedana=fm.vedana,
            source_path=target_vault_path,
        )
        cross_link_count += 1

    return FinalizeResult(
        signal_id=signal_id,
        terminal_state=_STATE_NEXT,
        target_vault_path=target_vault_path,
        final_markdown=final_markdown,
        cross_link_count=cross_link_count,
    )


def _build_excerpt(title: str, body: str) -> Optional[str]:
    """Derive a 1-line excerpt ≤140 chars for cross-link stubs.

    Prefer the title (it's already a pithy summary). Fall back to the
    first body sentence if the title is empty-after-trim.
    """
    candidate = title.strip()
    if not candidate:
        candidate = body.strip().split("\n", 1)[0]
    candidate = candidate.replace("\n", " ").strip()
    if len(candidate) > 140:
        candidate = candidate[:137].rstrip() + "..."
    return candidate or None


def _route_validation_failure(
    conn: Any, row: _SignalRow, *, error_count: int
) -> None:
    """Flip state + commit according to the retry ladder.

    After ``_MAX_OPUS_REFLIPS`` Opus retries fail finalization, the
    signal goes to ``finalize_failed`` terminal. Before that it flips to
    ``opus_failed`` so Step 5's R3 ladder gets another crack.

    ``emit_log`` is called at the point of raise; this helper only
    handles the state transition + commit-before-raise contract.
    """
    new_count = _increment_retry_count(conn, row.signal_id)
    if new_count >= _MAX_OPUS_REFLIPS:
        _mark_terminal(conn, row.signal_id, _STATE_FINALIZE_FAILED)
        emit_log(
            "ERROR",
            "finalize",
            row.signal_id,
            f"terminal finalize failure after {new_count} Opus retries; "
            f"routed to {_STATE_FINALIZE_FAILED}",
        )
    else:
        _mark_terminal(conn, row.signal_id, _STATE_OPUS_FAILED)
    conn.commit()
