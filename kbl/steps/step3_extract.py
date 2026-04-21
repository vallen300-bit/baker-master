"""Step 3 — Gemma local entity extraction evaluator.

Consumes Step 2 output (``signal_queue.status='awaiting_extract'`` rows),
builds the production prompt per ``briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md``,
calls Ollama, parses JSON, writes structured entities to
``signal_queue.extracted_entities`` + a row to ``kbl_cost_ledger``,
advances state.

CHANDA compliance:
    - **Q1 Loop Test.** Step 3 does not read hot.md / ledger / Gold — not
      a Leg touch. Pass.
    - **Q2 Wish Test.** Structured entities feed Step 5 synthesis. Pass.
    - **Inv 10 (template stability).** Template text is loaded once per
      process from ``kbl/prompts/step3_extract.txt``. No self-modification.
    - **§7 error matrix.** Top-level JSON malformed → retry once; second
      failure writes an empty-entities stub and continues (not a signal
      failure). Sub-key / sub-field hallucinations are tolerated with
      drop-the-bad-bit-keep-the-rest policy inside ``parse_gemma_response``.

State transitions (per task contract):
    awaiting_extract  -->  extract_running  -->  awaiting_classify
                                            \\->  extract_failed
                                                    (only on DB / lookup
                                                     errors, NOT on parse
                                                     errors which recover
                                                     via retry + stub)

Note on Ollama client: this module owns its own ``call_ollama`` helper
mirroring ``kbl.steps.step1_triage.call_ollama``. Consolidation into a
shared ``kbl/ollama.py`` module is intentionally deferred — both PR #8
(Step 1) and this PR land the helper independently; a later refactor PR
can lift once both are on ``main``. Keeping the two helpers behaviorally
identical (same endpoint, sampling, error surface) is the pre-push gate.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from kbl.exceptions import ExtractParseError, OllamaUnavailableError

# ---------------------------- constants ----------------------------

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent / "prompts" / "step3_extract.txt"
)

_OLLAMA_HOST_ENV = "OLLAMA_HOST"
_DEFAULT_OLLAMA_HOST = "http://localhost:11434"

_DEFAULT_MODEL = "gemma2:8b"
_DEFAULT_TIMEOUT = 30
_DEFAULT_SIGNAL_TRUNCATE = 3000
_DEFAULT_NUM_PREDICT = 1024  # Step 3 output can be larger than Step 1

_REQUIRED_KEYS: tuple[str, ...] = (
    "people",
    "orgs",
    "money",
    "dates",
    "references",
    "action_items",
)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_CURRENCIES = frozenset({"EUR", "USD", "CHF", "GBP"})

_ORG_TYPES = frozenset(
    {
        "law_firm",
        "bank",
        "investor",
        "contractor",
        "hotel",
        "family_office",
        "advisor",
        "regulator",
        "other",
    }
)

_DIRECTOR_NAME_TOKENS = frozenset({"dimitry", "vallen"})
_DIRECTOR_COMPANY_TOKENS = frozenset({"brisen", "brisengroup", "brisen group"})

_STATE_RUNNING = "extract_running"
_STATE_NEXT = "awaiting_classify"
_STATE_FAILED = "extract_failed"

_RETRY_BUDGET = 1  # one retry after initial attempt (total 2 calls)


# ---------------------------- result dataclass ----------------------------


@dataclass(frozen=True)
class ExtractedEntities:
    """Parsed + validated Gemma response. Six array-valued keys, always
    present. Values are tuples of dicts — frozen dataclass semantics
    protect the object against accidental caller mutation. Serializer
    below (``to_dict``) hands the JSONB writer a plain-dict shape."""

    people: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    orgs: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    money: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    dates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    references: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    action_items: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "people": [dict(p) for p in self.people],
            "orgs": [dict(o) for o in self.orgs],
            "money": [dict(m) for m in self.money],
            "dates": [dict(d) for d in self.dates],
            "references": [dict(r) for r in self.references],
            "action_items": [dict(a) for a in self.action_items],
        }

    @classmethod
    def empty(cls) -> "ExtractedEntities":
        return cls()


# ---------------------------- template loading ----------------------------


_template_cache: Optional[str] = None


def _load_template() -> str:
    """Read the extract template once per process (Inv 10)."""
    global _template_cache
    if _template_cache is None:
        _template_cache = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return _template_cache


def _reset_template_cache() -> None:
    """Test hook — drops cached template so fixtures can override."""
    global _template_cache
    _template_cache = None


# ---------------------------- prompt builder ----------------------------


def build_prompt(
    signal_text: str,
    source: str,
    primary_matter: Optional[str],
    resolved_thread_paths: Optional[list[str]],
) -> str:
    """Assemble the Step 3 extract prompt.

    ``source`` and ``primary_matter`` are context hints only — the prompt
    instructs Gemma explicitly NOT to extract them as entities. Thread
    context hint surfaces up to the first three resolved paths (from Step
    2) so the model has arc-awareness when deciding whether a reference
    is "that contract we signed" (prior arc) vs. a fresh ID to emit.

    Args:
        signal_text: raw signal content. Quotes escaped to apostrophes so
            the ``Signal: "..."`` wrapper stays well-formed; truncated to
            3000 chars to cap prompt size.
        source: one of ``email | whatsapp | meeting | scan``. Free-form
            strings pass through — the prompt tolerates unknowns.
        primary_matter: canonical slug or ``None``. ``None`` renders as
            "none (null matter)" for model readability.
        resolved_thread_paths: up to the first 3 entries render as a
            semicolon-joined hint; ``None`` / empty renders as
            "new thread".

    Returns:
        Fully-rendered prompt string. Callers must NOT mutate the template.
    """
    matter_hint = primary_matter if primary_matter else "none (null matter)"
    if resolved_thread_paths:
        thread_hint = "; ".join(resolved_thread_paths[:3])
    else:
        thread_hint = "new thread"

    template = _load_template()
    return template.format(
        signal=signal_text.replace('"', "'")[:_DEFAULT_SIGNAL_TRUNCATE],
        source=source,
        matter_hint=matter_hint,
        thread_hint=thread_hint,
    )


# ---------------------------- response parser ----------------------------


def _is_director_person(entry: dict[str, Any]) -> bool:
    """Return True when a ``people`` entry is the Director (Dimitry Vallen).

    Conservative: only strips when BOTH name tokens appear. "Dimitry" as
    a subject ("appoint Dimitry to board of X") would still be filtered
    if both tokens are in `name`, which is why the prompt rule says
    "skip self-references" — the model is expected to not emit this in
    the first place; this is a safety net for signature / sign-off leaks.
    """
    name = str(entry.get("name", "")).lower()
    if not name:
        return False
    tokens = set(re.findall(r"[a-z]+", name))
    return _DIRECTOR_NAME_TOKENS.issubset(tokens)


def _is_director_org(entry: dict[str, Any]) -> bool:
    name = str(entry.get("name", "")).lower().strip()
    if not name:
        return False
    for token in _DIRECTOR_COMPANY_TOKENS:
        if token in name:
            return True
    return False


def _clean_person(entry: Any) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"name": name.strip()}
    for key in ("role", "company"):
        v = entry.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    if _is_director_person(out):
        return None
    return out


def _clean_org(entry: Any) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    out: dict[str, Any] = {"name": name.strip()}
    t = entry.get("type")
    if isinstance(t, str) and t in _ORG_TYPES:
        out["type"] = t
    if _is_director_org(out):
        return None
    return out


def _clean_money(entry: Any) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    amount = entry.get("amount")
    # bool is a subclass of int — reject it before the numeric branch.
    if isinstance(amount, bool):
        return None
    if not isinstance(amount, (int, float)):
        return None
    currency = entry.get("currency")
    if not isinstance(currency, str) or currency not in _VALID_CURRENCIES:
        return None
    out: dict[str, Any] = {"amount": amount, "currency": currency}
    context = entry.get("context")
    if isinstance(context, str) and context.strip():
        out["context"] = context.strip()
    return out


def _clean_date(entry: Any) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    date = entry.get("date")
    if not isinstance(date, str) or not _ISO_DATE_RE.match(date):
        return None
    out: dict[str, Any] = {"date": date}
    event = entry.get("event")
    if isinstance(event, str) and event.strip():
        out["event"] = event.strip()
    return out


def _clean_reference(entry: Any) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    ref_id = entry.get("id")
    if not isinstance(ref_id, str) or not ref_id.strip():
        return None
    out: dict[str, Any] = {"id": ref_id.strip()}
    t = entry.get("type")
    if isinstance(t, str) and t.strip():
        out["type"] = t.strip()
    return out


def _clean_action(entry: Any) -> Optional[dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    actor = entry.get("actor")
    action = entry.get("action")
    if not isinstance(actor, str) or not actor.strip():
        return None
    if not isinstance(action, str) or not action.strip():
        return None
    out: dict[str, Any] = {"actor": actor.strip(), "action": action.strip()}
    deadline = entry.get("deadline")
    if isinstance(deadline, str) and deadline.strip():
        out["deadline"] = deadline.strip()
    return out


_CLEANERS = {
    "people": _clean_person,
    "orgs": _clean_org,
    "money": _clean_money,
    "dates": _clean_date,
    "references": _clean_reference,
    "action_items": _clean_action,
}


def parse_gemma_response(raw: str) -> ExtractedEntities:
    """Parse Gemma's structured JSON extract output.

    Parse policy (§7 error matrix):
        - Empty / non-JSON top-level       → raise ``ExtractParseError``.
        - Non-object top-level             → raise ``ExtractParseError``.
        - Missing top-level key            → fill with ``[]``, continue.
        - Top-level value not a list       → replace with ``[]``, continue.
        - Sub-field hallucination          → drop that entry, keep siblings.
        - Director self-reference leaks    → strip silently.

    Partial-JSON tolerance: if the parser can read the envelope at all,
    it returns a best-effort ``ExtractedEntities`` rather than raising.
    Only a structurally unreadable response (malformed JSON, array root)
    triggers the retry path in ``extract()``.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ExtractParseError("empty model response")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ExtractParseError(f"invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ExtractParseError(
            f"top-level must be object (got {type(data).__name__})"
        )

    cleaned: dict[str, tuple[dict[str, Any], ...]] = {}
    for key in _REQUIRED_KEYS:
        raw_list = data.get(key)
        if not isinstance(raw_list, list):
            cleaned[key] = ()
            continue
        entries: list[dict[str, Any]] = []
        cleaner = _CLEANERS[key]
        for item in raw_list:
            out = cleaner(item)
            if out is not None:
                entries.append(out)
        cleaned[key] = tuple(entries)

    return ExtractedEntities(**cleaned)


# ---------------------------- Ollama call ----------------------------


def call_ollama(
    prompt: str,
    model: str = _DEFAULT_MODEL,
    timeout: int = _DEFAULT_TIMEOUT,
    host: Optional[str] = None,
) -> dict[str, Any]:
    """POST ``prompt`` to Ollama's ``/api/generate`` endpoint.

    Mirrors ``kbl.steps.step1_triage.call_ollama`` byte-for-byte except
    ``num_predict=1024`` (Step 3 outputs can be longer than Step 1).
    Raises ``OllamaUnavailableError`` on timeout / connection refused /
    non-2xx. Retry is the caller's concern.
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
            "num_predict": _DEFAULT_NUM_PREDICT,
        },
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raise OllamaUnavailableError(
            f"Ollama HTTP {e.code} at {url}: {e.reason}"
        ) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise OllamaUnavailableError(f"Ollama unreachable at {url}: {e}") from e

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise OllamaUnavailableError(f"Ollama returned non-JSON envelope: {e}") from e


# ---------------------------- pipeline entry ----------------------------


def _fetch_signal_context(conn: Any, signal_id: int) -> tuple[str, str, Optional[str], list[str]]:
    """Return ``(raw_content, source, primary_matter, resolved_thread_paths)``.

    Raises ``LookupError`` when the signal row is absent.

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
            "       source, primary_matter, resolved_thread_paths "
            "FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"signal_queue row not found: id={signal_id}")
    raw_content = row[0] or ""
    source = row[1] or ""
    primary_matter = row[2]
    resolved_raw = row[3]
    # resolved_thread_paths is JSONB; psycopg2 returns it as list[str]|None.
    # Defend against string (old rows) + None.
    if isinstance(resolved_raw, list):
        paths = [p for p in resolved_raw if isinstance(p, str)]
    elif isinstance(resolved_raw, str):
        try:
            parsed = json.loads(resolved_raw)
            paths = [p for p in parsed if isinstance(p, str)] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            paths = []
    else:
        paths = []
    return raw_content, source, primary_matter, paths


def _mark_running(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_RUNNING, signal_id),
        )


def _write_extraction_result(
    conn: Any, signal_id: int, entities: ExtractedEntities, next_state: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET "
            "  extracted_entities = %s::jsonb, "
            "  status = %s "
            "WHERE id = %s",
            (json.dumps(entities.to_dict()), next_state, signal_id),
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
            "VALUES (%s, 'extract', %s, %s, %s, %s, 0, %s)",
            (signal_id, model, input_tokens, output_tokens, latency_ms, success),
        )


def _envelope_response(envelope: dict[str, Any]) -> tuple[str, Optional[int], Optional[int]]:
    """Extract ``(response_text, input_tokens, output_tokens)`` from an
    Ollama ``/api/generate`` envelope. Missing counters are returned as
    ``None`` rather than raising."""
    return (
        envelope.get("response") or "",
        envelope.get("prompt_eval_count"),
        envelope.get("eval_count"),
    )


def extract(
    signal_id: int,
    conn: Any,
    model: str = _DEFAULT_MODEL,
    timeout: int = _DEFAULT_TIMEOUT,
) -> ExtractedEntities:
    """Run Step 3 extraction for a single signal.

    Full side-effect path: fetch signal context, build prompt, call
    Ollama, parse. On top-level parse failure retry once; on second
    failure write an empty-entities stub + cost ledger row with
    ``success=False`` and advance state to ``awaiting_classify`` so the
    pipeline keeps flowing (§7 row 1). DB / lookup errors raise and
    leave state at ``extract_running`` — operator triage territory.

    Raises:
        LookupError: signal_id absent from ``signal_queue``.
        OllamaUnavailableError: Ollama unreachable. Caller defers.
    """
    signal_text, source, primary_matter, thread_paths = _fetch_signal_context(
        conn, signal_id
    )
    _mark_running(conn, signal_id)

    prompt = build_prompt(signal_text, source, primary_matter, thread_paths)

    total_latency_ms = 0
    last_input_tokens: Optional[int] = None
    last_output_tokens: Optional[int] = None

    attempt = 0
    while True:
        start = time.monotonic()
        envelope = call_ollama(prompt, model=model, timeout=timeout)
        total_latency_ms += int((time.monotonic() - start) * 1000)
        raw_text, last_input_tokens, last_output_tokens = _envelope_response(envelope)
        try:
            result = parse_gemma_response(raw_text)
        except ExtractParseError:
            if attempt >= _RETRY_BUDGET:
                stub = ExtractedEntities.empty()
                _write_extraction_result(conn, signal_id, stub, _STATE_NEXT)
                _write_cost_ledger(
                    conn,
                    signal_id=signal_id,
                    model=model,
                    input_tokens=last_input_tokens,
                    output_tokens=last_output_tokens,
                    latency_ms=total_latency_ms,
                    success=False,
                )
                return stub
            attempt += 1
            continue
        break

    _write_extraction_result(conn, signal_id, result, _STATE_NEXT)
    _write_cost_ledger(
        conn,
        signal_id=signal_id,
        model=model,
        input_tokens=last_input_tokens,
        output_tokens=last_output_tokens,
        latency_ms=total_latency_ms,
        success=True,
    )
    return result
