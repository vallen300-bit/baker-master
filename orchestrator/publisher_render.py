"""orchestrator/publisher_render.py — the Publisher render ENGINE.

PUBLISHER_AGENT_INSTALL_1 Part 3. Injected as ``render_fn`` into
``PublisherBusWorker`` (Part 2). Turns structured flight-state facts
(``FLIGHT_DASHBOARD_PACKET``) into Director-facing HTML in the canonical
Pattern-E register, then runs the deterministic contract gates from
``verify-dashboard-render`` SKILL step 4 (== content-contract-v2 rules 9–11).

Scope of this slice (spec SPEC_PUBLISHER_AGENT_v1, checkpoint Part 3):
  * Pure stdlib. **No model calls** — the whole engine is deterministic code
    (Mnilax: "if code can answer the question, code answers it"). Cost is zero.
  * **No filesystem writes** — read-only slice. ``render_ticket`` returns the
    HTML string + the intended surface path; the actual rendered-surface write is
    gated by Part 1's render-ACL guard and lands in a later (canary) slice.
  * **Stateless per render** (spec v1.1(b) / AC7): the module holds no mutable
    state keyed across matters. ``render_ticket`` is a pure function of its
    ticket, so a matter-A fact can never leak into a matter-B render.
  * **Per-flight content contract** (spec v1.1(a)): the flight's OWN contract is
    resolved per render (``resolve_content_contract``); there is no hardcoded
    universal schema baked into the gate/section logic.

Delivers:
  * **AC1** — fact-faithful re-render: every figure / section / receipt the
    packet declares round-trips byte-normalized through the render
    (``extract_*`` == packet facts). The deterministic floor; residual layout is
    AH1's call (brief §10 OPEN-2).
  * **AC2** — the 5 gate functions demonstrably FAIL a seeded violation each
    (German diacritic, banned abbreviation, wall-of-text, missing/blank as-of
    anchor, stale cited version, missing ``Page vN`` stamp, fake-live control,
    non-ledger machine counts).

Render function contract (consumed by ``publisher_bus_worker._render``):
    render_ticket(ticket: dict) -> dict with keys
      status:        "rendered" | "bounce" | "failed"
      surface:       intended rendered-surface path (str)
      gates:         list of {"gate", "verdict": "PASS"|"FAIL", "detail"}
      cost:          {"prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0}
      html:          the rendered HTML (str) — not written to disk this slice
      bounce_reason: named ambiguity when status == "bounce"
      failing_gate:  first FAIL gate name when status == "failed"
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from typing import Any

# ── canonical register (Pattern-E) — compact palette + core classes ──────────
# Custom-property palette lifted verbatim from
# wiki/_templates/flight-dashboard-canonical-v5.html so the render is recognisably
# the same register. Full layout fidelity vs a hand-authored page is AH1's
# residual call (brief §10 OPEN-2); the floor is register + fact preservation.
_CANONICAL_STYLE = """
:root{--canvas:#EFF0F0;--surface:#FFFFFF;--layer:#F4F5F5;--layer-hover:#EAEBEB;
--ink:#1D1F20;--ink-2:#4E5355;--ink-3:#676C6F;--ink-4:#80868A;
--line:#EAEBEB;--line-strong:#DADCDD;--brand:#006399;--brand-subtle:#F5FBFF;
--brand-border:#CFE8F5;--green:#2F934B;--green-bg:#E4F6E9;--amber:#B57E10;
--amber-bg:#FBF2DF;--red:#A5261D;--red-bg:#FBEAE9;--shadow:rgba(29,31,32,.14);
--sans:'Inter',-apple-system,'Segoe UI','Helvetica Neue',sans-serif;
--mono:'SF Mono',ui-monospace,Menlo,monospace;}
html[data-theme="dark"]{--canvas:#17191A;--surface:#1E2122;--layer:#232627;
--ink:#E8EAEB;--ink-2:#C0C4C6;--ink-3:#969B9E;--ink-4:#7A8083;--line:#2C3032;
--line-strong:#3A3F41;--brand:#58ABDB;--brand-subtle:#14262F;--green:#55C078;
--amber:#D9A23A;--red:#E26A60;--shadow:rgba(0,0,0,.5);}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--canvas);color:var(--ink);font:14px/1.6 var(--sans)}
main{padding:30px 40px 60px}.col{max-width:780px;margin:0 auto}
.card{background:var(--surface);border:1px solid var(--line-strong);
border-radius:8px;padding:22px 26px;margin-bottom:14px}
.cardname{font:600 12px var(--sans);letter-spacing:.05em;color:var(--ink-3);
text-transform:uppercase}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.kpi{border:1px solid var(--line-strong);border-radius:8px;padding:13px 15px}
.kpi .n{font:700 24px var(--sans)}.kpi .l{font:600 10px var(--sans);
color:var(--ink-4);text-transform:uppercase}.src{font-size:11px;color:var(--ink-4)}
.src.warn{color:var(--amber)}
.st{font:600 11px var(--sans);padding:2px 9px;border-radius:11px}
.wait{color:var(--amber);background:var(--amber-bg)}
.stale{color:var(--amber);background:var(--amber-bg)}
section{display:none}section.on{display:block}
.gocue{font:600 12px var(--sans);color:var(--ink-4);border:1px solid var(--line-strong);
border-radius:6px;padding:2px 10px;opacity:.55;pointer-events:none}
footer{font-size:11px;color:var(--ink-4);margin-top:24px}
""".strip()

# The section that is engineer-facing and EXEMPT from the wall-of-text guard
# (content-contract-v2 rule 10c exemption, Director-ratified 2026-07-07 #6096).
_ENGINE_LAB_SECTION = "v9"

# ── lexical guard vocab (content-contract-v2 rule 10) ────────────────────────
# 10a: German diacritics. Kept explicit (not a unicode-category sweep) so the
# gate names the exact offending character and never trips on legitimate accents
# in an English rendering of a name.
_GERMAN_DIACRITICS = "äöüÄÖÜß"

# 10a: German terms that recur in this matter family and must be translated.
# Matched case-insensitively as whole words.
_GERMAN_TERMS = (
    "darlehensvertrag", "grundschuld", "gesamtgrundschuld", "beleihungsobjekte",
    "gebührenvereinbarung", "gebuehrenvereinbarung", "sicherungsabtretung",
    "sicherungsabtretungsvertrag", "geschäftsanteilsverpfändung",
    "geschaeftsanteilsverpfaendung", "jahresabschluss", "entwurf", "anlage",
    "vinkulierung", "vorkaufsrecht", "grundbuch", "eintragung",
    "restrukturierung", "gesellschafterstruktur",
)

# 10b: abbreviations that must be spelled out (contract rule 10b).
_BANNED_ABBREVIATIONS = ("RETT", "LTV", "DD", "CP", "AIFM", "VDR")

# static-honesty (rule 11a): a live-looking ratification cue.
_LIVE_CUE_RE = re.compile(r"🟢\s*GO\?|👉\s*YOU\b")

_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


# ─────────────────────────────────────────────────────────────────────────────
# fact model
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Figure:
    """One financial figure/claim tile (contract section 8 / rule 9a)."""
    value: str
    label: str
    source_family: str = ""      # doc family, for the staleness diff (rule 9c)
    source_version: str = ""     # cited version, for the staleness diff
    as_of: str = ""              # as-of date (rule 9a)
    tone: str = ""               # "", "green", "red", "amber"

    @property
    def source_text(self) -> str:
        bits = [b for b in (self.source_family, self.source_version, self.as_of) if b]
        return " · ".join(bits)


@dataclass(frozen=True)
class Receipt:
    """A source pointer (contract rule 3 proof rule)."""
    ref: str
    detail: str = ""


def _norm(text: str) -> str:
    """Byte-normalize a fact token for the deterministic-diff floor (AC1)."""
    return _WS_RE.sub(" ", (text or "").strip())


# ─────────────────────────────────────────────────────────────────────────────
# per-flight content contract (spec v1.1(a) — no universal schema)
# ─────────────────────────────────────────────────────────────────────────────
# The BASE section vocabulary (content-contract-v2 §Sections, Director's reading
# order). A flight's OWN contract may override the section set (e.g. BB-AUK-001
# adds a "v11" Projects section). We never hardcode a single universal schema.
_BASE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("v0", "Overview"),
    ("v1", "Decide now"),
    ("v2", "Financials"),
    ("v4", "Due and Blocking"),
    ("v6", "Top risks"),
    ("v8", "Communications"),
    ("v9", "Engine Lab"),
    ("v10", "Settings"),
)


def resolve_content_contract(ticket: dict[str, Any]) -> dict[str, Any]:
    """Resolve the flight's OWN content contract for this render (spec v1.1(a)).

    Priority: an inline ``content_contract`` object on the ticket, else the base
    contract. Never a hardcoded universal schema — the returned contract governs
    which sections render and which register rules apply. A flight can extend the
    section set via ``content_contract.sections``.
    """
    inline = ticket.get("content_contract")
    sections = list(_BASE_SECTIONS)
    contract_id = "FLIGHT_DASHBOARD_PACKET v2 (base)"
    lexical_english_only = True
    if isinstance(inline, dict):
        contract_id = str(inline.get("id") or contract_id)
        raw_sections = inline.get("sections")
        if isinstance(raw_sections, list) and raw_sections:
            resolved: list[tuple[str, str]] = []
            for s in raw_sections:
                if isinstance(s, dict) and s.get("id"):
                    resolved.append((str(s["id"]), str(s.get("label") or s["id"])))
                elif isinstance(s, (list, tuple)) and len(s) == 2:
                    resolved.append((str(s[0]), str(s[1])))
            if resolved:
                sections = resolved
        if inline.get("lexical_english_only") is False:
            lexical_english_only = False
    return {
        "id": contract_id,
        "sections": sections,
        "lexical_english_only": lexical_english_only,
    }


# ─────────────────────────────────────────────────────────────────────────────
# extractors (byte-normalized fact sets — the AC1 diff basis)
# ─────────────────────────────────────────────────────────────────────────────
_FIGURE_MARKER_RE = re.compile(r'data-figure="([^"]*)"')
_SECTION_RE = re.compile(r'<section id="([^"]*)"')
_RECEIPT_MARKER_RE = re.compile(r'data-receipt="([^"]*)"')
_PAGE_VERSION_RE = re.compile(r"Page v(\d+)")
_DATA_PAGE_VERSION_RE = re.compile(r'data-page-version="(\d+)"')
# fallback (shipped hand-page, no data-* markers): KPI figure values.
_KPI_N_RE = re.compile(r'<div class="n[^"]*"[^>]*>([^<]+)</div>')
# fallback receipts: bus msg ids + matter tags.
_BUS_ID_RE = re.compile(r"#(\d+)")
_MATTER_TAG_RE = re.compile(r"\[([A-Z]{2,}-[A-Z]{2,}-\d+)\]")


def extract_figures(html_text: str) -> list[str]:
    """Ordered, byte-normalized figure tokens. Prefers explicit data-figure
    markers (our render); falls back to KPI ``.n`` values (a hand page)."""
    marked = [_norm(m) for m in _FIGURE_MARKER_RE.findall(html_text)]
    if marked:
        return marked
    return [_norm(m) for m in _KPI_N_RE.findall(html_text)]


def extract_sections(html_text: str) -> list[str]:
    return [_norm(m) for m in _SECTION_RE.findall(html_text)]


def extract_receipts(html_text: str) -> list[str]:
    """Ordered, byte-normalized receipt tokens. Prefers explicit data-receipt
    markers; falls back to bus ids + matter tags in a hand page."""
    marked = [_norm(m) for m in _RECEIPT_MARKER_RE.findall(html_text)]
    if marked:
        return marked
    fallback = ["#" + m for m in _BUS_ID_RE.findall(html_text)]
    fallback += ["[" + m + "]" for m in _MATTER_TAG_RE.findall(html_text)]
    return [_norm(m) for m in fallback]


def extract_page_version(html_text: str) -> int | None:
    """The CURRENT page version. Prefers the authoritative data-page-version
    attribute; else the MAX ``Page vN`` (the Engine-Lab build log lists every
    historical vN, so a plain first-match would be wrong)."""
    attr = _DATA_PAGE_VERSION_RE.search(html_text)
    if attr:
        return int(attr.group(1))
    found = [int(m) for m in _PAGE_VERSION_RE.findall(html_text)]
    return max(found) if found else None


def _visible_text(html_text: str, *, exclude_section: str | None = None) -> str:
    """Strip tags to visible text. Optionally drop one section's content (the
    Engine-Lab section is exempt from the wall-of-text guard, rule 10c)."""
    text = html_text
    if exclude_section:
        text = re.sub(
            rf'<section id="{re.escape(exclude_section)}".*?</section>',
            " ", text, flags=re.DOTALL,
        )
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


# ─────────────────────────────────────────────────────────────────────────────
# RenderDoc — the immutable context every gate consumes
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RenderDoc:
    html: str
    figures: tuple[Figure, ...] = ()
    business_text: str = ""
    sections: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    page_version: int | None = None
    prior_version: int | None = None
    register: dict[str, dict[str, str]] = field(default_factory=dict)
    machine_counts_source: str = ""
    snapshot_mode: str = "read_only"
    lexical_english_only: bool = True


def _verdict(gate: str, ok: bool, detail: str) -> dict[str, str]:
    return {"gate": gate, "verdict": "PASS" if ok else "FAIL", "detail": detail}


# ─────────────────────────────────────────────────────────────────────────────
# the 5 deterministic gates (verify-dashboard-render step 4 / rules 9–11) — AC2
# ─────────────────────────────────────────────────────────────────────────────
def gate_version_stamp(doc: RenderDoc) -> dict[str, str]:
    """Version-stamp gate: a ``Page vN`` stamp is present and, if a prior version
    is known, N has incremented (version-stamp-every-artifact rule)."""
    if doc.page_version is None:
        return _verdict("version-stamp", False, "no `Page vN` stamp found")
    if doc.prior_version is not None and doc.page_version <= doc.prior_version:
        return _verdict(
            "version-stamp", False,
            f"Page v{doc.page_version} did not increment prior v{doc.prior_version}",
        )
    return _verdict("version-stamp", True, f"Page v{doc.page_version}")


def gate_lexical(doc: RenderDoc) -> dict[str, str]:
    """Lexical guard (rule 10a/10b/10c) over business-surface text only (the
    Engine-Lab / build-audit log is exempt from 10c and 10a per v2.5)."""
    text = doc.business_text
    # 10a — German diacritics
    if doc.lexical_english_only:
        for ch in text:
            if ch in _GERMAN_DIACRITICS:
                return _verdict("lexical", False, f"10a German diacritic '{ch}' in business text")
        for term in _GERMAN_TERMS:
            m = re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE)
            if m:
                return _verdict("lexical", False, f"10a German term '{m.group(0)}' not translated")
    # 10b — banned abbreviations (whole word, case-sensitive acronym)
    for abbr in _BANNED_ABBREVIATIONS:
        if re.search(rf"\b{re.escape(abbr)}\b", text):
            return _verdict("lexical", False, f"10b unexplained abbreviation '{abbr}'")
    # 10c — no text block >2 sentences (business surfaces)
    worst = _first_wall_of_text(doc.html)
    if worst is not None:
        n, snippet = worst
        return _verdict("lexical", False, f"10c wall-of-text ({n} sentences): '{snippet[:60]}…'")
    return _verdict("lexical", True, "English-only, no banned abbreviations, no walls of text")


def _first_wall_of_text(html_text: str) -> tuple[int, str] | None:
    """First business-surface text block with >2 sentences (rule 10c). The
    Engine-Lab section is excluded."""
    body = re.sub(
        rf'<section id="{_ENGINE_LAB_SECTION}".*?</section>', " ",
        html_text, flags=re.DOTALL,
    )
    # A "block" = the text content of one leaf-ish element carrying prose. We
    # split on block-level tags and count sentences in each run of visible text.
    for chunk in re.split(r"</?(?:li|p|div|td|span|section)[^>]*>", body):
        run = _WS_RE.sub(" ", _TAG_RE.sub("", chunk)).strip()
        if not run:
            continue
        n = len(_SENTENCE_END_RE.findall(run))
        if n > 2:
            return n, run
    return None


def gate_as_of(doc: RenderDoc) -> dict[str, str]:
    """As-of anchoring (rule 9a): every figure tile carries an as-of date."""
    for fig in doc.figures:
        if not _norm(fig.as_of):
            return _verdict("as-of", False, f"figure '{fig.value}' ({fig.label}) has no as-of anchor")
    return _verdict("as-of", True, f"all {len(doc.figures)} figure(s) carry an as-of anchor")


def gate_staleness(doc: RenderDoc) -> dict[str, str]:
    """Staleness diff (rule 9c): a figure citing an OLDER version than the matter's
    living-documents register = STALE/FAIL until re-verified."""
    if not doc.register:
        return _verdict("staleness", True, "no living-documents register supplied — diff skipped")
    stale: list[str] = []
    for fig in doc.figures:
        fam = _norm(fig.source_family).lower()
        if not fam or fam not in doc.register:
            continue
        current = _norm(doc.register[fam].get("version", ""))
        cited = _norm(fig.source_version)
        if current and cited and _version_is_older(cited, current):
            stale.append(f"'{fig.value}' cites {cited} < register {current} ({fam})")
    if stale:
        return _verdict("staleness", False, "STALE tiles: " + "; ".join(stale))
    return _verdict("staleness", True, "all cited versions match the register")


def _version_number(v: str) -> int | None:
    m = re.search(r"v?(\d+)", v)
    return int(m.group(1)) if m else None


def _version_is_older(cited: str, current: str) -> bool:
    c, cur = _version_number(cited), _version_number(current)
    if c is not None and cur is not None:
        return c < cur
    # non-numeric versions: a mismatch is treated as stale (conservative).
    return _norm(cited) != _norm(current)


def gate_honesty(doc: RenderDoc) -> dict[str, str]:
    """Honesty checks: (11a) a read-only snapshot never renders a fake-live
    control — any GO/YOU cue must be aria-disabled; (section 4) machine ticket
    counts come from a ledger query, never a pasted snapshot."""
    if doc.snapshot_mode == "read_only":
        for m in _LIVE_CUE_RE.finditer(doc.html):
            window = doc.html[max(0, m.start() - 200): m.end() + 200]
            if "aria-disabled" not in window:
                return _verdict("honesty", False,
                                f"11a live cue '{m.group(0)}' not marked aria-disabled on a read-only page")
    if doc.machine_counts_source and doc.machine_counts_source != "ledger_query":
        return _verdict("honesty", False,
                        f"section-4 machine counts source is '{doc.machine_counts_source}', not a ledger query")
    return _verdict("honesty", True, "no fake-live controls; machine counts ledger-sourced")


GATES = (gate_version_stamp, gate_lexical, gate_as_of, gate_staleness, gate_honesty)


def run_gates(doc: RenderDoc) -> list[dict[str, str]]:
    return [gate(doc) for gate in GATES]


# ─────────────────────────────────────────────────────────────────────────────
# facts → HTML (canonical Pattern-E register)
# ─────────────────────────────────────────────────────────────────────────────
def _esc(text: Any) -> str:
    return _html.escape(str(text if text is not None else ""), quote=True)


def _figure_tile(fig: Figure) -> str:
    tone = f" {_esc(fig.tone)}" if fig.tone else ""
    warn = " warn" if fig.source_version and not fig.as_of else ""
    return (
        f'<div class="kpi">'
        f'<div class="n{tone}" data-figure="{_esc(fig.value)}">{_esc(fig.value)}</div>'
        f'<div class="l">{_esc(fig.label)}</div>'
        f'<div class="src{warn}" data-as-of="{_esc(fig.as_of)}"'
        f' data-source-family="{_esc(fig.source_family)}"'
        f' data-source-version="{_esc(fig.source_version)}">{_esc(fig.source_text)}</div>'
        f"</div>"
    )


def _receipt_span(rcpt: Receipt) -> str:
    return f'<span class="src" data-receipt="{_esc(rcpt.ref)}">Receipt: {_esc(rcpt.ref)}' + (
        f" — {_esc(rcpt.detail)}" if rcpt.detail else ""
    ) + "</span>"


def render_html(facts: "PublisherFacts", contract: dict[str, Any]) -> str:
    """Render the packet into canonical Pattern-E HTML. Every figure/receipt
    emits an explicit ``data-*`` marker so the AC1 fact-set round-trips exactly;
    residual layout fidelity vs a hand page is AH1's call (brief §10 OPEN-2)."""
    sections = contract["sections"]
    nav = "".join(f'<a data-v="{_esc(sid)}">{_esc(label)}</a>' for sid, label in sections)

    # section 8 — financials (figure tiles)
    fig_html = "".join(_figure_tile(f) for f in facts.figures) or '<div class="src">none this week</div>'
    # receipts
    rcpt_html = "".join(_receipt_span(r) for r in facts.receipts)
    # decide-now (static honesty on any GO/YOU cue — rule 11a)
    decide_html = _render_decisions(facts)
    # engine-lab build log carries the Page vN history (exempt from 10c)
    version_log = "".join(f"<li>Page v{v}</li>" for v in facts.version_history)

    body_sections = []
    for sid, label in sections:
        if sid == "v0":
            inner = (
                f'<div class="card"><div class="cardname">{_esc(facts.flight_name)}</div>'
                f'<div class="src">Goal: {_esc(facts.business_outcome)}</div></div>'
            )
        elif sid == "v1":
            inner = decide_html
        elif sid == "v2":
            inner = f'<div class="card"><div class="cardname">Financials</div><div class="kpis">{fig_html}</div></div>'
        elif sid == _ENGINE_LAB_SECTION:
            inner = (
                f'<div class="card"><div class="cardname">Engine Lab</div>'
                f'<div class="src">Dashboard build &amp; audit trail — engineer-facing (rule 10c exempt)</div>'
                f"<ul>{version_log}</ul>{rcpt_html}</div>"
            )
        else:
            inner = f'<div class="card"><div class="cardname">{_esc(label)}</div><div class="src">none this week</div></div>'
        cls = " on" if sid == "v0" else ""
        body_sections.append(f'<section id="{_esc(sid)}" class="{cls.strip()}">{inner}</section>')

    stamp = (
        f'<footer data-page-version="{facts.page_version}">'
        f"Page v{facts.page_version} · as of {_esc(facts.last_refreshed_at)} · "
        f"{_esc(contract['id'])} · writer: publisher (single renderer)</footer>"
    )
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"<title>{_esc(facts.project_code)} · {_esc(facts.flight_name)} · Flight Dashboard</title>\n"
        f"<style>\n{_CANONICAL_STYLE}\n</style>\n</head>\n<body>\n"
        f'<aside><div class="kicker">{_esc(facts.desk_owner)}</div>'
        f"<h1>{_esc(facts.flight_name)}</h1>"
        f'<div class="fcode">{_esc(facts.project_code)} · CEO view</div>'
        f"<nav>{nav}</nav></aside>\n"
        f'<main><div class="col">\n'
        + "\n".join(body_sections)
        + f"\n{stamp}\n</div></main>\n</body>\n</html>\n"
    )


def _render_decisions(facts: "PublisherFacts") -> str:
    if not facts.decisions:
        return '<div class="card"><div class="cardname">Decide now</div><div class="src">none this week</div></div>'
    rows = []
    for d in facts.decisions:
        cue = ""
        if d.get("cue"):
            # static honesty (rule 11a): a snapshot renders GO/YOU planned + disabled.
            cue = (
                f'<span class="gocue" aria-disabled="true">{_esc(d["cue"])}'
                " · planned, live in step-2</span>"
            )
        rows.append(
            f'<div class="card"><div class="cardname">Decide now</div>'
            f'<div class="src">{_esc(d.get("question", ""))}</div>{cue}</div>'
        )
    return "".join(rows)


# ─────────────────────────────────────────────────────────────────────────────
# packet → PublisherFacts (validation + normalization)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PublisherFacts:
    project_code: str
    flight_name: str
    matter_slug: str
    desk_owner: str
    business_outcome: str
    snapshot_mode: str
    page_version: int
    last_refreshed_at: str
    figures: tuple[Figure, ...] = ()
    receipts: tuple[Receipt, ...] = ()
    decisions: tuple[dict[str, Any], ...] = ()
    version_history: tuple[int, ...] = ()
    prior_version: int | None = None
    machine_counts_source: str = ""


_REQUIRED = ("project_code", "matter_slug")


def facts_from_ticket(ticket: dict[str, Any]) -> PublisherFacts:
    """Normalize a FLIGHT_DASHBOARD_PACKET ticket into typed facts. Raises
    ``ValueError`` (bounced by ``render_ticket``) when a required field is absent
    — Publisher owns FORM only, so a malformed packet goes back to the desk."""
    missing = [k for k in _REQUIRED if not str(ticket.get(k) or "").strip()]
    if missing:
        raise ValueError(f"packet missing required field(s): {', '.join(missing)}")

    figures = tuple(_figure_from(f) for f in _as_list(ticket.get("figures")))
    receipts = tuple(
        Receipt(ref=str(r.get("ref", "")), detail=str(r.get("detail", "")))
        if isinstance(r, dict) else Receipt(ref=str(r))
        for r in _as_list(ticket.get("receipts"))
    )
    # a build-infra v1 packet carries no explicit figures/receipts; derive receipt
    # pointers from its dispatch_refs + evidence so the fact-set is non-empty (A2).
    if not receipts:
        receipts = _derive_receipts(ticket)
    decisions = tuple(d for d in _as_list(ticket.get("decisions")) if isinstance(d, dict))
    version_history = tuple(
        int(v) for v in _as_list(ticket.get("version_history")) if str(v).isdigit()
    )
    page_version = _coerce_int(ticket.get("page_version"), default=1)
    if page_version not in version_history:
        version_history = version_history + (page_version,)

    return PublisherFacts(
        project_code=str(ticket["project_code"]),
        flight_name=str(ticket.get("flight_name") or ticket["project_code"]),
        matter_slug=str(ticket["matter_slug"]),
        desk_owner=str(ticket.get("desk_owner") or ""),
        business_outcome=str(ticket.get("business_outcome") or ""),
        snapshot_mode=str(ticket.get("snapshot_mode") or "read_only"),
        page_version=page_version,
        last_refreshed_at=str(ticket.get("last_refreshed_at") or ""),
        figures=figures,
        receipts=receipts,
        decisions=decisions,
        version_history=tuple(sorted(set(version_history))),
        prior_version=_coerce_int(ticket.get("prior_version"), default=None),
        machine_counts_source=str(ticket.get("machine_counts_source") or ""),
    )


def _figure_from(f: Any) -> Figure:
    if not isinstance(f, dict):
        return Figure(value=str(f), label="")
    return Figure(
        value=str(f.get("value", "")),
        label=str(f.get("label", "")),
        source_family=str(f.get("source_family", "")),
        source_version=str(f.get("source_version", "")),
        as_of=str(f.get("as_of", "")),
        tone=str(f.get("tone", "")),
    )


def _derive_receipts(ticket: dict[str, Any]) -> tuple[Receipt, ...]:
    out: list[Receipt] = []
    for d in _as_list(ticket.get("dispatch_refs")):
        if isinstance(d, dict) and d.get("ref"):
            out.append(Receipt(ref=str(d["ref"]), detail=str(d.get("status", ""))))
    for e in _as_list(ticket.get("evidence")):
        if isinstance(e, dict) and e.get("label"):
            out.append(Receipt(ref=str(e["label"]), detail=str(e.get("status", ""))))
    for b in _as_list(ticket.get("blockers")):
        if isinstance(b, dict) and b.get("proof"):
            out.append(Receipt(ref=str(b["proof"]), detail=str(b.get("label", ""))))
    return tuple(out)


def _as_list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, list) else []


def _coerce_int(v: Any, *, default: int | None) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# render_ticket — the render_fn injected into PublisherBusWorker
# ─────────────────────────────────────────────────────────────────────────────
def _surface_path(facts: PublisherFacts) -> str:
    return (
        "_ops/build/baker-os-v2/05_outputs/flight-dashboards/"
        f"{facts.project_code}/dashboard-v1-pattern-d.html"
    )


def build_render_doc(
    facts: PublisherFacts, contract: dict[str, Any], html_text: str,
    *, register: dict[str, dict[str, str]] | None = None,
) -> RenderDoc:
    """Assemble the immutable gate context from a render. Stateless: a pure
    function of its arguments (spec v1.1(b) / AC7)."""
    return RenderDoc(
        html=html_text,
        figures=facts.figures,
        business_text=_visible_text(html_text, exclude_section=_ENGINE_LAB_SECTION),
        sections=tuple(extract_sections(html_text)),
        receipts=tuple(extract_receipts(html_text)),
        page_version=extract_page_version(html_text),
        prior_version=facts.prior_version,
        register=dict(register or {}),
        machine_counts_source=facts.machine_counts_source,
        snapshot_mode=facts.snapshot_mode,
        lexical_english_only=contract.get("lexical_english_only", True),
    )


def _zero_cost() -> dict[str, Any]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "usd": 0.0}


def render_ticket(
    ticket: dict[str, Any],
    *, register: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Render one flight-dashboard ticket. Pure, stateless, no model call, no
    filesystem write. Returns the ``publisher_bus_worker`` render-fn contract."""
    # 1. facts (bounce a malformed packet back to the desk — FORM-only lane)
    try:
        facts = facts_from_ticket(ticket)
    except ValueError as e:
        return {
            "status": "bounce",
            "surface": "",
            "gates": [],
            "cost": _zero_cost(),
            "bounce_reason": str(e),
        }

    # 2. flight's OWN content contract (spec v1.1(a) — no universal schema)
    contract = resolve_content_contract(ticket)

    # 3. render + gate
    html_text = render_html(facts, contract)
    doc = build_render_doc(facts, contract, html_text, register=register)
    gates = run_gates(doc)

    failing = next((g for g in gates if g["verdict"] == "FAIL"), None)
    result: dict[str, Any] = {
        "status": "failed" if failing else "rendered",
        "surface": _surface_path(facts),
        "gates": gates,
        "cost": _zero_cost(),
        "html": html_text,
    }
    if failing:
        result["failing_gate"] = failing["gate"]
        result["bounce_reason"] = failing["detail"]
    return result
