"""The search runner for the AI Hotel Lab (Step 3) — a CONSUMER of the policy engine.

This module searches across Step-2 registered sources and returns results gated
through the LIVE Step-1 policy engine. It writes NO second allow path:

* **External principals are ALWAYS routed through the projection path**, regardless
  of the requested ``SearchMode`` or any crafted filter. An external caller asking
  for ``internal_global`` is silently served partner-safe projections only — a
  crafted query / filter / mode can never retrieve a raw internal field (AC2, T1
  confused-deputy).
* Every external result body is built ONLY from ``policy.engine.partner_projection``
  (via ``policy.sources.registry.external_projection_for``) — never from raw source
  text (HARD constraint; done rubric #2/#4).
* A denied source simply does not appear; a **zero-result** set carries a
  ``source_gap`` / ``execution_roadmap`` candidate and NEVER reveals that hidden
  material exists (governance invariant; done rubric #7).

Matching is metadata-only. For external principals, matching runs over the
PROJECTION fields (claim / source_type / freshness / provenance_class) — never over
raw bodies, titles, or provenance refs — so the match itself cannot leak.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

from policy import engine
from policy.audit import AuditSink, default_sink
from policy.models import Action, AuditEvent, Principal
from policy.sources import registry
from policy.sources.models import SourceDomain, SourceRecord
from policy.search import routing
from policy.search.models import (
    RouteTarget,
    SearchMode,
    SearchResult,
    SearchResultSet,
)

# A candidate loader returns the SourceRecords to search over (default: the registry
# store). Injected so the runner is DB-free in tests. It is ALWAYS called with an
# explicit bound — the runner never issues an unbounded read (AC10).
CandidateLoader = Callable[..., Iterable[SourceRecord]]

# AC10 scale guards: a single search NEVER scans more than _MAX_SCAN candidate rows
# and NEVER returns more than _PAGE_MAX results per page. Both are hard ceilings.
_MAX_SCAN = 500
_PAGE_MAX = 200


def _default_loader(*, limit: int, offset: int = 0, domain=None) -> Iterable[SourceRecord]:
    """Default candidate loader — a BOUNDED, parameterized, time-limited read over the
    source registry. Never an unbounded ``SELECT *`` (deputy-codex AC10 blocker)."""

    from policy.search.store import load_search_candidates

    return load_search_candidates(limit=limit, offset=offset, domain=domain)


def _route_for_record(rec: SourceRecord, *, llm_router=None):
    """Build a routing suggestion from a record's SAFE metadata (no raw text).

    Two texts are built:

    * ``text`` — the DETERMINISTIC input: structural metadata + claim + internal
      name. Deterministic rules are keyword matches and cannot be prompt-injected.
    * ``llm_text`` — the PROJECTION-SAFE input handed to any LLM router (T8): it
      OMITS the internal ``name`` (a potentially sensitive title) and uses only the
      object type, source type, domain, and the partner-safe ``claim``. Raw bodies
      and provenance refs are never used in either.
    """

    text = " ".join(p for p in (
        rec.object_type.value, rec.source_type, rec.claim or rec.name or "",
        rec.domain.value,
    ) if p)
    llm_text = " ".join(p for p in (
        rec.object_type.value, rec.source_type, rec.claim or "", rec.domain.value,
    ) if p)
    return routing.propose_route(
        text,
        sensitivity=rec.sensitivity,
        never_external=rec.is_never_external,
        llm_router=llm_router,
        llm_text=llm_text,
    )


def _internal_match(rec: SourceRecord, query: str) -> bool:
    """Internal matching over the full internal inventory view (Brisen-only)."""

    if not query:
        return True
    q = query.lower()
    hay = " ".join(
        str(v) for v in (
            rec.source_type, rec.name, rec.claim, rec.domain.value,
            rec.object_type.value, rec.classification.value,
        ) if v
    ).lower()
    return q in hay


def _external_match(projection: Mapping[str, Any], query: str) -> bool:
    """External matching over PROJECTION fields ONLY — never raw text (T-leak)."""

    if not query:
        return True
    q = query.lower()
    hay = " ".join(
        str(projection.get(k, "")) for k in
        ("claim", "source_type", "freshness", "provenance_class")
    ).lower()
    return q in hay


def _audit_result(
    sink: AuditSink,
    principal: Principal,
    *,
    result_ref: Optional[str],
    projected: bool,
    reason_code: str,
    route_target: Optional[str],
) -> None:
    sink.write(
        AuditEvent(
            event_type="search_result",
            principal_org=getattr(principal.org, "value", str(principal.org)),
            principal_role=principal.role,
            action="search",
            object_id=result_ref,
            object_type=None,
            allow=result_ref is not None,
            reason_code=reason_code,
            detail={"projected": projected, "route_target": route_target},
        )
    )


def search(
    principal: Principal,
    query: str,
    mode: SearchMode = SearchMode.INTERNAL_GLOBAL,
    *,
    domain: Optional[SourceDomain] = None,
    section: Optional[RouteTarget] = None,
    limit: int = 100,
    offset: int = 0,
    candidates: Optional[Iterable[SourceRecord]] = None,
    loader: CandidateLoader = _default_loader,
    llm_router=None,
    sink: Optional[AuditSink] = None,
) -> SearchResultSet:
    """Run a search and return a fully policy-gated :class:`SearchResultSet`.

    ``mode`` selects the search behaviour, but **external principals are always
    served partner-safe projections** no matter what mode/filter they pass (AC2).
    ``domain`` filters to a Step-2 source domain (``source_domain`` mode);
    ``section`` filters to a route_target (``section`` mode).

    Scale guards (deputy-codex AC10): ``limit`` is clamped to ``_PAGE_MAX`` and the
    candidate scan is clamped to ``_MAX_SCAN`` — a search NEVER runs an unbounded
    query. A backend (loader) failure PROPAGATES (fail closed): an external caller
    never receives a partial or unfiltered payload on a store/index error.

    ``web_live_hook`` is a DEFINED hook only — it performs no crawling and returns a
    zero-result set routed to ``execution_roadmap`` (any future web result must enter
    ``raw_signal`` first).
    """

    sink = sink or default_sink()
    external = principal.is_external
    limit = max(1, min(int(limit), _PAGE_MAX))
    offset = max(0, int(offset))

    # web/live-source is a hook only in Step 3 — no crawl, explicit empty.
    if mode is SearchMode.WEB_LIVE_HOOK:
        return SearchResultSet(
            mode=mode,
            query=query,
            results=(),
            zero_result_route=RouteTarget.EXECUTION_ROADMAP,
            zero_result_reason=(
                "web/live-source is a Step-3 hook only; any future web result must "
                "enter raw_signal first"
            ),
        )

    # Bounded candidate read. The default loader issues a bounded SQL window; an
    # in-memory candidate list (tests) is hard-capped at _MAX_SCAN too. Loader
    # errors are NOT caught here — they propagate so external callers fail closed.
    if candidates is not None:
        recs = list(candidates)[:_MAX_SCAN]
    else:
        recs = list(loader(limit=_MAX_SCAN, offset=0, domain=domain))

    # Domain filter (source_domain mode) is a safe metadata pre-filter.
    if domain is not None:
        recs = [r for r in recs if r.domain is domain]

    results: list[SearchResult] = []
    for rec in recs:
        suggestion = _route_for_record(rec, llm_router=llm_router)

        # Section mode: only keep records whose proposed route matches the section.
        if section is not None and suggestion.route_target is not section and (
            section not in suggestion.secondary_targets
        ):
            continue

        if external:
            # ALWAYS the projection path for external — engine is the sole control.
            projection = registry.external_projection_for(principal, rec, sink=sink)
            if projection is None:
                continue  # hidden by the engine — no leak, no count
            if not _external_match(projection, query):
                continue
            body = _partner_body(projection)
            results.append(SearchResult(
                result_ref=str(projection.get("object_id")),
                projected=True,
                body=body,
                routing=suggestion,
                policy_reason_code="allow_partner_read",
            ))
            _audit_result(
                sink, principal,
                result_ref=str(projection.get("object_id")),
                projected=True, reason_code="allow_partner_read",
                route_target=suggestion.route_target.value,
            )
        else:
            # Internal path: engine still authorises SEARCH (no UI-only control).
            if rec.is_gap:
                continue  # gap rows carry no payload to search
            item = registry.record_to_evidence_item(rec)
            decision = engine.evaluate(principal, item, Action.SEARCH, sink=sink)
            if not decision.allow:
                continue
            if not _internal_match(rec, query):
                continue
            body = _internal_body(rec)
            results.append(SearchResult(
                result_ref=rec.source_id,
                projected=False,
                body=body,
                routing=suggestion,
                policy_reason_code=decision.reason_code.value,
            ))
            _audit_result(
                sink, principal,
                result_ref=rec.source_id, projected=False,
                reason_code=decision.reason_code.value,
                route_target=suggestion.route_target.value,
            )

    if not results:
        # True zero-result: a source_gap candidate, never a blank, never a hidden-count.
        route, reason = _zero_result_route(query, domain, section, external)
        _audit_result(
            sink, principal, result_ref=None, projected=external,
            reason_code="zero_result", route_target=route.value,
        )
        return SearchResultSet(
            mode=mode, query=query, results=(),
            zero_result_route=route, zero_result_reason=reason,
        )

    # AC10 pagination — return at most one bounded page of results.
    paged = results[offset:offset + limit]
    return SearchResultSet(mode=mode, query=query, results=tuple(paged))


def _partner_body(projection: Mapping[str, Any]) -> Mapping[str, Any]:
    """Build an external result body from a projection ONLY (HARD constraint).

    This function NEVER reads raw source text. It copies the partner-safe projection
    fields and asserts (defence in depth) that no internal field is present. If the
    projection were ever bypassed, there would be no body to return — the search
    tests prove removing the projection call yields no external body.
    """

    forbidden = ("raw_body", "title", "source_refs", "provenance_refs", "source_id")
    body = {k: v for k, v in projection.items() if k not in forbidden}
    # Defence in depth: never let a forbidden key survive even if upstream changes.
    for k in forbidden:
        body.pop(k, None)
    return body


def _internal_body(rec: SourceRecord) -> Mapping[str, Any]:
    """Internal result body — the full internal inventory view (Brisen-only)."""

    return registry.internal_view(rec)


def _zero_result_route(
    query: str,
    domain: Optional[SourceDomain],
    section: Optional[RouteTarget],
    external: bool,
) -> "tuple[RouteTarget, str]":
    """Decide the route + message for a zero-result query.

    **External (deputy-codex T9/AC6): the message is GENERIC.** It never reveals
    hidden-source existence, a result/hidden count, a domain facet, the exact deny
    reason, or any gap inventory — only that nothing is available. An external
    zero-result is indistinguishable whether the corpus is empty or everything was
    policy-hidden.

    Internal: the message may carry the search scope so the internal team can track
    coverage gaps (logged to ``zero_result_gaps``).
    """

    if external:
        # Identical generic message regardless of domain/section/why — no signal.
        return (
            RouteTarget.SOURCE_GAP_UNASSIGNED_REVIEW,
            "no results available for this query",
        )

    if section is RouteTarget.RISK_PERMISSIONS_REVIEW:
        return section, "no visible results in this review section"
    scope = f"domain={domain.value}" if domain else "all permitted sources"
    return (
        RouteTarget.SOURCE_GAP_UNASSIGNED_REVIEW,
        f"no visible results for query over {scope} — logged as a source gap",
    )
