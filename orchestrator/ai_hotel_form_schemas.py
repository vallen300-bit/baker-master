"""AI_HOTEL_VOICE_FORM_1 — git-versioned form-schema registry.

Structured field extraction sits **beside** raw capture, never replaces it
(codex-arch #3349/#3351). The extraction prompt is GENERATED from these schemas
— the schema is the single source of truth and must not live only in prompt
prose. Deterministic validators are the control plane: the model *proposes*
values, this code *decides* what is valid / normalized / needs-review. The model
never writes a confirmed record and never enriches absent fields.

Two forms share ONE substrate (one endpoint, one table, one registry):
  - site_visit.v1   — priority form for Director's site-scouting trips.
  - supplier_card.v1 — trade-show supplier capture (fast-follow).

NO INVENTED FACTS: addresses, ownership, zoning, price, parcel, emails, demand
stats are NEVER guessed — absent → null and surfaced under the form's
research/unknowns field (site_visit) or simply left null (supplier_card).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional


# ── Schema model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FormField:
    """One extractable field.

    type drives normalization + validation:
      string | text → trimmed text (text = multi-sentence)
      email         → lowercased, RFC-ish shape check
      phone         → digits (+ optional leading +), plausibility check
      url           → trimmed, loose URL shape check
      enum          → case-insensitive match into `options`, else invalid
      score         → integer in 1..5 (model-suggested, user-editable)

    critical == True means the user must review/confirm (or mark unknown) before
    the draft can be saved. risk_level == "high" forces needs_review even when
    confidently extracted (no high-risk field is ever auto-accepted).
    """

    key: str
    label: str
    type: str
    critical: bool = False
    options: tuple[str, ...] = ()
    prompt_hint: str = ""
    risk_level: str = "low"
    group: str = ""


@dataclass(frozen=True)
class FormSchema:
    form_type: str
    version: str
    title: str
    fields: tuple[FormField, ...]
    # Optional deterministic post-processor: (values, field_meta) -> None,
    # mutates values in place (e.g. the site_visit unknowns backstop).
    post_process: Optional[Callable[[dict, dict], None]] = None

    def field_map(self) -> dict[str, FormField]:
        return {f.key: f for f in self.fields}


@dataclass
class ExtractionResult:
    """Output of parse_and_validate — the control-plane verdict on one draft."""

    values: dict[str, Optional[str]]
    field_meta: dict[str, dict]
    missing_critical: list[str]
    validation_errors: list[str]
    warnings: list[str]


# ── Enum option sets (kept here, not in prompt prose) ──────────────────────

_PROPERTY_TYPES = ("hotel", "office", "retail", "industrial", "vacant", "mixed_use", "unknown")
_FIT_LEVELS = ("high", "medium", "low", "unknown")
_COMPLEXITY = ("low", "medium", "high", "unknown")
_NEXT_ACTION_SITE = ("research_owner", "research_zoning", "broker_outreach", "revisit", "reject", "compare")

_SUPPLIER_CATEGORIES = ("guest_experience", "operations", "food_beverage", "security",
                        "sustainability", "marketing", "infrastructure", "other")
_FOLLOW_UP_ACTIONS = ("none", "send_info", "schedule_meeting", "request_demo", "share_with_team", "evaluate")


# ── site_visit.v1 (priority form) ──────────────────────────────────────────


def _site_visit_post(values: dict, field_meta: dict) -> None:
    """Deterministic anti-hallucination backstop (AC2).

    Facts that can NEVER come from a walk-by dictation — exact address, owner,
    zoning, parcel, price, permits, comps — are ALWAYS surfaced as research
    items so nothing unknowable is ever presented as established fact. Merges
    whatever the model put in `unknowns_to_research` with the standard list,
    de-duplicated.
    """
    standard = [
        "exact street address" if not values.get("address_or_location_clue") else None,
        "legal owner / title holder",
        "zoning + entitlements",
        "parcel boundaries / lot size",
        "asking price / valuation",
        "permits + building code path",
        "comparable sales / market comps",
    ]
    standard = [s for s in standard if s]

    existing = (values.get("unknowns_to_research") or "").strip()
    have = existing.lower()
    additions = []
    for item in standard:
        head = item.split("/")[0].split("+")[0].strip().split()[0].lower()
        if head not in have:
            additions.append(item)

    parts = []
    if existing:
        parts.append(existing)
    if additions:
        parts.append("; ".join(additions))
    values["unknowns_to_research"] = "; ".join(parts) if parts else None


SITE_VISIT_V1 = FormSchema(
    form_type="site_visit",
    version="site_visit_v1",
    title="Site visit card",
    post_process=_site_visit_post,
    fields=(
        FormField("site_label", "Site label", "string", group="Location",
                  prompt_hint="A short human label for the site, if the speaker gave one."),
        FormField("address_or_location_clue", "Address / location clue", "string", group="Location",
                  risk_level="high",
                  prompt_hint="Any address or location clue ACTUALLY stated. Never invent an address."),
        FormField("geo_context", "Geo context", "text", group="Location",
                  prompt_hint="City / neighborhood / proximity to NVIDIA, airport, convention center, campuses."),
        FormField("current_property_type", "Current property type", "enum", options=_PROPERTY_TYPES,
                  group="Location", prompt_hint="What the property currently is."),
        FormField("site_condition", "Site condition", "text", group="Location",
                  prompt_hint="Physical condition / state of the building or land as described."),
        FormField("access_parking_visibility", "Access / parking / visibility", "text", group="Location",
                  prompt_hint="Road access, parking, street visibility as described."),
        FormField("surrounding_demand_drivers", "Surrounding demand drivers", "text", group="Fit",
                  prompt_hint="Nearby demand drivers — employers, campuses, transit, attractions — if mentioned."),
        FormField("ai_hotel_angle", "AI-Hotel angle", "text", group="Fit",
                  prompt_hint="Why this site could fit the AI-Hotel concept, per the speaker."),
        FormField("hospitality_fit", "Hospitality fit", "enum", options=_FIT_LEVELS, group="Fit",
                  prompt_hint="Overall hospitality fit level (with the speaker's reason in geo/angle fields)."),
        FormField("conversion_complexity", "Conversion complexity", "enum", options=_COMPLEXITY, group="Risks",
                  prompt_hint="How hard a hospitality conversion looks, per the speaker."),
        FormField("red_flags_physical", "Physical red flags", "text", group="Risks",
                  prompt_hint="Structural / physical concerns mentioned (condition, contamination, layout)."),
        FormField("red_flags_deal", "Deal red flags", "text", group="Risks",
                  prompt_hint="Deal / ownership / market concerns mentioned. Never invent ownership facts."),
        FormField("unknowns_to_research", "Unknowns to research", "text", group="Research",
                  prompt_hint="What must be researched later — owner, zoning, parcel, broker, price, comps, permits."),
        FormField("next_action", "Next action", "enum", options=_NEXT_ACTION_SITE, group="Research",
                  prompt_hint="The single best next step."),
        FormField("overall_score", "Overall score (1-5)", "score", group="Score",
                  prompt_hint="A 1-5 attractiveness score (1 = poor, 5 = excellent). Model-suggested; user edits."),
        FormField("notes", "Notes", "text", group="Score",
                  prompt_hint="Anything else relevant not captured by the fields above."),
    ),
)


# ── supplier_card.v1 (fast-follow form) ────────────────────────────────────

SUPPLIER_CARD_V1 = FormSchema(
    form_type="supplier_card",
    version="supplier_card_v1",
    title="Supplier card",
    fields=(
        FormField("company_name", "Company name", "string", critical=True, group="Company",
                  prompt_hint="The supplier / vendor company name."),
        FormField("contact_name", "Contact name", "string", group="Company",
                  prompt_hint="Full name of the person spoken to."),
        FormField("title", "Title / role", "string", group="Company",
                  prompt_hint="Their job title or role at the company."),
        FormField("email", "Email", "email", group="Contact",
                  prompt_hint="Contact email address, exactly as stated."),
        FormField("phone", "Phone", "phone", group="Contact",
                  prompt_hint="Contact phone number, exactly as stated."),
        FormField("website", "Website", "url", group="Contact",
                  prompt_hint="Company website or URL, if mentioned."),
        FormField("booth_or_source", "Booth / source", "string", group="Company",
                  prompt_hint="Where they were met — booth number, hall, or referral."),
        FormField("offering_summary", "What they offer", "text", group="Offering",
                  prompt_hint="One or two sentences on their product or offering."),
        FormField("ai_hotel_category", "AI-Hotel category", "enum", options=_SUPPLIER_CATEGORIES,
                  group="Offering", prompt_hint="Best-fit AI-Hotel category for this supplier."),
        FormField("brisen_relevance", "Brisen relevance", "text", group="Offering",
                  prompt_hint="Why this matters to Brisen / the AI-Hotel, if stated."),
        FormField("follow_up_action", "Follow-up", "enum", options=_FOLLOW_UP_ACTIONS, group="Offering",
                  prompt_hint="Any follow-up action explicitly mentioned."),
        FormField("notes", "Notes", "text", group="Offering",
                  prompt_hint="Anything else relevant not captured by the fields above."),
    ),
)


_REGISTRY: dict[str, FormSchema] = {
    SITE_VISIT_V1.form_type: SITE_VISIT_V1,
    SUPPLIER_CARD_V1.form_type: SUPPLIER_CARD_V1,
}

PROMPT_VERSION = "ai_hotel_form_v1"


def get_form_schema(form_type: str) -> Optional[FormSchema]:
    """Return the schema for a form_type, or None if unknown (caller → 400)."""
    return _REGISTRY.get((form_type or "").strip())


def known_form_types() -> tuple[str, ...]:
    return tuple(_REGISTRY.keys())


# ── Auto-detect form_type from the captured text ───────────────────────────

_SITE_WORDS = (
    "site", "building", "location", "parking", "zoning", "parcel", "lot ",
    "property", "address", "block", "frontage", "vacant", "warehouse", "facade",
    "square feet", "sqft", "sq ft", "acres", "floor plate", "campus", "convention",
    "airport", "neighborhood", "neighbourhood", "nvidia", "santa clara", "downtown",
)
_SUPPLIER_WORDS = (
    "supplier", "vendor", "company", "booth", "stand ", "business card", "contact",
    "email", "phone number", "website", "product", "demo", "offering", "their pricing",
    "sales rep", "trade show", "exhibitor",
)


def detect_form_type(text: str) -> tuple[str, bool]:
    """Infer a form_type from captured text. Returns (form_type, auto_detected).

    Defaults to the priority form (site_visit) when signals are absent or tied —
    Director's trip-capture is the immediate use. auto_detected is always True
    here (the caller marks it False when the user picked explicitly).
    """
    low = (text or "").lower()
    site = sum(1 for w in _SITE_WORDS if w in low)
    supp = sum(1 for w in _SUPPLIER_WORDS if w in low)
    if supp > site:
        return "supplier_card", True
    return "site_visit", True


# ── Normalization + validation (the control plane) ─────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URL_RE = re.compile(r"^(?:https?://)?(?:[\w-]+\.)+[\w-]{2,}(?:[/?#]\S*)?$", re.IGNORECASE)
_ABSENT_TOKENS = {"", "null", "none", "n/a", "na", "unknown", "not stated", "not mentioned", "-"}


def _normalize(field: FormField, raw: Any) -> Optional[str]:
    """Coerce a raw model value to a normalized string, or None if absent.

    score is normalized to a stringified int in 1..5, or None if not coercible.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in _ABSENT_TOKENS:
        return None
    if field.type == "score":
        m = re.search(r"-?\d+", s)
        if not m:
            return None
        n = int(m.group())
        if n < 1 or n > 5:
            return s  # out of range → kept so the validator flags it
        return str(n)
    if field.type == "email":
        return s.lower()
    if field.type == "phone":
        cleaned = re.sub(r"[^\d+]", "", s)
        if cleaned.startswith("+"):
            cleaned = "+" + cleaned[1:].replace("+", "")
        else:
            cleaned = cleaned.replace("+", "")
        return cleaned or None
    if field.type == "enum":
        low = s.lower()
        for opt in field.options:
            if low == opt.lower():
                return opt
        return s  # unmatched → kept so the validator can flag it
    return s


def _validate(field: FormField, value: Optional[str]) -> Optional[str]:
    """Return a human-readable error string, or None if the value is OK.

    A None value is always valid here (criticality is checked separately).
    """
    if value is None:
        return None
    if field.type == "email" and not _EMAIL_RE.match(value):
        return f"{field.key}: '{value}' is not a valid email address."
    if field.type == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) < 7 or len(digits) > 15:
            return f"{field.key}: '{value}' is not a plausible phone number."
    if field.type == "url" and not _URL_RE.match(value):
        return f"{field.key}: '{value}' is not a valid URL."
    if field.type == "enum" and value not in field.options:
        return f"{field.key}: '{value}' is not one of {list(field.options)}."
    if field.type == "score":
        if not re.fullmatch(r"[1-5]", value):
            return f"{field.key}: '{value}' must be an integer 1-5."
    return None


def _coerce_confidence(raw: Any) -> Optional[float]:
    try:
        c = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, c))


def _evidence_source(capture_source: str, confidence: Optional[float], present: bool) -> Optional[str]:
    """field_meta.evidence_source ∈ {audio, photo, typed_note, inferred_low_confidence}."""
    if not present:
        return None
    if confidence is not None and confidence < 0.5:
        return "inferred_low_confidence"
    if capture_source == "audio":
        return "audio"
    if capture_source == "photo":
        return "photo"
    return "typed_note"


# ── Prompt generation (from schema, never hand-written prose) ──────────────


def build_extraction_prompt(schema: FormSchema, transcript: str, note: str) -> str:
    """Generate the extraction instruction from the schema field list."""
    field_lines = []
    for f in schema.fields:
        crit = " (CRITICAL)" if f.critical else ""
        if f.type == "enum":
            spec = f"  Allowed values: {', '.join(f.options)}."
        elif f.type == "score":
            spec = "  An integer 1-5 (1 = poor, 5 = excellent)."
        else:
            spec = ""
        field_lines.append(f'- "{f.key}"{crit}: {f.prompt_hint}{spec}')
    fields_block = "\n".join(field_lines)

    source_parts = []
    if transcript:
        source_parts.append(f"Dictated transcript:\n{transcript}")
    if note:
        source_parts.append(f"Typed note:\n{note}")
    source_block = "\n\n".join(source_parts) if source_parts else "(no text provided)"

    return (
        f"You are extracting a structured {schema.title} from a field capture "
        "(a person dictated observations on the floor or at a site).\n\n"
        "Return ONLY a JSON object. For EACH field key listed below, output an "
        'object: {"value": <string/number or null>, "confidence": <number 0..1>, '
        '"evidence": <short verbatim quote from the source, or null>}.\n\n'
        "HARD RULES:\n"
        "- If a field was not clearly stated, set its value to null. DO NOT guess, "
        "infer, enrich, or fabricate. An absent field is null, never a best-effort.\n"
        "- NEVER invent addresses, ownership, zoning, parcel, price, demand stats, "
        "emails, phone numbers, URLs, or company names. If unsure, value = null.\n"
        "- confidence reflects how clearly the value was stated (1 = explicit, "
        "0.3 = vaguely implied).\n"
        "- For enum fields, value MUST be exactly one of the allowed values, or null.\n\n"
        f"Fields:\n{fields_block}\n\n"
        f"Source:\n{source_block}"
    )


# ── Draft extraction (model output → validated draft) ──────────────────────


def parse_and_validate(schema: FormSchema, model_obj: Any,
                       capture_source: str = "typed_note") -> ExtractionResult:
    """Turn a parsed model object into a validated, normalized draft.

    Fault-tolerant: a non-dict / empty model_obj yields an all-null draft with a
    warning — never an exception (no data loss on invalid model JSON).
    """
    values: dict[str, Optional[str]] = {}
    field_meta: dict[str, dict] = {}
    missing_critical: list[str] = []
    validation_errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(model_obj, dict):
        model_obj = {}
        warnings.append("Extraction produced no structured object — all fields blank; review manually.")

    for f in schema.fields:
        entry = model_obj.get(f.key)
        raw_val: Any = None
        conf_raw: Any = None
        evidence: Any = None
        if isinstance(entry, dict):
            raw_val = entry.get("value")
            conf_raw = entry.get("confidence")
            evidence = entry.get("evidence")
        elif isinstance(entry, (str, int, float)):
            raw_val = entry

        norm = _normalize(f, raw_val)
        err = _validate(f, norm)
        confidence = _coerce_confidence(conf_raw)

        needs_review = False
        if err:
            validation_errors.append(err)
            needs_review = True
        if norm is None and f.critical:
            missing_critical.append(f.key)
            needs_review = True
        if f.risk_level == "high":
            needs_review = True
        if confidence is not None and confidence < 0.5 and norm is not None:
            needs_review = True

        values[f.key] = norm
        field_meta[f.key] = {
            "confidence": confidence,
            "evidence": (str(evidence)[:240] if evidence else None),
            "evidence_source": _evidence_source(capture_source, confidence, norm is not None),
            "normalized_value": norm,
            "needs_review": needs_review,
            "risk_level": f.risk_level,
            "group": f.group,
            "label": f.label,
            "critical": f.critical,
        }

    if schema.post_process:
        try:
            schema.post_process(values, field_meta)
        except Exception:
            # A backstop failure must never break extraction — keep the draft.
            pass

    return ExtractionResult(
        values=values,
        field_meta=field_meta,
        missing_critical=missing_critical,
        validation_errors=validation_errors,
        warnings=warnings,
    )


def validate_corrected(
    schema: FormSchema,
    corrected: dict[str, Any],
    acknowledged_unknown: tuple[str, ...] = (),
) -> tuple[dict[str, Optional[str]], list[str], list[str]]:
    """Re-validate user-corrected values at confirm time (server is the gate).

    Returns (normalized_values, missing_critical, validation_errors). A critical
    field the user explicitly marked unknown is NOT reported missing.
    """
    ack = set(acknowledged_unknown or ())
    normalized: dict[str, Optional[str]] = {}
    missing: list[str] = []
    errors: list[str] = []
    corrected = corrected if isinstance(corrected, dict) else {}

    for f in schema.fields:
        val = _normalize(f, corrected.get(f.key))
        normalized[f.key] = val
        err = _validate(f, val)
        if err:
            errors.append(err)
        if val is None and f.critical and f.key not in ack:
            missing.append(f.key)

    return normalized, missing, errors
