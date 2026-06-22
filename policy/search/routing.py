"""Deterministic-first routing for the AI Hotel Lab search layer (Step 3).

Routing decides WHICH dashboard section a result belongs to. It is:

* **Deterministic-first** — 11 keyword rules (codex-arch #3679) run before any LLM.
* **LLM assist-only** — the LLM may PROPOSE a target + reason, never finalise, never
  promote, never mutate policy. The LLM is an injected callable so the layer stays
  DB-free / network-free in tests (default: no LLM, deterministic only).
* **Human-overridable always** — :func:`apply_override` records the override
  (actor / prior / new / rationale / timestamp) and NEVER touches policy fields.

Routing is NOT a visibility control. It never widens access; classification /
allowed_orgs / lifecycle are owned by the Step-1 engine. A sensitive or
never-external signal routes to ``risk_permissions_review`` (rule 11) so a human
sees it — but the engine still decides whether anyone external ever sees it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional, Sequence

from policy.models import Org, Principal, Sensitivity
from policy.search.models import (
    RawSignal,
    RouteTarget,
    RoutingMethod,
    RoutingOverride,
    RoutingSuggestion,
)

# A routing LLM is any callable returning a (RouteTarget, reason, confidence) tuple
# given the text. It is ASSIST-ONLY — its output is wrapped as a proposal.
LlmRouter = Callable[[str], "tuple[RouteTarget, str, float]"]

_RULE_CONFIDENCE = 0.85       # deterministic keyword match
_NOMATCH_CONFIDENCE = 0.2     # no rule fired
_LLM_CONFIDENCE_CAP = 0.6     # LLM assist can never out-rank a deterministic rule


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# The 11 deterministic rules (codex-arch #3679). Order is documentation only;
# resolution below is set-based so multi-match conflicts are detected, not hidden.
# --------------------------------------------------------------------------- #
# (rule_no, primary target, keyword substrings — matched case-insensitively)
_RULES: tuple[tuple[int, RouteTarget, tuple[str, ...]], ...] = (
    (1, RouteTarget.SANTA_CLARA_SITE_THESIS,
     ("parcel", "permit", "zoning", "gis", "assessor", "site-ownership",
      "site ownership", "site access", "traffic", "apn", "conditional-use",
      "conditional use", "easement")),
    (2, RouteTarget.FIELD_EVIDENCE,
     ("field photo", "field-photo", "gps", "video", "voice note", "voice-note",
      "site photo", "site-photo", "photo capture", "drone footage", "walkthrough")),
    (3, RouteTarget.MARKET_PROOF_COMPETITIVE_SET,
     ("competitor", "comparable", "local hotel", "benchmark", "comp set",
      "comp-set", "ai-hospitality benchmark", "competitive set")),
    (4, RouteTarget.NVIDIA_LIGHTHOUSE,
     ("nvidia", "gpu", "ai-infra", "ai infra", "lighthouse", "dgx",
      "partner signal", "accelerated compute")),
    (5, RouteTarget.MANDARIN_ORIENTAL_OPERATOR_LOGIC,
     ("mohg", "mandarin", "operator", "brand standard", "guest-experience",
      "guest experience", "service-standard", "service standard", "hotel ops")),
    (6, RouteTarget.BUSINESS_CASE_FINANCING,
     ("bank", "debt", "financing", "cap-stack", "cap stack", "capital stack",
      "investor-economics", "investor economics", "term sheet", "loan", "ltv")),
    (7, RouteTarget.RESIDENCE_BUYERS,
     ("branded residence", "residence buyer", "buyer demand",
      "luxury-residential", "luxury residential", "residential comps",
      "residence sales")),
    (8, RouteTarget.MARKETING_PR,
     ("press", "narrative", "public-perception", "public perception",
      "campaign", "media coverage", "pr push", "press release")),
    (9, RouteTarget.VENDORS_FUTURE_OPERATING_LAYER,
     ("vendor", "bms", "pms", "smart lock", "locks", "hvac", "digital-twin",
      "digital twin", "building management")),
)

# Rule 10 — empty / blocked / missing-data signals route to the roadmap.
_ROADMAP_KEYWORDS: tuple[str, ...] = (
    "missing data", "zero result", "zero results", "unresolved", "empty state",
    "blocked next action", "no data", "needs follow-up", "gap to close",
)

# Rule 11 — unclear / conflicting / sensitive / permission-risk → risk review.
_RISK_KEYWORDS: tuple[str, ...] = (
    "unclear", "conflicting", "sensitive", "permission-risk", "permission risk",
    "confidential", "legal hold", "cannot determine", "ambiguous classification",
)


def _matched_targets(text: str) -> list[tuple[int, RouteTarget]]:
    t = text.lower()
    return [(no, tgt) for (no, tgt, kws) in _RULES if any(k in t for k in kws)]


def route_deterministic(
    text: str,
    *,
    sensitivity: Optional[Sensitivity] = None,
    never_external: bool = False,
) -> RoutingSuggestion:
    """Apply the 11 deterministic rules. ALWAYS returns a suggestion — never None.

    Precedence (fail-safe first):

    * **Rule 11 (sensitive/permission-risk)** wins outright — a never-external or
      sensitivity-tagged signal, or risk keywords, routes to ``risk_permissions_review``
      so a human decides. This is intentionally conservative.
    * **Rule 2 + Rule 1** is a designed pair, not a conflict: a site-relevant field
      capture is ``field_evidence`` primary with ``santa_clara_site_thesis`` secondary.
    * **≥2 remaining primary targets** is a genuine conflict → ``source_gap_unassigned_review``.
    * **Exactly 1 primary** → that target.
    * **Rule 10** (no primary, roadmap keywords) → ``execution_roadmap``.
    * **No match** → ``source_gap_unassigned_review`` (never a silent default placement).
    """

    text = text or ""

    # Rule 11 — sensitive / permission-risk fail-safe (highest precedence).
    if never_external or sensitivity is not None or any(
        k in text.lower() for k in _RISK_KEYWORDS
    ):
        why = (
            "never-external/sensitive source" if (never_external or sensitivity)
            else "unclear/conflicting/permission-risk keywords"
        )
        return RoutingSuggestion(
            route_target=RouteTarget.RISK_PERMISSIONS_REVIEW,
            route_reason=f"rule 11: {why} → human permission review",
            method=RoutingMethod.RULE,
            confidence=_RULE_CONFIDENCE,
            rule_no=11,
        )

    matches = _matched_targets(text)
    primaries = {tgt for _, tgt in matches}
    secondary: tuple[RouteTarget, ...] = ()

    # Rule 2 + Rule 1 designed pair: site-relevant field capture.
    if (
        RouteTarget.FIELD_EVIDENCE in primaries
        and RouteTarget.SANTA_CLARA_SITE_THESIS in primaries
    ):
        primaries.discard(RouteTarget.SANTA_CLARA_SITE_THESIS)
        secondary = (RouteTarget.SANTA_CLARA_SITE_THESIS,)

    if len(primaries) >= 2:
        targets = sorted(t.value for t in primaries)
        return RoutingSuggestion(
            route_target=RouteTarget.SOURCE_GAP_UNASSIGNED_REVIEW,
            route_reason=f"rule 11: conflicting routes {targets} → unassigned review",
            method=RoutingMethod.RULE,
            confidence=_RULE_CONFIDENCE,
            rule_no=11,
        )

    if len(primaries) == 1:
        target = next(iter(primaries))
        rule_no = next(no for no, tgt in matches if tgt is target)
        return RoutingSuggestion(
            route_target=target,
            route_reason=f"rule {rule_no}: keyword match → {target.value}",
            method=RoutingMethod.RULE,
            confidence=_RULE_CONFIDENCE,
            secondary_targets=secondary,
            rule_no=rule_no,
        )

    # Rule 10 — explicit empty / blocked / missing-data signal.
    if any(k in text.lower() for k in _ROADMAP_KEYWORDS):
        return RoutingSuggestion(
            route_target=RouteTarget.EXECUTION_ROADMAP,
            route_reason="rule 10: missing-data/blocked/empty signal → execution roadmap",
            method=RoutingMethod.RULE,
            confidence=_RULE_CONFIDENCE,
            rule_no=10,
        )

    # No rule fired — never invent a confident placement.
    return RoutingSuggestion(
        route_target=RouteTarget.SOURCE_GAP_UNASSIGNED_REVIEW,
        route_reason="no deterministic rule matched → unassigned review",
        method=RoutingMethod.RULE,
        confidence=_NOMATCH_CONFIDENCE,
        rule_no=11,
    )


def propose_route(
    text: str,
    *,
    sensitivity: Optional[Sensitivity] = None,
    never_external: bool = False,
    llm_router: Optional[LlmRouter] = None,
    llm_text: Optional[str] = None,
) -> RoutingSuggestion:
    """Deterministic-first, LLM-assist-second routing proposal.

    The deterministic rules run ALWAYS. The LLM is consulted ONLY when the
    deterministic pass produced no confident placement (an unassigned-review with
    low confidence) AND an ``llm_router`` is supplied. The LLM output is wrapped as
    a PROPOSAL (``method=llm``), capped below deterministic confidence, and CANNOT
    override a fail-safe risk/permission routing — it never finalises or promotes.

    **Prompt-injection defence (deputy-codex T8/AC9).** The LLM receives ``llm_text``
    — a PROJECTION-SAFE descriptor (structural metadata + partner-safe claim) — NOT
    the full text and NEVER raw bodies / internal titles. Whatever the LLM returns
    is schema-validated: a non-``RouteTarget`` answer is discarded and the
    deterministic route stands. The LLM's only output channel is a route SUGGESTION
    — it has no path to mutate policy, promote, or widen visibility, so a malicious
    source string cannot make routing reveal a hidden document or skip a gate.
    """

    deterministic = route_deterministic(
        text, sensitivity=sensitivity, never_external=never_external
    )

    # The LLM never overrides the conservative fail-safe routes, and never overrides
    # a confident deterministic placement.
    if (
        llm_router is None
        or deterministic.confidence >= _RULE_CONFIDENCE
        or deterministic.route_target is RouteTarget.RISK_PERMISSIONS_REVIEW
    ):
        return deterministic

    # T8: the LLM only ever sees projection-safe text, never raw text/titles.
    safe_text = llm_text if llm_text is not None else text
    try:
        proposal = llm_router(safe_text)
        target, reason, conf = proposal  # may raise if the LLM returned junk
    except Exception:  # noqa: BLE001 - LLM failure / bad shape -> deterministic, fail-safe
        return deterministic

    # Schema validation: a non-RouteTarget (e.g. an injected free-text "command")
    # is rejected outright — the deterministic route stands.
    if not isinstance(target, RouteTarget):
        return deterministic
    try:
        conf = min(float(conf), _LLM_CONFIDENCE_CAP)
    except (TypeError, ValueError):
        return deterministic

    return RoutingSuggestion(
        route_target=target,
        route_reason=f"llm assist: {str(reason)[:240]}",
        method=RoutingMethod.LLM,
        confidence=conf,
        rule_no=None,
    )


def apply_override(
    signal_id: str,
    suggestion: RoutingSuggestion,
    new_target: RouteTarget,
    actor: Principal,
    *,
    rationale: str,
    recorder: Optional[Callable[[RoutingOverride], None]] = None,
) -> RoutingOverride:
    """Record a human override of a routing suggestion (AC5). Human override always
    wins; it is audited and NEVER mutates policy.

    Routing is a placement decision, so any internal actor may re-file a result —
    but the override changes ONLY ``route_target``. It cannot touch classification,
    allowed_orgs, or lifecycle (those stay the Step-1 engine's), so it can never
    silently widen visibility (governance invariant).
    """

    if not isinstance(new_target, RouteTarget):
        raise ValueError(f"override target must be a RouteTarget, got {new_target!r}")

    override = RoutingOverride(
        signal_id=signal_id,
        prior_target=suggestion.route_target,
        new_target=new_target,
        actor_org=getattr(actor.org, "value", str(actor.org)),
        actor_role=actor.role,
        actor_is_ai=actor.is_ai,
        rationale=rationale,
        timestamp=_now(),
    )
    if recorder is not None:
        recorder(override)
    return override


def apply_override_to_signal(
    signal: RawSignal,
    new_target: RouteTarget,
    actor: Principal,
    *,
    rationale: str,
    recorder: Optional[Callable[[RoutingOverride], None]] = None,
) -> RoutingOverride:
    """Override the proposed route on a stored ``RawSignal`` (AC5), mutating ONLY the
    ``proposed_route_target`` and appending an audit-trail ref. Policy is untouched."""

    suggestion = RoutingSuggestion(
        route_target=signal.proposed_route_target,
        route_reason=signal.route_reason,
        method=RoutingMethod.RULE,
        confidence=signal.confidence if signal.confidence is not None else 0.0,
    )
    override = apply_override(
        signal.signal_id, suggestion, new_target, actor,
        rationale=rationale, recorder=recorder,
    )
    signal.proposed_route_target = new_target
    signal.route_reason = f"human override by {override.actor_role}: {rationale}"
    signal.audit_trail = signal.audit_trail + (f"override:{override.timestamp}",)
    return override
