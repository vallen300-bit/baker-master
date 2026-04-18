"""Step 1 — Gemma local triage evaluator.

Consumes Layer 0 PASS output (`signal_queue.status='awaiting_triage'` rows),
builds the production prompt per `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md`
@ commit ``d7db987``, calls Ollama, parses JSON, writes results to
``signal_queue`` columns + a row to ``kbl_cost_ledger``, advances state.

CHANDA compliance:
    - **Inv 3 (Step 1 reads on every invocation).** ``build_prompt`` calls
      ``load_hot_md()`` + ``load_recent_feedback(conn, limit=20)`` on every
      call. No caching. Zero reads = invariant violation. Explicit test
      coverage in ``tests/test_step1_triage.py``.
    - **Inv 10 (template stability).** Template text is loaded once per
      process from ``kbl/prompts/step1_triage.txt`` — no self-modification
      based on feedback. Feedback steers model DECISIONS via the rendered
      ledger block, not the template itself.
    - **Q1 Loop Test** — this step is core Leg 3 behavior. Pass.
    - **Q2 Wish Test** — pure wish-service. Pass.

State transitions (per task contract):
    awaiting_triage  -->  triage_running  -->  awaiting_resolve
                                        \\->   awaiting_inbox_route
                                                  (score < KBL_PIPELINE_TRIAGE_THRESHOLD
                                                   OR retries-exhausted stub)

Threshold default: 40. Override via ``KBL_PIPELINE_TRIAGE_THRESHOLD`` env var.

Parse-failure recovery (§7 row 3 — ``R3 retry (pared prompt); 2 failures → inbox``):
    The first attempt uses the full prompt (slug glossary + hot.md + ledger).
    If Gemma returns unparseable JSON the triage function retries once with
    a pared prompt — ledger block replaced with an ``[LEDGER OMITTED — R3
    retry]`` marker — on the hypothesis that an over-large ledger block is
    the most likely confound. If the retry ALSO fails, ``triage()`` writes
    a stub ``TriageResult`` (``primary_matter=None``, ``vedana=None``,
    ``summary="parse_failed"``) and advances the signal to
    ``awaiting_inbox_route`` — Director-visible, pipeline flows. No
    ``TriageParseError`` is raised past the retry budget.

    Inv 3 preservation: both attempts share the same ``load_hot_md()`` +
    ``load_recent_feedback()`` reads done by ``build_prompt``. The pared
    retry reuses those already-fresh values; the reads still happened on
    this ``triage()`` invocation. Test ``test_build_prompt_reads_on_every_call``
    enforces.

Out of scope (future tickets):
    - Ollama service management (KBL-A)
    - Qwen availability fallback (separate ticket)
    - Step 2 resolver
    - Anthropic cost ledger mapping (this step is Gemma-only, cost_usd=0)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kbl import slug_registry
from kbl.exceptions import OllamaUnavailableError, TriageParseError
from kbl.loop import load_hot_md, load_recent_feedback, render_ledger

# ---------------------------- constants ----------------------------

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "step1_triage.txt"
)

_TRIAGE_THRESHOLD_ENV = "KBL_PIPELINE_TRIAGE_THRESHOLD"
_DEFAULT_TRIAGE_THRESHOLD = 40

_OLLAMA_HOST_ENV = "OLLAMA_HOST"
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"

_DEFAULT_MODEL = "gemma2:8b"
_DEFAULT_TIMEOUT = 30
_DEFAULT_SIGNAL_TRUNCATE = 3000

_VEDANA_VALUES = frozenset({"opportunity", "threat", "routine"})

_HOT_MD_FALLBACK = "(no current-priorities cache available)"
_LEDGER_FALLBACK = "(no recent Director actions)"

# Parse-failure recovery (§7 row 3). One retry after the initial call —
# 2 total Ollama calls max per signal. On retries-exhausted, ``triage()``
# writes a stub + advances to the inbox route rather than raising.
_RETRY_BUDGET = 1
_LEDGER_PARED_MARKER = "[LEDGER OMITTED — R3 retry]"
_STUB_SUMMARY = "parse_failed"
_INBOX_ROUTE_STATE = "awaiting_inbox_route"


# ---------------------------- result dataclass ----------------------------


@dataclass(frozen=True)
class TriageResult:
    """Parsed + validated Gemma response. Shape matches §4.2 contract.

    ``vedana`` is ``Optional[str]`` to accommodate the retries-exhausted
    stub (``vedana=None``, ``summary="parse_failed"``) that Step 1 writes
    when Gemma returns unparseable JSON twice in a row. On the happy path
    the parser still enforces the three-value enum.
    """

    primary_matter: Optional[str]
    related_matters: tuple[str, ...] = field(default_factory=tuple)
    vedana: Optional[str] = "routine"
    triage_score: int = 0
    triage_confidence: float = 0.0
    summary: str = ""


# ---------------------------- template loading ----------------------------


_template_cache: Optional[str] = None


def _load_template() -> str:
    """Read the triage template file once per process. Inv 10 — template
    is code, not data; cached since it doesn't change between signals."""
    global _template_cache
    if _template_cache is None:
        _template_cache = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _template_cache


def _reset_template_cache() -> None:
    """Test hook — drops cached template so test fixtures can override."""
    global _template_cache
    _template_cache = None


# ---------------------------- glossary builder ----------------------------


def _build_glossary() -> str:
    """Render the active-slug glossary block: ``  <slug><pad>— <desc>``.

    Matches the format the D1-ratified prompt was evaluated on: slugs
    left-justified to ``max_len+2`` chars, em-dash separator. Deterministic
    (sorted) so prompt text is stable across calls with identical
    registry state — helps Ollama cache + telemetry diffing.
    """
    slugs = sorted(slug_registry.active_slugs())
    if not slugs:
        return "  (no active matter slugs)"
    max_len = max(len(s) for s in slugs) + 2
    return "\n".join(f"  {s.ljust(max_len)}— {slug_registry.describe(s)}" for s in slugs)


# ---------------------------- prompt builder ----------------------------


def build_prompt(signal_text: str, conn: Any) -> str:
    """Assemble the Step 1 triage prompt.

    Calls ``kbl.slug_registry`` + ``kbl.loop`` helpers on every invocation
    — per CHANDA Inv 3, these reads MUST occur fresh each tick. Caller
    owns the ``conn`` lifecycle (PR #6 convention).

    Args:
        signal_text: the raw signal content. Quotes are escaped so the
            ``Signal: "..."`` wrapper stays syntactically well-formed;
            truncated to 3000 chars to cap prompt size.
        conn: a live psycopg connection used by ``load_recent_feedback``.

    Returns:
        The fully-rendered prompt string. Callers must NOT mutate.
    """
    glossary = _build_glossary()

    hot_md_content = load_hot_md()
    # Inv 1: both None (missing file) and "" (empty file) are zero-Gold.
    hot_md_block = hot_md_content if hot_md_content else _HOT_MD_FALLBACK

    ledger_rows = load_recent_feedback(conn, limit=20)
    rendered = render_ledger(ledger_rows)
    # render_ledger already returns a placeholder string for empty input,
    # but guard here so a renderer bug doesn't leak an empty block to the
    # model.
    feedback_ledger_block = rendered if rendered.strip() else _LEDGER_FALLBACK

    template = _load_template()
    return template.format(
        signal=signal_text.replace('"', "'")[:_DEFAULT_SIGNAL_TRUNCATE],
        slug_glossary=glossary,
        hot_md_block=hot_md_block,
        feedback_ledger_block=feedback_ledger_block,
    )


def _build_pared_prompt(
    signal_text: str, slug_glossary: str, hot_md_block: str
) -> str:
    """Assemble the Step 1 triage prompt WITHOUT the feedback ledger block.

    Used as the R3 retry after the first Gemma call returned unparseable
    JSON — the hypothesis is that an over-large ledger block is the most
    likely confound. Slug glossary + hot.md + signal remain; the ledger
    placeholder is replaced with a short marker so the template still
    formats cleanly.

    Inv 3 note: this helper does NOT read hot.md or the ledger. The caller
    (``triage()``) has already executed those reads once per invocation
    via ``build_prompt``; the retry reuses the already-fresh values rather
    than re-reading. Inv 3's per-invocation-fresh-read contract is still
    satisfied.
    """
    template = _load_template()
    return template.format(
        signal=signal_text.replace('"', "'")[:_DEFAULT_SIGNAL_TRUNCATE],
        slug_glossary=slug_glossary,
        hot_md_block=hot_md_block,
        feedback_ledger_block=_LEDGER_PARED_MARKER,
    )


# ---------------------------- matter normalization ----------------------------


def normalize_matter(raw: Optional[str]) -> Optional[str]:
    """Resolve a raw string to a canonical slug via ``slug_registry.normalize``.

    Handles:
        - ``None`` / ``""`` / ``"null"`` / ``"none"`` -> ``None``
        - Canonical slug match -> slug unchanged
        - Alias match (case + whitespace normalized) -> canonical slug
        - Unknown / generic category -> ``None``
    """
    return slug_registry.normalize(raw)


# ---------------------------- response parser ----------------------------


def _coerce_int_score(value: Any) -> int:
    if isinstance(value, bool):  # bool is subclass of int
        raise TriageParseError(f"triage_score is a bool: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise TriageParseError(f"triage_score must be int 0-100 (got {value!r})")


def _coerce_confidence(value: Any) -> float:
    if isinstance(value, bool):
        raise TriageParseError(f"triage_confidence is a bool: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as e:
            raise TriageParseError(
                f"triage_confidence not a number: {value!r}"
            ) from e
    raise TriageParseError(f"triage_confidence must be 0.0-1.0 (got {value!r})")


def parse_gemma_response(raw: str) -> TriageResult:
    """Parse Gemma's structured JSON triage output.

    Enforces the §4.2 schema: 6 required keys, ``vedana`` in the enum,
    ``triage_score`` coerceable to int, ``triage_confidence`` coerceable
    to float, ``primary_matter`` normalized against the slug registry,
    ``related_matters`` deduped against ``primary_matter``. Raises
    ``TriageParseError`` on any violation — the caller (``triage()``) then
    applies the malformed-output recovery policy per §3.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise TriageParseError("empty model response")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TriageParseError(f"invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise TriageParseError(f"top-level must be object (got {type(data).__name__})")

    missing = [
        k
        for k in (
            "primary_matter",
            "related_matters",
            "vedana",
            "triage_score",
            "triage_confidence",
            "summary",
        )
        if k not in data
    ]
    if missing:
        raise TriageParseError(f"missing required keys: {sorted(missing)}")

    vedana = data["vedana"]
    if not isinstance(vedana, str) or vedana not in _VEDANA_VALUES:
        raise TriageParseError(
            f"vedana must be one of {sorted(_VEDANA_VALUES)} (got {vedana!r})"
        )

    triage_score = max(0, min(100, _coerce_int_score(data["triage_score"])))
    triage_confidence = max(0.0, min(1.0, _coerce_confidence(data["triage_confidence"])))

    summary = data["summary"]
    if not isinstance(summary, str):
        raise TriageParseError(f"summary must be a string (got {type(summary).__name__})")

    primary_raw = data["primary_matter"]
    # Accept JSON null, the string "null", or a slug.
    primary_matter = normalize_matter(primary_raw) if primary_raw else None

    related_raw = data["related_matters"]
    if not isinstance(related_raw, list):
        raise TriageParseError(
            f"related_matters must be a list (got {type(related_raw).__name__})"
        )
    related: list[str] = []
    seen: set[str] = set()
    for item in related_raw:
        norm = normalize_matter(item)
        if norm is None or norm == primary_matter or norm in seen:
            continue
        seen.add(norm)
        related.append(norm)

    return TriageResult(
        primary_matter=primary_matter,
        related_matters=tuple(related),
        vedana=vedana,
        triage_score=triage_score,
        triage_confidence=triage_confidence,
        summary=summary,
    )


# ---------------------------- Ollama call ----------------------------


def call_ollama(
    prompt: str,
    model: str = _DEFAULT_MODEL,
    timeout: int = _DEFAULT_TIMEOUT,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """POST ``prompt`` to Ollama's ``/api/generate`` endpoint.

    Returns the full decoded response dict so the caller can extract
    ``response`` (model text) + token counters + latency for ledger
    bookkeeping. Uses ``format=json`` + temperature=0 + seed=42 — matches
    the D1-eval sampling config so production accuracy stays aligned
    with measured numbers.

    Raises ``OllamaUnavailableError`` on timeout / connection refused /
    non-2xx. Retry policy is the caller's concern (Step 1 retries once
    per §3).
    """
    if host is None:
        host = os.environ.get(_OLLAMA_HOST_ENV, _DEFAULT_OLLAMA_HOST)
    url = host.rstrip("/") + "/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "seed": 42,
            "top_p": 0.9,
            "num_predict": 512,
        },
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise OllamaUnavailableError(
            f"Ollama HTTP {e.code} at {url}: {e.reason}"
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OllamaUnavailableError(
            f"Ollama unreachable at {url}: {e}"
        ) from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OllamaUnavailableError(
            f"Ollama returned non-JSON envelope: {e}"
        ) from e


# ---------------------------- pipeline entry ----------------------------


def _get_triage_threshold() -> int:
    raw = os.environ.get(_TRIAGE_THRESHOLD_ENV)
    if raw is None or raw == "":
        return _DEFAULT_TRIAGE_THRESHOLD
    try:
        parsed = int(raw)
    except ValueError:
        return _DEFAULT_TRIAGE_THRESHOLD
    return parsed


def _fetch_signal(conn: Any, signal_id: int) -> str:
    """Return the signal's raw content. Raises ``LookupError`` when absent.

    Consumes ``raw_content`` per the evaluator assumption; if the column
    name differs in the live schema we'll see the failure at the SQL level
    and can adjust in a follow-up without touching the rest of the flow.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_content FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"signal_queue row not found: id={signal_id}")
    return row[0] or ""


def _mark_running(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = 'triage_running' WHERE id = %s",
            (signal_id,),
        )


def _write_triage_result(
    conn: Any, signal_id: int, result: TriageResult, next_state: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET "
            "  primary_matter = %s, "
            "  related_matters = %s, "
            "  vedana = %s, "
            "  triage_score = %s, "
            "  triage_confidence = %s, "
            "  triage_summary = %s, "
            "  status = %s "
            "WHERE id = %s",
            (
                result.primary_matter,
                list(result.related_matters),
                result.vedana,
                result.triage_score,
                result.triage_confidence,
                result.summary,
                next_state,
                signal_id,
            ),
        )


def _write_cost_ledger(
    conn: Any,
    signal_id: int,
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    latency_ms: int,
    success: bool,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO kbl_cost_ledger "
            "(signal_id, step, model, input_tokens, output_tokens, "
            " latency_ms, cost_usd, success) "
            "VALUES (%s, 'triage', %s, %s, %s, %s, 0, %s)",
            (
                signal_id,
                model,
                input_tokens,
                output_tokens,
                latency_ms,
                success,
            ),
        )


def _next_state_for(result: TriageResult, threshold: int) -> str:
    if result.triage_score < threshold:
        return "awaiting_inbox_route"
    return "awaiting_resolve"


def _run_triage_attempt(
    conn: Any,
    signal_id: int,
    prompt: str,
    model: str,
    timeout: int,
) -> Optional[TriageResult]:
    """Single call-Ollama-and-parse attempt.

    On successful parse writes the result UPDATE + a ``success=True`` cost
    ledger row and returns the ``TriageResult``. On parse failure writes a
    ``success=False`` cost ledger row and returns ``None`` so ``triage()``
    can loop into the retry path.

    ``OllamaUnavailableError`` is re-raised unchanged — transport failures
    aren't part of the parse-retry budget; the caller's pipeline tick
    handles availability-fallback per §3.
    """
    start = time.monotonic()
    envelope = call_ollama(prompt, model=model, timeout=timeout)
    latency_ms = int((time.monotonic() - start) * 1000)

    raw_text = envelope.get("response")
    input_tokens = envelope.get("prompt_eval_count")
    output_tokens = envelope.get("eval_count")

    try:
        result = parse_gemma_response(raw_text or "")
    except TriageParseError:
        _write_cost_ledger(
            conn,
            signal_id=signal_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            success=False,
        )
        return None

    threshold = _get_triage_threshold()
    next_state = _next_state_for(result, threshold)
    _write_triage_result(conn, signal_id, result, next_state)
    _write_cost_ledger(
        conn,
        signal_id=signal_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        success=True,
    )
    return result


def _read_prompt_inputs(
    conn: Any,
) -> tuple[str, str, str]:
    """Fresh Inv 3 reads — hot.md + feedback ledger — executed once per
    ``triage()`` invocation and shared across all attempts. Returns
    ``(slug_glossary, hot_md_block, ledger_block)``.

    Keeping the read collocated with ``triage()`` (rather than implicit
    inside ``build_prompt``) lets the retry path reuse the already-fresh
    values without re-reading. Inv 3 is satisfied per-invocation, not
    per-prompt-build.
    """
    glossary = _build_glossary()
    hot_md_content = load_hot_md()
    hot_md_block = hot_md_content if hot_md_content else _HOT_MD_FALLBACK
    ledger_rows = load_recent_feedback(conn, limit=20)
    rendered = render_ledger(ledger_rows)
    ledger_block = rendered if rendered.strip() else _LEDGER_FALLBACK
    return glossary, hot_md_block, ledger_block


def _build_stub_result() -> TriageResult:
    """The retries-exhausted stub. Director-visible via
    ``triage_summary='parse_failed'`` + inbox route."""
    return TriageResult(
        primary_matter=None,
        related_matters=(),
        vedana=None,
        triage_score=0,
        triage_confidence=0.0,
        summary=_STUB_SUMMARY,
    )


def triage(
    signal_id: int,
    conn: Any,
    model: str = _DEFAULT_MODEL,
    timeout: int = _DEFAULT_TIMEOUT,
) -> TriageResult:
    """Run Step 1 triage for a single signal. Full side-effect path:
    fetch signal, build prompt, call Ollama, parse, write result + cost,
    transition state. Parse failures absorb internally via the retry
    budget + stub-and-route pattern (§7 row 3) — no ``TriageParseError``
    escapes past ``_RETRY_BUDGET`` attempts.

    Raises:
        LookupError: when the signal_id is not in ``signal_queue``.
        OllamaUnavailableError: when Ollama cannot be reached. Caller
            (pipeline tick) swaps to availability fallback or defers.
            Transport failures are NOT counted against the parse-retry
            budget — the ``_RETRY_BUDGET`` is reserved for malformed
            model output only.
    """
    signal_text = _fetch_signal(conn, signal_id)
    _mark_running(conn, signal_id)

    # Inv 3: fresh reads once per invocation, shared across all attempts.
    glossary, hot_md_block, ledger_block = _read_prompt_inputs(conn)

    template = _load_template()
    signal_truncated = signal_text.replace('"', "'")[:_DEFAULT_SIGNAL_TRUNCATE]

    # Attempt 0 — full prompt (glossary + hot.md + ledger).
    prompt = template.format(
        signal=signal_truncated,
        slug_glossary=glossary,
        hot_md_block=hot_md_block,
        feedback_ledger_block=ledger_block,
    )

    for attempt in range(_RETRY_BUDGET + 1):
        result = _run_triage_attempt(conn, signal_id, prompt, model, timeout)
        if result is not None:
            return result
        # Parse failed on this attempt. Build the next-attempt prompt if
        # retries remain. The pared prompt drops the ledger block — our
        # best guess at the most likely confound — while keeping the
        # glossary + hot.md + signal intact.
        if attempt < _RETRY_BUDGET:
            prompt = _build_pared_prompt(signal_text, glossary, hot_md_block)

    # Retries exhausted. Each failed attempt already wrote its own
    # success=False cost row. Write the stub result + advance to inbox
    # so the Director sees the signal; pipeline keeps flowing.
    stub = _build_stub_result()
    _write_triage_result(conn, signal_id, stub, _INBOX_ROUTE_STATE)
    return stub
