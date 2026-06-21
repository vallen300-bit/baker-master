"""Human-readable source map generator (Step 2, done rubric #5).

Renders the registry as a sectioned-by-domain markdown document comparing the
INTERNAL inventory view against the EXTERNAL projection for a given partner. The
external column is produced ONLY through ``registry.external_projection_for`` —
i.e. the live Step-1 policy engine — so the map can never show a partner something
the engine would deny.

NO content, NO snippets, NO summaries (T6): the external column shows the safe
projection fields (claim / confidence / source_count / freshness / provenance_class)
or an explicit redacted marker. Gap rows render as explicit ⛔ GAP lines (AC8/T7),
never silent blanks.
"""

from __future__ import annotations

from typing import Iterable, Optional

from policy.audit import AuditSink
from policy.models import Org, Principal
from policy.sources import registry
from policy.sources.models import SourceDomain, SourceRecord

_DOMAIN_TITLES = {
    SourceDomain.BAKER_INTERNAL_MEMORY: "1. Baker internal memory",
    SourceDomain.VAULT_PROJECT_ROOMS: "2. Vault / project rooms / curated files",
    SourceDomain.DROPBOX_PROJECT_FILES: "3. Dropbox / project files",
    SourceDomain.COMMS_EMAIL_WA_SLACK: "4. Email / WhatsApp / Slack",
    SourceDomain.FIELD_EVIDENCE: "5. Field evidence",
    SourceDomain.OPEN_WEB: "6. Open web",
    SourceDomain.SITE_SEARCH_PUBLIC: "7. Santa Clara / site-search public data",
    SourceDomain.MARKET_CAPITAL_RESIDENCE: "8. Market / capital / residence",
}


def _external_cell(
    principal: Principal, rec: SourceRecord, sink: Optional[AuditSink]
) -> str:
    if rec.is_gap:
        return "— (gap)"
    proj = registry.external_projection_for(principal, rec, sink=sink)
    if proj is None:
        reason = rec.redaction_reason or "policy-denied"
        return f"🔒 hidden — {reason}"
    # safe projection only — claim + confidence + source_count (no refs/title/body)
    claim = proj.get("claim") or "(no claim)"
    return (
        f"“{claim}” · conf={proj.get('confidence')} · "
        f"sources={proj.get('source_count')} · {proj.get('provenance_class')}"
    )


def generate_source_map(
    records: Iterable[SourceRecord],
    external_principal: Principal,
    *,
    sink: Optional[AuditSink] = None,
) -> str:
    """Return the markdown source map: internal inventory vs external projection
    for ``external_principal``. Every domain section is present even if empty."""

    records = list(records)
    lines: list[str] = []
    lines.append("# AI Hotel Lab — Source Map")
    lines.append("")
    lines.append(
        f"_Internal inventory vs external projection for "
        f"**{external_principal.org.value}** ({external_principal.role}). "
        f"External column is computed by the live Step-1 policy engine — "
        f"classification is not a grant._"
    )
    lines.append("")

    for domain in SourceDomain:
        lines.append(f"## {_DOMAIN_TITLES[domain]}")
        lines.append("")
        domain_rows = [r for r in records if r.domain is domain]
        if not domain_rows:
            lines.append("_No sources registered in this domain yet._")
            lines.append("")
            continue
        lines.append("| Source | Class | Internal status | External view |")
        lines.append("|---|---|---|---|")
        for rec in domain_rows:
            if rec.is_gap:
                internal = (
                    f"⛔ GAP — owner: {rec.gap_owner}; {rec.gap_reason}; "
                    f"next: {rec.gap_next_action}"
                )
            else:
                ne = " · never-external" if rec.is_never_external else ""
                internal = (
                    f"{rec.collection_status.value} · {rec.object_type.value}"
                    f" · raw_internal={rec.raw_body_available_internal}{ne}"
                )
            ext = _external_cell(external_principal, rec, sink)
            name = rec.name or rec.source_type
            lines.append(f"| {name} | {rec.classification.value} | {internal} | {ext} |")
        lines.append("")

    return "\n".join(lines)
