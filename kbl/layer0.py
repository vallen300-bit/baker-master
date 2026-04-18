"""Layer 0 deterministic filter — Step 0 of the KBL-B pipeline.

Evaluates a ``Signal`` against the ruleset loaded by ``kbl.layer0_rules``
and returns ``Layer0Decision("pass" | "drop", rule_name, detail)``.

Design (per ``briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md`` @ ``64d1712``):

    1. **Never-drop invariants run first** — cheapest checks, ordered:
        a. ``source='scan'`` — Director's own query, always passes.
        b. ``is_director_sender(signal)`` — C2 Inv 5 author-authority.
        c. ``primary_matter_hint`` present — pre-tagged ingestion.
        d. VIP sender — S4 soft-fail CLOSED (pass on lookup failure).
        e. Topic override — active slug or alias mentioned as whole-word,
           short-slug (<4 char canonical) requires alias match (S3).
    2. **Rule walk** — first-match-wins over the rules list; source filter
       (``source`` == signal.source or ``*``) applied before match dispatch.
    3. **Content-hash dedupe** handled by the ``content_hash_seen_within_hours``
       rule handler (S5). Hash INSERT on PASS only is done by
       ``_process_layer0``, not by the rule handler.
    4. **1-in-50 review sampling** (S6) done by ``_process_layer0`` on
       DROP when ``signal.id % 50 == 0``.

Module boundaries:
    - This module is the EVALUATOR. It does NOT read the ruleset YAML
      directly; it calls ``kbl.layer0_rules.load_layer0_rules()``.
    - Writers (dedupe insert, review insert) live in ``kbl.layer0_dedupe``.
    - Pipeline wiring (``kbl/pipeline_tick.py`` call-site) is a separate
      ticket — this module exposes ``_process_layer0(signal, conn)`` for
      that caller to import.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kbl import layer0_dedupe, layer0_rules
from kbl.layer0_rules import Layer0Rule, Layer0Rules

try:  # slug registry may be absent in constrained test envs
    from kbl import slug_registry as _slug_registry
except Exception:  # pragma: no cover — defensive
    _slug_registry = None  # type: ignore[assignment]

from baker.director_identity import is_director_sender

logger = logging.getLogger(__name__)


# ----------------------------- signal + decision -----------------------------


@dataclass
class Signal:
    """Minimal shape the evaluator needs. Callers may subclass or adapt.

    ``id`` is used for deterministic 1-in-50 review sampling; must be a
    positive integer (matches ``signal_queue.id`` BIGINT after PR #5).
    """

    id: int
    source: str
    raw_content: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Layer0Decision:
    """Verdict from ``evaluate``. Immutable — callers never mutate."""

    verdict: str            # "pass" | "drop"
    rule_name: Optional[str] = None   # populated only on "drop"
    detail: Optional[str] = None      # rule.detail from YAML, for logging


# ---------------------------- rule-type handlers ----------------------------
#
# Each handler: ``(rule_match_spec: dict, signal: Signal) -> bool``.
# Returns True when the rule fires (→ DROP). Handlers must be pure + I/O-free
# EXCEPT the content-hash one which reads the dedupe table (documented).

_VIPCheck = Callable[[dict[str, Any]], bool]


def _lc(value: Any) -> str:
    return (value or "").lower() if isinstance(value, str) else ""


def _get_payload(signal: Signal, key: str, default: Any = None) -> Any:
    return signal.payload.get(key, default) if signal.payload else default


def _extract_email_addr(raw: str) -> str:
    """Strip ``Name <addr@domain>`` wrapping. Lowercase output."""
    if not raw:
        return ""
    s = raw.strip()
    if "<" in s and ">" in s:
        s = s.split("<", 1)[1].rsplit(">", 1)[0]
    return s.strip().lower()


def _email_sender_domain_contains(spec: dict, signal: Signal) -> bool:
    sender = _extract_email_addr(_get_payload(signal, "sender", ""))
    if "@" not in sender:
        return False
    domain = sender.split("@", 1)[1]
    needles = spec.get("match_any") or spec.get("sender_domain_in") or []
    if not isinstance(needles, list):
        return False
    return any(isinstance(n, str) and n.lower() in domain for n in needles)


def _email_sender_local_part_matches(spec: dict, signal: Signal) -> bool:
    sender = _extract_email_addr(_get_payload(signal, "sender", ""))
    if "@" not in sender:
        return False
    local = sender.split("@", 1)[0]
    patterns = spec.get("patterns") or []
    if not isinstance(patterns, list):
        return False
    for pat in patterns:
        if not isinstance(pat, str):
            continue
        try:
            if re.search(pat, local, re.IGNORECASE):
                return True
        except re.error:
            logger.warning("layer0: malformed local-part pattern %r skipped", pat)
    return False


def _wa_chat_id_suffix(spec: dict, signal: Signal) -> bool:
    chat_id = _get_payload(signal, "chat_id", "")
    if not isinstance(chat_id, str):
        return False
    suffixes = spec.get("suffixes") or []
    return any(isinstance(s, str) and chat_id.endswith(s) for s in suffixes)


def _wa_minimum_content_length(spec: dict, signal: Signal) -> bool:
    """Fires when message content is shorter than ``threshold`` chars.

    Accepts both the new ``content_length_lt`` key and legacy
    ``threshold`` / ``min_chars`` keys so rules authored against the
    evaluator test fixture OR the B3 production YAML both work.
    """
    threshold = spec.get("content_length_lt")
    if threshold is None:
        threshold = spec.get("threshold")
    if threshold is None:
        threshold = spec.get("min_chars")
    if threshold is None:
        return False
    body = signal.raw_content or ""
    return len(body) < int(threshold)


def _content_starts_with_marker(spec: dict, signal: Signal) -> bool:
    """S2: anchor Baker-echo drop on the literal ``baker_scan:`` prefix."""
    body = (signal.raw_content or "").lstrip()
    markers = spec.get("markers") or []
    return any(isinstance(m, str) and body.startswith(m) for m in markers)


def _meeting_duration_min_seconds(spec: dict, signal: Signal) -> bool:
    threshold = spec.get("threshold")
    if threshold is None:
        return False
    duration = _get_payload(signal, "duration_sec")
    if not isinstance(duration, (int, float)):
        return False
    return duration < int(threshold)


def _meeting_transcript_quality(spec: dict, signal: Signal) -> bool:
    content = signal.raw_content or ""
    tokens = content.split()
    min_words = spec.get("min_words")
    if isinstance(min_words, int) and len(tokens) < min_words:
        return True
    max_unknown = spec.get("max_unknown_speaker_ratio")
    if isinstance(max_unknown, (int, float)):
        lines = [l for l in content.split("\n") if ":" in l]
        if lines:
            unknown = sum(
                1 for l in lines if l.strip().lower().startswith("unknown:")
            )
            if unknown / len(lines) >= float(max_unknown):
                return True
    min_unique = spec.get("min_unique_tokens_ratio")
    if isinstance(min_unique, (int, float)) and tokens:
        lowered = [t.lower() for t in tokens]
        ratio = len(set(lowered)) / len(lowered)
        if ratio < float(min_unique):
            return True
    return False


def _content_hash_seen_within_hours(spec: dict, signal: Signal) -> bool:
    """S5: read side. Caller is expected to have supplied ``conn`` via
    the evaluate() context when using this handler. The handler falls
    back to returning False if no connection is available — the hash
    check then acts as a no-op and the signal flows through.
    """
    conn = signal.payload.get("_kbl_conn") if signal.payload else None
    if conn is None:
        return False
    h = layer0_dedupe.content_hash(signal.raw_content)
    try:
        return layer0_dedupe.has_seen_recent(conn, h)
    except Exception:
        # S4 soft-fail-CLOSED for dedupe reads: DB blip must not drop the
        # signal. Log + treat as not-seen.
        logger.warning("layer0: dedupe read failed — treating as unseen", exc_info=True)
        return False


_RULE_DISPATCHERS: dict[str, Callable[[dict, Signal], bool]] = {
    "email_sender_domain_contains": _email_sender_domain_contains,
    "email_sender_local_part_matches": _email_sender_local_part_matches,
    "wa_chat_id_suffix": _wa_chat_id_suffix,
    "content_min_chars": _wa_minimum_content_length,
    "content_starts_with_marker": _content_starts_with_marker,
    "meeting_duration_min_seconds": _meeting_duration_min_seconds,
    "meeting_transcript_quality": _meeting_transcript_quality,
    "content_hash_seen_within_hours": _content_hash_seen_within_hours,
}


def _rule_applies_to_source(rule: Layer0Rule, signal: Signal) -> bool:
    return rule.source in ("*", signal.source)


def _rule_fires(rule: Layer0Rule, signal: Signal) -> bool:
    """Match predicates come in two shapes in the real rule YAML:

    1. ``match: {sender_domain_in: [...]}`` — older B3 style used in the
       test fixture for LOADER-1. Predicate key implies the handler.
    2. ``type: email_sender_domain_contains``, plus top-level keys at the
       same level as ``match`` — the production B3 Step 0 spec.

    Real rules land in baker-vault under style 2. For the evaluator we
    honor style-2 when a ``type`` is present, and best-effort map style 1
    onto the same handlers by inferring the type from the match dict's
    first key.
    """
    # Style 2: explicit ``type`` field. Real production rules live here.
    rule_type = rule.match.get("type") if isinstance(rule.match, dict) else None
    if isinstance(rule_type, str) and rule_type in _RULE_DISPATCHERS:
        return _RULE_DISPATCHERS[rule_type](rule.match, signal)

    # Fallback: derive from first key. Handles style-1 fixtures like
    # ``match: {sender_domain_in: [...]}``.
    if isinstance(rule.match, dict) and rule.match:
        first_key = next(iter(rule.match.keys()))
        inferred = _STYLE1_KEY_TO_TYPE.get(first_key)
        if inferred and inferred in _RULE_DISPATCHERS:
            return _RULE_DISPATCHERS[inferred](rule.match, signal)

    logger.warning(
        "layer0: rule %r has unknown/missing match shape — skipping",
        rule.name,
    )
    return False


_STYLE1_KEY_TO_TYPE: dict[str, str] = {
    "sender_domain_in": "email_sender_domain_contains",
    "content_length_lt": "content_min_chars",
    "markers": "content_starts_with_marker",
}


# ------------------------- never-drop invariant helpers -------------------------


def _has_primary_matter_hint(signal: Signal) -> bool:
    return bool(_get_payload(signal, "primary_matter_hint"))


def _default_vip_check(payload: dict[str, Any]) -> bool:
    """Resolve ``is_vip_sender`` lazily from ``baker.vip_contacts``.

    If the module isn't present (it's not shipped yet — future KBL-C),
    we treat the check as "no VIP data available" → False. The caller
    applies S4 soft-fail-CLOSED semantics when the call ITSELF raises;
    here, an absent module is NOT a raise — it's a definitive "unknown".
    """
    try:
        from baker.vip_contacts import is_vip_sender  # type: ignore[import-not-found]
    except Exception:
        return False
    return bool(is_vip_sender(payload))


def _mentions_active_slug_or_alias(content: str) -> bool:
    """S3: whole-word match against active slugs + aliases.

    Short slugs (canonical <4 chars — e.g., ``ao``, ``mo``) require an
    alias match; their canonical token is rejected alone to prevent
    false dictionary hits in arbitrary prose.

    Raises on any slug-registry failure so the caller can apply S4
    soft-fail CLOSED.
    """
    if _slug_registry is None:
        return False
    body = (content or "").lower()
    if not body:
        return False
    slugs = _slug_registry.active_slugs()
    for slug in slugs:
        aliases = _slug_registry.aliases_for(slug)
        candidates: list[str] = list(aliases)
        primary = slug.split("-")[0]
        if len(primary) >= 4:
            candidates.append(primary)
        for term in candidates:
            if not term:
                continue
            if re.search(rf"\b{re.escape(term.lower())}\b", body):
                return True
    return False


# ---------------------------- public API ----------------------------


def evaluate(
    signal: Signal,
    ruleset: Optional[Layer0Rules] = None,
    vip_checker: Optional[_VIPCheck] = None,
) -> Layer0Decision:
    """Run Layer 0 invariant checks + rule walk. Returns a decision.

    Args:
        signal: the signal to evaluate.
        ruleset: optional pre-loaded ``Layer0Rules`` (test hook). When
            None, the module-level cache is used via
            ``layer0_rules.load_layer0_rules()``.
        vip_checker: optional callable to override the VIP resolver (test
            hook). Accepts a payload dict, returns bool. When None, a
            lazy import of ``baker.vip_contacts.is_vip_sender`` is used.
    """
    # 1a. scan source — Director's own query, never dropped.
    if signal.source == "scan":
        return Layer0Decision(verdict="pass")

    # 1b. C2: Director-sender (Inv 5).
    try:
        if is_director_sender(signal):
            return Layer0Decision(verdict="pass")
    except Exception:
        # Author-authority check should never blow up, but if it does,
        # don't take the whole pipeline down for it. Log + continue.
        logger.warning("layer0: director-sender check failed", exc_info=True)

    # 1c. Pre-tagged matter hint — trust upstream tagger.
    if _has_primary_matter_hint(signal):
        return Layer0Decision(verdict="pass")

    # 1d. VIP sender — S4 soft-fail CLOSED.
    checker = vip_checker or _default_vip_check
    try:
        if checker(signal.payload or {}):
            return Layer0Decision(verdict="pass")
    except Exception:
        logger.warning(
            "layer0: vip_lookup_failed_pass_through (S4 soft-fail CLOSED)",
            exc_info=True,
        )
        return Layer0Decision(verdict="pass")

    # 1e. Slug/alias topic override — S3 + S4 parallel soft-fail CLOSED.
    try:
        if _mentions_active_slug_or_alias(signal.raw_content):
            return Layer0Decision(verdict="pass")
    except Exception:
        logger.warning(
            "layer0: slug_registry_unreachable_pass_through (S4 soft-fail CLOSED)",
            exc_info=True,
        )
        return Layer0Decision(verdict="pass")

    # 2. Rule walk — first match wins.
    rules = ruleset if ruleset is not None else layer0_rules.load_layer0_rules()
    for rule in rules.rules:
        if not _rule_applies_to_source(rule, signal):
            continue
        if _rule_fires(rule, signal):
            return Layer0Decision(
                verdict="drop", rule_name=rule.name, detail=rule.detail
            )

    # 3. No rule matched — PASS.
    return Layer0Decision(verdict="pass")


# ------------------------- pipeline wrapper -------------------------


_REVIEW_SAMPLE_MODULUS = 50


def _process_layer0(
    signal: Signal,
    conn: Any,
    ruleset: Optional[Layer0Rules] = None,
    vip_checker: Optional[_VIPCheck] = None,
) -> Layer0Decision:
    """Evaluate + apply Step-0 side effects (dedupe insert, review sample).

    Side-effect policy:
        - PASS → INSERT hash row into ``kbl_layer0_hash_seen`` (S5). Drops
          are NOT inserted; a false-positive drop must not silently
          suppress future legitimate copies.
        - DROP + ``signal.id % 50 == 0`` → INSERT row into
          ``kbl_layer0_review`` (S6). Sampling is deterministic for
          audit reproducibility.
        - All writes bubble exceptions after best-effort rollback so the
          caller's transaction boundary stays truthful.

    Commit/rollback is the caller's responsibility. This wrapper runs
    inside whatever transaction the pipeline dispatcher opens.
    """
    # Expose conn to the dedupe-read rule handler without widening the
    # handler signature. Handlers intentionally take (spec, signal) only.
    signal.payload.setdefault("_kbl_conn", conn)
    try:
        decision = evaluate(signal, ruleset=ruleset, vip_checker=vip_checker)
    finally:
        signal.payload.pop("_kbl_conn", None)

    if decision.verdict == "pass":
        if conn is not None and signal.raw_content:
            h = layer0_dedupe.content_hash(signal.raw_content)
            layer0_dedupe.insert_hash(
                conn,
                content_hash_value=h,
                source_signal_id=signal.id,
                source_kind=signal.source,
            )
        return decision

    # DROP path: sample for review if signal.id lands on the 1-in-50 cadence.
    if (
        conn is not None
        and signal.id
        and (signal.id % _REVIEW_SAMPLE_MODULUS) == 0
    ):
        layer0_dedupe.kbl_layer0_review_insert(
            conn,
            signal_id=signal.id,
            dropped_by_rule=decision.rule_name or "unknown",
            signal_excerpt=signal.raw_content or "",
            source_kind=signal.source,
        )
    return decision
